sales_analysis_tool = (
    sales_analyst_agent.as_tool(
        tool_name="analyze_sales_data",
        tool_description=(
            "SQLiteの売上データを"
            "集計・分析する"
        ),
    )
)
