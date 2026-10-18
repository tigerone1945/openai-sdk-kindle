"""Repositoryの契約を、SQLiteとPostgreSQLの両方で確認する(同じテストを、両方に対して実行する)。

実行(リポジトリのルートから):
    uv run --with pytest pytest chapters/ch13-postgresql/tests -q                       # SQLiteのみ
    TEST_PG_URL=postgresql+psycopg://postgres:pass@127.0.0.1:55432/postgres \
        uv run --with pytest pytest chapters/ch13-postgresql/tests -q                   # 両方
"""
import threading

import pandas as pd
import pytest
from sqlalchemy import text

from conftest import CSV, M

DIMENSIONS = M.catalog.DIMENSIONS
RegisterResult = M.repository.RegisterResult


@pytest.fixture(scope="module")
def df():
    return pd.read_csv(CSV)


def test_summary_matches_csv(repo, df):
    s = repo.sales_summary()
    assert s.order_count == len(df)
    assert s.total_sales == int(df["sales_amount"].sum())
    assert s.cancelled_count == int((df["status"] == "キャンセル").sum())
    assert s.review_count == int((df["review_flag"] == "要レビュー").sum())
    assert all(type(v) is int for v in vars(s).values())  # DecimalではなくPythonのint


@pytest.mark.parametrize("dimension,column", [("category", "category"), ("customer_type", "customer_type"), ("region", "region")])
def test_dimension_matches_pandas(repo, df, dimension, column):
    expected = sorted(df.groupby(column)["sales_amount"].sum().items(), key=lambda kv: (-kv[1], kv[0]))
    got = [(r.label, r.sales) for r in repo.sales_by_dimension(dimension)]
    assert got == [(k, int(v)) for k, v in expected]
    assert all(type(sales) is int for _, sales in got)


def test_every_dimension_is_covered_by_a_test():
    assert set(DIMENSIONS) == {"category", "customer_type", "region"}


def test_unknown_dimension_is_rejected(repo):
    with pytest.raises(ValueError, match="切り口"):
        repo.sales_by_dimension("customer_name; DROP TABLE orders")


def test_review_orders_are_sorted_and_limited(repo, df):
    expected = df[df["review_flag"] == "要レビュー"].sort_values(["total_amount", "order_id"], ascending=[False, True])
    rows = repo.review_orders(5)
    assert [r.order_id for r in rows] == list(expected["order_id"].head(5))
    assert rows[0].customer_name and rows[0].product_name  # JOINで名前が付く
    assert isinstance(rows[0].total_amount, int)


def test_register_review_request(repo):
    assert repo.register_review_request("O0001", "確認") is RegisterResult.REGISTERED
    assert repo.register_review_request("O0001", "確認") is RegisterResult.ALREADY_REGISTERED
    assert repo.register_review_request("O9999", "x") is RegisterResult.UNKNOWN_ORDER


def test_sql_in_an_order_id_is_just_a_value(repo):
    assert repo.register_review_request("O0001'; DROP TABLE orders; --", "x") is RegisterResult.UNKNOWN_ORDER
    assert repo.sales_summary().order_count == 300


