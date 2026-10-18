import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from pydantic import BaseModel

from agents import (
    Agent,
    GuardrailFunctionOutput,
    RunContextWrapper,
    Runner,
    SQLiteSession,
    TResponseInputItem,
    function_tool,
    input_guardrail,
    trace,
)


load_dotenv()

SALES_DB_PATH = Path(
    "data/sales.db"
)

AUDIT_LOG_PATH = Path(
    "data/audit_log.jsonl"
)

SESSION_DB_PATH = Path(
    "data/conversations.db"
)


class SalesAnalysisResult(BaseModel):
    question: str
    analysis_type: str
    result_summary: str
    key_findings: list[str]
    next_action: str


# --- Join Governance: 許可したJoinと、使ってよい切り口 ------------
# Agent ではなく、開発者がコードで管理する(レビューを通して変更する)。

BUSINESS_TABLES = ("orders", "customers", "products")

ALLOWED_JOINS: dict[tuple[str, str], tuple[str, str]] = {
    ("orders", "customers"): ("customer_id", "customer_id"),
    ("orders", "products"): ("product_id", "product_id"),
}

# Semantic Layer(最小形): 「切り口」という業務用語を、(Table, 列)に結びつける。
DIMENSIONS: dict[str, tuple[str, str]] = {
    "category": ("products", "category"),
    "customer_type": ("customers", "customer_type"),
    "region": ("orders", "region"),
}


def resolve_join(left: str, right: str) -> tuple[str, str] | None:
    """許可されたJoinなら、(leftの結合キー, rightの結合キー)を返す。"""
    if (left, right) in ALLOWED_JOINS:
        return ALLOWED_JOINS[(left, right)]

    if (right, left) in ALLOWED_JOINS:
        right_key, left_key = ALLOWED_JOINS[(right, left)]
        return left_key, right_key

    return None


def require_table(name: str) -> str:
    """SQLに埋め込む識別子は、許可リストにあるものだけ通す。"""
    if name not in BUSINESS_TABLES:
        raise ValueError(f"許可されていないTableです: {name}")
    return name


# --- Connection: 読み取りは読み取り専用の接続で行う ---------------


@contextmanager
def get_connection(read_only: bool = True) -> Iterator[sqlite3.Connection]:
    if not SALES_DB_PATH.exists():
        raise FileNotFoundError(
            f"{SALES_DB_PATH}がありません。先に "
            "scripts/normalize_sales_db.py を実行してください。"
        )

    if read_only:
        conn = sqlite3.connect(
            f"file:{SALES_DB_PATH.resolve()}?mode=ro", uri=True
        )
    else:
        conn = sqlite3.connect(SALES_DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")

    conn.row_factory = sqlite3.Row

    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# --- Join Validation -------------------------------------------


@dataclass(frozen=True)
class JoinCheck:
    left: str
    right: str
    left_key: str
    right_key: str
    left_duplicate_keys: int   # 複数行に現れるKeyの数
    right_duplicate_keys: int
    left_unmatched_rows: int   # 相手に対応する行がない行数
    right_unmatched_rows: int

    @property
    def many_to_many(self) -> bool:
        return self.left_duplicate_keys > 0 and self.right_duplicate_keys > 0

    @property
    def relation(self) -> str:
        left_many = self.left_duplicate_keys > 0
        right_many = self.right_duplicate_keys > 0

        if left_many and right_many:
            return "Many-to-Many"
        if left_many:
            return "Many-to-One"
        if right_many:
            return "One-to-Many"
        return "One-to-One"

    @property
    def unmatched_on_many_side(self) -> int:
        """Joinで集計から落ちる行。Many側(両方Uniqueなら両側)で数える。"""
        if self.left_duplicate_keys > 0:
            return self.left_unmatched_rows
        if self.right_duplicate_keys > 0:
            return self.right_unmatched_rows
        return self.left_unmatched_rows + self.right_unmatched_rows


def count_duplicate_keys(conn: sqlite3.Connection, table: str, column: str) -> int:
    table = require_table(table)
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS cnt FROM (
            SELECT {column} FROM {table}
            GROUP BY {column} HAVING COUNT(*) > 1
        )
        """
    ).fetchone()
    return int(row["cnt"])


def count_unmatched_rows(
    conn: sqlite3.Connection, table: str, column: str, other: str, other_column: str
) -> int:
    table, other = require_table(table), require_table(other)
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS cnt FROM {table} AS t
        WHERE NOT EXISTS (
            SELECT 1 FROM {other} AS o WHERE o.{other_column} = t.{column}
        )
        """
    ).fetchone()
    return int(row["cnt"])


