import json
import sqlite3
from datetime import datetime
from pathlib import Path

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

SESSION_DB_PATH = Path(
    "data/conversations.db"
)

AUDIT_LOG_PATH = Path(
    "data/audit_log.jsonl"
)


class SalesAnalysisResult(BaseModel):
    question: str
    analysis_type: str
    result_summary: str
    key_findings: list[str]
    next_action: str


def get_connection() -> sqlite3.Connection:
    if not SALES_DB_PATH.exists():
        raise FileNotFoundError(
            f"{SALES_DB_PATH}がありません。先に "
            "scripts/import_csv_to_sqlite.py を実行してください。"
        )

    conn = sqlite3.connect(SALES_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# --- Data Access: SQLを知っているのはここだけ -----------------


def sales_summary() -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS order_count,
                SUM(sales_amount) AS total_sales,
                SUM(status = 'キャンセル') AS cancelled_count,
                SUM(review_flag = '要レビュー') AS review_count
            FROM sales
            """
        ).fetchone()

    return f"""
総レコード数: {row["order_count"]}
売上合計: {int(row["total_sales"]):,}円
キャンセル件数: {row["cancelled_count"]}
要レビュー件数: {row["review_count"]}
""".strip()


def sales_by_category() -> str:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT category, SUM(sales_amount) AS sales
            FROM sales
            GROUP BY category
            ORDER BY sales DESC
            """
        ).fetchall()

    return "\n".join(
        f"{row['category']}: {int(row['sales']):,}円"
        for row in rows
    )


def sales_by_region() -> str:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT region, SUM(sales_amount) AS sales
            FROM sales
            GROUP BY region
            ORDER BY sales DESC
            """
        ).fetchall()

    return "\n".join(
        f"{row['region']}: {int(row['sales']):,}円"
        for row in rows
    )


def review_orders(limit: int) -> str:
    # 値はSQL文字列に埋め込まず、パラメータとして渡す。
    safe_limit = max(1, min(limit, 50))

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT order_id, customer_name, product_name,
                   total_amount, status
            FROM sales
            WHERE review_flag = '要レビュー'
            ORDER BY total_amount DESC, order_id
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
    """検証と重複防止を、DBの制約に任せて1文で行う。"""
    with get_connection() as conn:
        # 存在しない注文IDは、外部キー制約ではなく先に確認して、
        # 理由が分かるメッセージを返す。
        exists = conn.execute(
            "SELECT 1 FROM sales WHERE order_id = ?",
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

    if cursor.rowcount == 0:
        return f"{order_id}は既に登録済みのため、追加しませんでした。"

    write_audit_log("executed", order_id=order_id, reason=reason)

    return f"{order_id}をレビュー依頼として登録しました。"


# --- Tool: AgentへのInterface(第7章までと同じ名前・同じ説明) ---


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
    return sales_by_category()


@function_tool
def get_sales_by_region() -> str:
    """
    地域別の売上を集計する。
    売上金額にはsales_amountを使用する。
    """
    return sales_by_region()


@function_tool
def get_review_orders(limit: int = 10) -> str:
    """
    要レビュー注文を、金額の大きい順に最大limit件返す。
    """
    return review_orders(limit)


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


agent = Agent(
    name="売上分析アシスタント",
    instructions="""
あなたは売上データ分析を支援する
AIアシスタントです。

ユーザーの質問に応じて、
必要なFunction Toolを選んでください。

売上集計は自分で計算せず、
必ずToolの結果を使用してください。

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
        get_sales_summary,
        get_sales_by_category,
        get_sales_by_region,
        get_review_orders,
        create_review_request,
    ],
    output_type=SalesAnalysisResult,
    input_guardrails=[
        sales_scope_guardrail,
    ],
)


async def run_with_approval(
    question: str,
    decide,
) -> SalesAnalysisResult:
    """
    承認が必要なToolが呼ばれたら、decide(tool名, 引数) の結果で
    approve / reject してから、実行を再開する。
    """
    result = await Runner.run(agent, question)

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

        result = await Runner.run(agent, state)

    return result.final_output
