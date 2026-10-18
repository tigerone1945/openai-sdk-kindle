from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel

from agents import (
    Agent,
    Runner,
    SQLiteSession,
    function_tool,
    trace,
)


load_dotenv()

CSV_PATH = Path(
    "data/raw/ai_agent_practice_sales.csv"
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


agent = Agent(
    name="売上分析アシスタント",
    instructions="""
あなたは売上データ分析を支援する
AIアシスタントです。

ユーザーの質問に応じて、
必要なFunction Toolを選んでください。

売上集計は自分で計算せず、
必ずToolの結果を使用してください。

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
    ],
    output_type=SalesAnalysisResult,
)


def run_sales_agent(
    question: str,
    session_id: str,
) -> SalesAnalysisResult:

    session = SQLiteSession(
        session_id,
        str(SESSION_DB_PATH),
    )

    with trace(
        workflow_name="sales_analysis_chat",
        group_id=session_id,
    ):
        result = Runner.run_sync(
            agent,
            question,
            session=session,
        )

    return result.final_output