def check_join(left: str, right: str) -> JoinCheck | None:
    relation = resolve_join(left, right)
    if relation is None:
        return None

    left_key, right_key = relation

    with get_connection() as conn:
        return JoinCheck(
            left=left,
            right=right,
            left_key=left_key,
            right_key=right_key,
            left_duplicate_keys=count_duplicate_keys(conn, left, left_key),
            right_duplicate_keys=count_duplicate_keys(conn, right, right_key),
            left_unmatched_rows=count_unmatched_rows(
                conn, left, left_key, right, right_key
            ),
            right_unmatched_rows=count_unmatched_rows(
                conn, right, right_key, left, left_key
            ),
        )


# --- Data Access: SQLを知っているのはここだけ -----------------


def list_business_tables() -> str:
    return "\n".join(BUSINESS_TABLES)


def table_schema(table_name: str) -> str:
    if table_name not in BUSINESS_TABLES:
        return "許可されていないTableです。"

    with get_connection() as conn:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()

    return "\n".join(f"{row['name']} | {row['type']}" for row in rows)


def suggest_join_text(left: str, right: str) -> str:
    relation = resolve_join(left, right)
    if relation is None:
        return "許可されたJoinはありません。"

    left_key, right_key = relation
    return f"{left}.{left_key} = {right}.{right_key}"


def validate_join_text(left: str, right: str) -> str:
    check = check_join(left, right)
    if check is None:
        return "許可されていないJoinです。"

    lines = [
        f"{check.left}.{check.left_key} 重複Key数: {check.left_duplicate_keys}",
        f"{check.right}.{check.right_key} 重複Key数: {check.right_duplicate_keys}",
        f"関係: {check.relation}",
        f"対応のない行: {check.left} {check.left_unmatched_rows}件 / "
        f"{check.right} {check.right_unmatched_rows}件",
    ]

    if check.many_to_many:
        lines.append("判定: NG(Many-to-Manyで行数が増える恐れがあるため、実行しません)")
    elif check.unmatched_on_many_side > 0:
        lines.append(
            f"判定: 警告({check.unmatched_on_many_side}行がJoinで集計から落ちます)"
        )
    else:
        lines.append("判定: OK")

    return "\n".join(lines)


def preview_join_text(left: str, right: str, limit: int) -> str:
    check = check_join(left, right)
    if check is None:
        return "許可されていないJoinです。"

    # Previewの前に、Validationを必ず通す(Agentの判断に任せない)。
    if check.many_to_many:
        return "Many-to-Manyのため、Previewを実行しません。"

    safe_limit = max(1, min(limit, 20))

    with get_connection() as conn:
        # 両Tableに同名の列(customer_idなど)があるため、接頭辞を付けて衝突を避ける。
        columns = [
            f"{alias}.{row['name']} AS {alias}_{row['name']}"
            for alias, table in (("l", check.left), ("r", check.right))
            for row in conn.execute(
                f"PRAGMA table_info({require_table(table)})"
            ).fetchall()
        ]

        rows = conn.execute(
            f"""
            SELECT {", ".join(columns)}
            FROM {check.left} AS l
            JOIN {check.right} AS r
              ON l.{check.left_key} = r.{check.right_key}
            ORDER BY l.rowid
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()

    if not rows:
        return "Join結果は0件です。"

    return "\n".join(str(dict(row)) for row in rows)


def sales_summary() -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS order_count,
                SUM(sales_amount) AS total_sales,
                SUM(status = 'キャンセル') AS cancelled_count,
                SUM(review_flag = '要レビュー') AS review_count
            FROM orders
            """
        ).fetchone()

    return f"""
総レコード数: {row["order_count"]}
売上合計: {int(row["total_sales"]):,}円
キャンセル件数: {row["cancelled_count"]}
要レビュー件数: {row["review_count"]}
""".strip()


