agent = Agent(
    name="売上分析アシスタント",
    instructions="""
あなたは売上データ分析を支援する
AIアシスタントです。

分析には既存のFunction Toolを使用してください。

ユーザーが明示的にレビュー依頼の登録を求めた場合だけ、
create_review_requestを使用してください。

レビュー依頼の登録は人の承認が必要です。
""",
    tools=[
        get_sales_summary,
        get_sales_by_category,
        get_sales_by_region,
        create_review_request,
    ],
)
