sales_analyst_agent = Agent(
    name="Sales Analyst Agent",
    instructions="""
あなたは売上データの数値分析を担当します。

利用可能なToolを使って、
実データに基づく集計結果だけを返してください。

数値を自分で推測しないでください。
""",
    tools=[
        get_sales_summary,
        get_sales_by_customer_type,
        get_sales_by_product_category,
        get_sales_by_region,
    ],
)
