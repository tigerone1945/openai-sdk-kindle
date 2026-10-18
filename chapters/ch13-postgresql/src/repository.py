"""Repository:SQLを知っているのは、ここだけ。

Toolは、このモジュールの型(SalesRepository)だけを知る。SQLiteかPostgreSQLかは、
接続(Engine)の違いで、ここから先は知らない。SQLは、両方で動く書き方にする。
方言の差(スキーマの取得、並びの基準)は、SQLAlchemyの inspect() で吸収する。
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from functools import wraps
from typing import Any, Protocol

from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from catalog import DIMENSIONS, require_table, resolve_join


# --- 契約:Repositoryが返すもの(DBの型を、外へ漏らさない) ----------


@dataclass(frozen=True)
class SalesSummary:
    order_count: int
    total_sales: int
    cancelled_count: int
    review_count: int


@dataclass(frozen=True)
class LabeledSales:
    label: str
    sales: int


@dataclass(frozen=True)
class ReviewOrder:
    order_id: str
    customer_name: str
    product_name: str
    total_amount: int
    status: str


@dataclass(frozen=True)
class Column:
    name: str
    type: str


@dataclass(frozen=True)
class JoinCounts:
    left_duplicate_keys: int    # 複数行に現れるKeyの数
    right_duplicate_keys: int
    left_unmatched_rows: int    # 相手に対応する行がない行数
    right_unmatched_rows: int


class StorageUnavailableError(Exception):
    """保存先に繋がらない・接続が足りない・ロックが解けない。再試行できる障害。

    DBドライバの例外は、ここで翻訳する。Toolも、APIも、どのDBを使っているかを知らずに済む。
    """


def is_storage_unavailable(error: BaseException | None) -> bool:
    """例外そのものか、その原因(__cause__ / __context__)のどれかが、保存先の障害か。

    Agent SDK は、Toolの例外を UserError に包んで投げ直す。専門Agentの入れ子では、さらに包まれる。
    包まれても、原因をたどれば分かるようにする。
    """
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, StorageUnavailableError):
            return True
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return False


class RegisterResult(Enum):
    REGISTERED = "registered"
    ALREADY_REGISTERED = "already_registered"
    UNKNOWN_ORDER = "unknown_order"


class SalesRepository(Protocol):
    def sales_summary(self) -> SalesSummary: ...
    def sales_by_dimension(self, dimension: str) -> list[LabeledSales]: ...
    def review_orders(self, limit: int) -> list[ReviewOrder]: ...
    def register_review_request(self, order_id: str, reason: str) -> RegisterResult: ...
    def table_columns(self, table: str) -> list[Column]: ...
    def join_counts(self, left: str, right: str) -> JoinCounts: ...
    def preview_join(self, left: str, right: str, limit: int) -> list[dict[str, Any]]: ...
    def ping(self) -> None: ...


def is_unavailable(error: Exception, dialect: str) -> bool:
    """再試行で直りうる障害か。SQLiteの OperationalError には「no such table」のような、直らないものも含まれる。"""
    if isinstance(error, (InterfaceError, PoolTimeoutError)):
        return True
    if isinstance(error, OperationalError):
        return dialect != "sqlite" or any(m in str(error) for m in ("locked", "busy", "unable to open"))
    return False


def translated(method):
    """Repositoryの公開メソッドが、DBドライバの例外を StorageUnavailableError に翻訳する。"""

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except (OperationalError, InterfaceError, PoolTimeoutError) as e:
            if is_unavailable(e, self.read_engine.dialect.name):
                raise StorageUnavailableError("保存先を利用できません。") from e
            raise

    return wrapper


def plain(value: Any) -> Any:
    """DBごとに違う型(Decimal・date)を、どのDBでも同じ素朴な値にそろえる。"""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


# --- 実装:1つ。Engineを替えれば、SQLiteでもPostgreSQLでも動く ------


class SqlSalesRepository:
    """読み取りは read_engine(読み取り専用の接続・役割)、書き込みは write_engine で行う。"""

    def __init__(self, read_engine: Engine, write_engine: Engine):
        self.read_engine = read_engine
        self.write_engine = write_engine

    @translated
    def ping(self) -> None:
        for engine in (self.read_engine, self.write_engine):
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))

    @translated
    def sales_summary(self) -> SalesSummary:
        with self.read_engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT
                        COUNT(*) AS order_count,
                        COALESCE(SUM(sales_amount), 0) AS total_sales,
                        COALESCE(SUM(CASE WHEN status = 'キャンセル' THEN 1 ELSE 0 END), 0) AS cancelled_count,
                        COALESCE(SUM(CASE WHEN review_flag = '要レビュー' THEN 1 ELSE 0 END), 0) AS review_count
                    FROM orders
                    """
                )
            ).mappings().one()

        return SalesSummary(**{k: int(v) for k, v in row.items()})

    @translated
    def sales_by_dimension(self, dimension: str) -> list[LabeledSales]:
        """許可された切り口で売上を集計する。識別子は許可リストからだけ組み立てる。"""
        if dimension not in DIMENSIONS:
            raise ValueError(f"許可されていない切り口です: {dimension}")

        table, column = DIMENSIONS[dimension]

        if table == "orders":
            source, label = "orders AS o", f"o.{column}"
        else:
            left_key, right_key = resolve_join("orders", table)
            source = f"orders AS o JOIN {require_table(table)} AS d ON o.{left_key} = d.{right_key}"
            label = f"d.{column}"

        with self.read_engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT {label} AS label, SUM(o.sales_amount) AS sales
                    FROM {source}
                    GROUP BY {label}
                    ORDER BY sales DESC, label
                    """
                )
            ).all()

        return [LabeledSales(label=r[0], sales=int(r[1])) for r in rows]

    @translated
    def review_orders(self, limit: int) -> list[ReviewOrder]:
        with self.read_engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT o.order_id, c.customer_name, p.product_name, o.total_amount, o.status
                    FROM orders AS o
                    JOIN customers AS c ON o.customer_id = c.customer_id
                    JOIN products AS p ON o.product_id = p.product_id
                    WHERE o.review_flag = '要レビュー'
                    ORDER BY o.total_amount DESC, o.order_id
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).all()

        return [ReviewOrder(r[0], r[1], r[2], int(r[3]), r[4]) for r in rows]

    @translated
    def register_review_request(self, order_id: str, reason: str) -> RegisterResult:
        """存在確認と登録を、1つのトランザクションで行う。重複は主キーが防ぐ。"""
        with self.write_engine.begin() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM orders WHERE order_id = :order_id"),
                {"order_id": order_id},
            ).first()

            if exists is None:
                return RegisterResult.UNKNOWN_ORDER

            inserted = conn.execute(
                text(
                    """
                    INSERT INTO review_requests (order_id, reason, created_at)
                    VALUES (:order_id, :reason, :created_at)
                    ON CONFLICT (order_id) DO NOTHING
                    """
                ),
                {
                    "order_id": order_id,
                    "reason": reason,
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                },
            ).rowcount

        return RegisterResult.REGISTERED if inserted == 1 else RegisterResult.ALREADY_REGISTERED

    @translated
    def table_columns(self, table: str) -> list[Column]:
        # PRAGMA table_info(SQLite)も information_schema(PostgreSQL)も使わず、方言の差を inspect() に任せる。
        columns = inspect(self.read_engine).get_columns(require_table(table))
        return [Column(name=c["name"], type=str(c["type"])) for c in columns]

    @translated
    def join_counts(self, left: str, right: str) -> JoinCounts:
        relation = resolve_join(left, right)
        if relation is None:
            raise ValueError(f"許可されていないJoinです: {left}, {right}")

        left_key, right_key = relation
        left, right = require_table(left), require_table(right)

        def duplicates(conn, table: str, column: str) -> int:
            return int(conn.execute(text(
                f"SELECT COUNT(*) FROM (SELECT {column} FROM {table} GROUP BY {column} HAVING COUNT(*) > 1) AS d"
            )).scalar_one())

        def unmatched(conn, table: str, column: str, other: str, other_column: str) -> int:
            return int(conn.execute(text(
                f"SELECT COUNT(*) FROM {table} AS t WHERE NOT EXISTS "
                f"(SELECT 1 FROM {other} AS o WHERE o.{other_column} = t.{column})"
            )).scalar_one())

        with self.read_engine.connect() as conn:
            return JoinCounts(
                left_duplicate_keys=duplicates(conn, left, left_key),
                right_duplicate_keys=duplicates(conn, right, right_key),
                left_unmatched_rows=unmatched(conn, left, left_key, right, right_key),
                right_unmatched_rows=unmatched(conn, right, right_key, left, left_key),
            )

    @translated
    def preview_join(self, left: str, right: str, limit: int) -> list[dict[str, Any]]:
        relation = resolve_join(left, right)
        if relation is None:
            raise ValueError(f"許可されていないJoinです: {left}, {right}")

        left_key, right_key = relation
        left, right = require_table(left), require_table(right)
        inspector = inspect(self.read_engine)

        # 両Tableに同名の列(customer_idなど)があるため、接頭辞を付けて衝突を避ける。
        columns = [
            f"{alias}.{c['name']} AS {alias}_{c['name']}"
            for alias, table in (("l", left), ("r", right))
            for c in inspector.get_columns(table)
        ]
        # 並びの基準は、方言ごとの行番号(rowid)ではなく、主キー。
        order_by = ", ".join(
            f"l.{c}" for c in inspector.get_pk_constraint(left)["constrained_columns"]
        )

        with self.read_engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT {", ".join(columns)}
                    FROM {left} AS l JOIN {right} AS r ON l.{left_key} = r.{right_key}
                    ORDER BY {order_by}
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).mappings().all()

        return [{k: plain(v) for k, v in row.items()} for row in rows]
