from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel
from agents import Agent, Runner, function_tool

load_dotenv()

CSV_PATH = Path("data/raw/ai_agent_practice_sales.csv")


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

    total_sales = int(df["sales_amount"].sum())
    order_count = len(df)
    cancelled_count = int(
        (df["status"] == "キャンセル").sum()
    )
    review_count = int(
        (df["review_flag"] == "要レビュー").sum()
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

    lines = [
        f"{row.category}: {int(row.sales_amount):,}円"
        for row in result.itertuples()
    ]

    return "\n".join(lines)


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

    lines = [
        f"{row.region}: {int(row.sales_amount):,}円"
        for row in result.itertuples()
    ]

    return "\n".join(lines)


agent = Agent(
    name="売上分析アシスタント",
    instructions="""
あなたは売上データ分析を支援するAIアシスタントです。

ユーザーの質問に応じて、
必要なFunction Toolを利用してください。

売上集計は自分で計算せず、
必ずToolの結果を使用してください。

最終結果はSalesAnalysisResultの形式で返してください。

analysis_typeには、
今回行った分析種別を短い英語識別子で設定してください。

key_findingsには、
重要な発見を2〜4件入れてください。

next_actionには、
次に確認すべき分析を1つ提案してください。
""",
    tools=[
        get_sales_summary,
        get_sales_by_category,
        get_sales_by_region,
    ],
    output_type=SalesAnalysisResult,
)

question = "カテゴリ別の売上を分析してください。"

result = Runner.run_sync(
    agent,
    question,
)

output = result.final_output

print(output)
print(output.model_dump())