def test_concurrent_registration_of_the_same_order_inserts_once(repo):
    """20並行で同じ注文を登録しても、1件だけが登録される(確認と登録の隙間がない)。"""
    results, errors = [], []

    def worker():
        try:
            results.append(repo.register_review_request("O0010", "並行"))
        except Exception as e:  # noqa: BLE001 - 失敗の種類を、テストの結果として見る
            errors.append(repr(e))

    threads = [threading.Thread(target=worker) for _ in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert errors == []
    assert results.count(RegisterResult.REGISTERED) == 1
    assert results.count(RegisterResult.ALREADY_REGISTERED) == 19


def test_table_columns_have_the_same_names(repo, df):
    expected = {
        "orders": ["order_id", "order_date", "customer_id", "product_id", "unit_price", "quantity", "discount_rate",
                   "subtotal", "total_amount", "sales_amount", "region", "salesperson", "status", "review_flag"],
        "customers": ["customer_id", "customer_name", "customer_type"],
        "products": ["product_id", "product_name", "category"],
    }
    for table, names in expected.items():
        assert [c.name for c in repo.table_columns(table)] == names


def test_table_columns_reject_unlisted_tables(repo):
    with pytest.raises(ValueError):
        repo.table_columns("sqlite_master")
    with pytest.raises(ValueError):
        repo.table_columns("review_requests")  # 書き込み先のTableは、探索の対象にしない


@pytest.mark.parametrize("left,right,left_dups,right_dups", [("orders", "customers", 10, 0), ("orders", "products", 12, 0), ("customers", "orders", 0, 10)])
def test_join_counts(repo, left, right, left_dups, right_dups):
    c = repo.join_counts(left, right)
    assert (c.left_duplicate_keys, c.right_duplicate_keys) == (left_dups, right_dups)
    assert c.left_unmatched_rows == c.right_unmatched_rows == 0


def test_join_counts_reject_unallowed_join(repo):
    with pytest.raises(ValueError):
        repo.join_counts("customers", "products")


def test_preview_join_keeps_both_key_columns_and_plain_values(repo):
    rows = repo.preview_join("orders", "customers", 3)
    assert [r["l_order_id"] for r in rows] == ["O0001", "O0002", "O0003"]  # 主キー順(行番号に頼らない)
    first = rows[0]
    assert {"l_customer_id", "r_customer_id", "r_customer_name"} <= set(first)
    # どのDBでも、同じ素朴な値(日付は文字列、割引率は数値)
    assert first["l_order_date"] == "2026-02-27" and isinstance(first["l_order_date"], str)
    assert first["l_discount_rate"] == pytest.approx(0.1) and isinstance(first["l_discount_rate"], float)
    assert isinstance(first["l_unit_price"], int)


def test_preview_order_does_not_depend_on_physical_row_order(repo):
    """行を更新すると、PostgreSQLでは行の物理的な位置が変わる。並びは、物理的な順序ではなく主キーで決まる。"""
    with repo.write_engine.begin() as conn:
        conn.execute(text("UPDATE orders SET unit_price = unit_price WHERE order_id IN ('O0001', 'O0002')"))

    assert [r["l_order_id"] for r in repo.preview_join("orders", "customers", 3)] == ["O0001", "O0002", "O0003"]


def test_preview_join_limit_is_applied(repo):
    assert len(repo.preview_join("orders", "products", 7)) == 7


def test_ping(repo):
    repo.ping()


# --- 保存先の障害:DBドライバの例外を、Repositoryの例外に翻訳する --------------

StorageUnavailableError = M.repository.StorageUnavailableError
SqlSalesRepository = M.repository.SqlSalesRepository


def test_unreachable_database_becomes_storage_unavailable():
    """繋がらないDB(閉じたポート)でも、呼び出し側が受け取るのは、保存先の種類を知らなくてよい例外。"""
    from sqlalchemy import create_engine

    engine = create_engine("postgresql+psycopg://u:p@127.0.0.1:1/none", connect_args={"connect_timeout": 1})
    repo = SqlSalesRepository(engine, engine)
    for call in (repo.ping, repo.sales_summary, lambda: repo.register_review_request("O0001", "x")):
        with pytest.raises(StorageUnavailableError):
            call()


def test_pool_exhaustion_becomes_storage_unavailable(tmp_path):
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{tmp_path / 'p.db'}", pool_size=1, max_overflow=0, pool_timeout=0.3)
    repo = SqlSalesRepository(engine, engine)
    held = engine.connect()
    try:
        with pytest.raises(StorageUnavailableError):
            repo.ping()
    finally:
        held.close()


def test_sqlite_lock_becomes_storage_unavailable_but_a_missing_table_does_not(tmp_path):
    """SQLiteの OperationalError には、再試行で直るもの(ロック)と、直らないもの(Tableがない)がある。"""
    from sqlalchemy import create_engine, text as sql

    path = tmp_path / "x.db"
    engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 0.2})
    with engine.begin() as conn:
        conn.execute(sql("CREATE TABLE orders (order_id TEXT PRIMARY KEY)"))
        conn.execute(sql("CREATE TABLE review_requests (order_id TEXT PRIMARY KEY, reason TEXT, created_at TEXT)"))
        conn.execute(sql("INSERT INTO orders VALUES ('O1')"))
    repo = SqlSalesRepository(engine, engine)

    holder = engine.connect()
    holder.execute(sql("BEGIN IMMEDIATE"))  # 書き込みロックを握ったままにする
    try:
        with pytest.raises(StorageUnavailableError):
            repo.register_review_request("O1", "x")
    finally:
        holder.rollback()
        holder.close()

    from sqlalchemy.exc import OperationalError
    with pytest.raises(OperationalError):  # Tableが無いのは、再試行しても直らない: 翻訳しない
        SqlSalesRepository(create_engine(f"sqlite:///{tmp_path / 'empty.db'}"), engine).sales_summary()