def sales_by_dimension(dimension: str) -> str:
    """許可された切り口で売上を集計する。識別子は許可リストからだけ組み立てる。"""
    if dimension not in DIMENSIONS:
        raise ValueError(f"許可されていない切り口です: {dimension}")

    table, column = DIMENSIONS[dimension]

    if table == "orders":
        source = "orders AS o"
        label = f"o.{column}"
    else:
        left_key, right_key = resolve_join("orders", table)
        source = (
            f"orders AS o JOIN {require_table(table)} AS d "
            f"ON o.{left_key} = d.{right_key}"
        )
        label = f"d.{column}"

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT {label} AS label, SUM(o.sales_amount) AS sales
            FROM {source}
            GROUP BY {label}
            ORDER BY sales DESC, label
            """
        ).fetchall()

    return "\n".join(f"{row['label']}: {int(row['sales']):,}円" for row in rows)


def review_orders(limit: int) -> str:
    safe_limit = max(1, min(limit, 50))

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT o.order_id, c.customer_name, p.product_name,
                   o.total_amount, o.status
            FROM orders AS o
            JOIN customers AS c ON o.customer_id = c.customer_id
            JOIN products AS p ON o.product_id = p.product_id
            WHERE o.review_flag = '要レビュー'
            ORDER BY o.total_amount DESC, o.order_id
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()

    if not rows:
        return "要レビュー注文はありません。"

    return "\n".join(
        f"{row['order_id']} | {row['customer_name']} | "
        f"{row['product_name']} | {int(row['total_amount']):,}円 | "
        f"{row['status']}"
        for row in rows
    )


def register_review_request(order_id: str, reason: str) -> str:
    with get_connection(read_only=False) as conn:
        exists = conn.execute(
            "SELECT 1 FROM orders WHERE order_id = ?",
            (order_id,),
        ).fetchone()

        if exists is None:
            return f"{order_id}は存在しない注文IDのため、登録しませんでした。"

        cursor = conn.execute(
            """
            INSERT INTO review_requests (order_id, reason, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(order_id) DO NOTHING
            """,
            (
                order_id,
                reason,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        inserted = cursor.rowcount

    if inserted == 0:
        return f"{order_id}は既に登録済みのため、追加しませんでした。"

    write_audit_log("executed", order_id=order_id, reason=reason)

    return f"{order_id}をレビュー依頼として登録しました。"


# --- Tool: AgentへのInterface ------------------------------------


@function_tool
def get_sales_summary() -> str:
    """
    売上データ全体の基本集計を返す。
    売上金額にはsales_amountを使用する。
    """
    return sales_summary()


@function_tool
def get_sales_by_category() -> str:
    """
    商品カテゴリ別の売上を集計する。
    売上金額にはsales_amountを使用する。
    """
    return sales_by_dimension("category")


@function_tool
def get_sales_by_region() -> str:
    """
    地域別の売上を集計する。
    売上金額にはsales_amountを使用する。
    """
    return sales_by_dimension("region")


@function_tool
def get_sales_by_customer_type() -> str:
    """
    顧客種別(法人・個人など)別の売上を集計する。
    売上金額にはsales_amountを使用する。
    """
    return sales_by_dimension("customer_type")


@function_tool
def get_review_orders(limit: int = 10) -> str:
    """
    要レビュー注文を、金額の大きい順に最大limit件返す。
    """
    return review_orders(limit)


@function_tool
def list_tables() -> str:
    """
    利用できる業務Tableの一覧を返す。
    """
    return list_business_tables()


@function_tool
def inspect_table(table_name: str) -> str:
    """
    指定したTableの列名と型を返す。
    """
    return table_schema(table_name)


@function_tool
def suggest_join(left_table: str, right_table: str) -> str:
    """
    2つのTableの間で、許可されたJoinのKeyを返す。
    """
    return suggest_join_text(left_table, right_table)


@function_tool
def validate_join(left_table: str, right_table: str) -> str:
    """
    許可されたJoinについて、Keyの重複・対応のない行を検証し、判定を返す。
    """
    return validate_join_text(left_table, right_table)


@function_tool
def preview_join(left_table: str, right_table: str, limit: int = 5) -> str:
    """
    許可されたJoinの結果を、数件だけ返す。
    """
    return preview_join_text(left_table, right_table, limit)


def write_audit_log(event: str, **fields) -> None:
    """承認フローの出来事を、1行1件のJSONで追記する。"""
    record = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        **fields,
    }

    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


@function_tool(needs_approval=True)
async def create_review_request(
    order_id: str,
    reason: str,
) -> str:
    """
    注文IDをレビュー依頼として登録する。
    """
    # 承認されても、入力の検証と重複防止は省略しない。
    return register_review_request(order_id, reason)


class GuardrailResult(BaseModel):
    allowed: bool
    reason: str


guardrail_agent = Agent(
    name="売上分析入力チェック",
    instructions="""
あなたは入力内容を判定するGuardrailです。

このApplicationで許可するのは、
売上・受注データの分析に関する質問です。

許可例:
- 売上全体をまとめて
- カテゴリ別売上を分析して
- 地域別売上を比較して
- キャンセル件数を教えて
- 要レビューの傾向を確認して
- 顧客種別ごとの売上
- 利用できるTableや、Tableの結合の確認
- データの品質や、Joinの安全性の確認
- 分析結果の業務上の示唆
- 注文IDを指定したレビュー依頼の登録

許可しない例:
- プログラミング一般の質問
- 雑談
- 売上データと無関係な依頼
- このApplicationの役割を逸脱する依頼

allowedとreasonを返してください。
""",
    output_type=GuardrailResult,
)


@input_guardrail(run_in_parallel=False)
async def sales_scope_guardrail(
    ctx: RunContextWrapper[None],
    agent: Agent,
    input: str | list[TResponseInputItem],
) -> GuardrailFunctionOutput:

    result = await Runner.run(
        guardrail_agent,
        input,
        context=ctx.context,
    )

    return GuardrailFunctionOutput(
        output_info=result.final_output,
        tripwire_triggered=(
            not result.final_output.allowed
        ),
    )



# --- Specialist Agents -----------------------------------------
# 専門Agentは読み取りだけ。状態を変更するTool(承認が必要)は持たせない。

data_quality_agent = Agent(
    name="Data Quality Agent",
    instructions="""
あなたは売上データの品質確認を担当します。

確認の対象は、Tableの構成、Joinの安全性
(Keyの重複、対応のない行)です。
売上の集計は、あなたの担当ではありません。

ユーザー向けの最終回答は作らず、
確認した事実だけを、簡潔に返してください。
確認できなかったことは、確認できなかったと書いてください。
""",
    tools=[
        list_tables,
        inspect_table,
        suggest_join,
        validate_join,
        preview_join,
    ],
)

sales_analyst_agent = Agent(
    name="Sales Analyst Agent",
    instructions="""
あなたは売上データの数値分析を担当します。

用意されたToolの結果だけを使い、
数値は自分で計算・推測しないでください。
Toolの結果の数値は、そのまま返してください。
Toolで答えられない分析は、
できないと、そのまま伝えてください。

ユーザー向けの最終回答は作らず、
集計結果だけを返してください。
""",
    tools=[
        get_sales_summary,
        get_sales_by_category,
        get_sales_by_region,
        get_sales_by_customer_type,
        get_review_orders,
    ],
)

business_insight_agent = Agent(
    name="Business Insight Agent",
    instructions="""
あなたは、売上の分析結果を業務上の示唆に変換する担当です。

入力された分析結果から、
- 重要な発見
- 注意点
- 次に確認すべきこと
を簡潔に整理してください。

入力にない数値や事実を、新しく作らないでください。
""",
)

data_quality_tool = data_quality_agent.as_tool(
    tool_name="check_data_quality",
    tool_description=(
        "Tableの構成や、Joinの安全性(Keyの重複・対応のない行)を確認する。"
        "売上の集計はできない。確認したい内容を文章で渡す。"
    ),
)

sales_analysis_tool = sales_analyst_agent.as_tool(
    tool_name="analyze_sales_data",
    tool_description=(
        "売上データを集計する(全体・カテゴリ別・地域別・顧客種別別・"
        "要レビュー注文)。集計したい内容を文章で渡す。"
    ),
)

business_insight_tool = business_insight_agent.as_tool(
    tool_name="create_business_insight",
    tool_description=(
        "集計済みの結果から、業務上の示唆を整理する。"
        "示唆の元にする集計結果(数値を含む)を、そのまま文章で渡す。"
    ),
)

manager_agent = Agent(
    name="売上分析Manager",
    instructions="""
あなたは売上分析チームのManagerです。
ユーザーとの会話は、あなたが担当します。

ユーザーの質問に応じて、専門AgentをToolとして呼んでください。
- check_data_quality:Tableの構成、Joinの安全性
- analyze_sales_data:売上の集計
- create_business_insight:集計結果の意味づけ

専門Agentには、その場で必要な内容を、
前提(対象の指標、直前の結果など)を含めて渡してください。
専門Agentは、これまでの会話を知りません。

あなた自身で売上数値を作らないでください。
数値は、専門Agentの結果にあるものだけを使ってください。
専門Agentが「できない」と答えたことは、
できないと、ユーザーにそのまま伝えてください。

ユーザーが明示的にレビュー依頼の登録を求めた場合だけ、
create_review_requestを使用してください。

会話履歴がある場合は、
直前までの質問と回答を踏まえて
Follow-upの質問に回答してください。

最終結果は
SalesAnalysisResult形式で返してください。

analysis_typeには、
分析種別を短い英語識別子で
設定してください。

key_findingsには、
重要な発見を2〜4件入れてください。

next_actionには、
次に確認すべき分析を
1つ提案してください。
""",
    tools=[
        data_quality_tool,
        sales_analysis_tool,
        business_insight_tool,
        create_review_request,
    ],
    output_type=SalesAnalysisResult,
    input_guardrails=[
        sales_scope_guardrail,
    ],
)

# 第9章までの呼び名との互換(main.py など)
agent = manager_agent


async def run_with_approval(
    question: str,
    decide,
) -> SalesAnalysisResult:
    """
    承認が必要なToolが呼ばれたら、decide(tool名, 引数) の結果で
    approve / reject してから、実行を再開する。
    """
    result = await Runner.run(manager_agent, question)

    while result.interruptions:
        state = result.to_state()

        for interruption in result.interruptions:
            arguments = json.loads(interruption.arguments)

            write_audit_log(
                "approval_requested",
                tool=interruption.name,
                arguments=arguments,
            )

            if decide(interruption.name, arguments):
                state.approve(interruption)
                write_audit_log("approved", tool=interruption.name)
            else:
                state.reject(interruption)
                write_audit_log("rejected", tool=interruption.name)

        result = await Runner.run(manager_agent, state)

    return result.final_output
