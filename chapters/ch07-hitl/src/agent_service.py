import csv
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
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

CSV_PATH = Path(
    "data/raw/ai_agent_practice_sales.csv"
)

SESSION_DB_PATH = Path(
    "data/conversations.db"
)

REVIEW_REQUESTS_PATH = Path(
    "data/review_requests.csv"
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


def load_sales_data() -> pd.DataFrame:
    return pd.read_csv(CSV_PATH)


@function_tool
def get_sales_summary() -> str:
    """
    売上データ全体の基本集計を返す。
    売上金額にはsales_amountを使用する。
    """
    df = load_sales_data()

    total_sales = int(
        df["sales_amount"].sum()
    )

    order_count = len(df)

    cancelled_count = int(
        (df["status"] == "キャンセル").sum()
    )

    review_count = int(
        (
            df["review_flag"]
            == "要レビュー"
        ).sum()
    )

    return f"""
総レコード数: {order_count}
売上合計: {total_sales:,}円
キャンセル件数: {cancelled_count}
要レビュー件数: {review_count}
""".strip()


@function_tool
def get_sales_by_category() -> str:
    """
    商品カテゴリ別の売上を集計する。
    売上金額にはsales_amountを使用する。
    """
    df = load_sales_data()

    result = (
        df.groupby(
            "category",
            as_index=False,
        )["sales_amount"]
        .sum()
        .sort_values(
            "sales_amount",
            ascending=False,
        )
    )

    return "\n".join(
        f"{row.category}: "
        f"{int(row.sales_amount):,}円"
        for row in result.itertuples()
    )


@function_tool
def get_sales_by_region() -> str:
    """
    地域別の売上を集計する。
    売上金額にはsales_amountを使用する。
    """
    df = load_sales_data()

    result = (
        df.groupby(
            "region",
            as_index=False,
        )["sales_amount"]
        .sum()
        .sort_values(
            "sales_amount",
            ascending=False,
        )
    )

    return "\n".join(
        f"{row.region}: "
        f"{int(row.sales_amount):,}円"
        for row in result.itertuples()
    )



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

    # 承認されても、入力の検証は省略しない。
    order_ids = set(load_sales_data()["order_id"])

    if order_id not in order_ids:
        return f"{order_id}は存在しない注文IDのため、登録しませんでした。"

    file_exists = REVIEW_REQUESTS_PATH.exists()

    # 同じ注文を二重に登録しない（再実行しても結果が変わらない）。
    if file_exists:
        with REVIEW_REQUESTS_PATH.open(
            encoding="utf-8-sig", newline=""
        ) as f:
            registered = {row["order_id"] for row in csv.DictReader(f)}

        if order_id in registered:
            return f"{order_id}は既に登録済みのため、追加しませんでした。"

    with REVIEW_REQUESTS_PATH.open(
        "a", newline="", encoding="utf-8-sig"
    ) as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow(["created_at", "order_id", "reason"])

        writer.writerow(
            [
                datetime.now().isoformat(timespec="seconds"),
                order_id,
                reason,
            ]
        )

    write_audit_log("executed", order_id=order_id, reason=reason)

    return f"{order_id}をレビュー依頼として登録しました。"


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
