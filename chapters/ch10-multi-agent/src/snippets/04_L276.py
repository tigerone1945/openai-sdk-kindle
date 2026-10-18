data_quality_tool = (
    data_quality_agent.as_tool(
        tool_name="check_data_quality",
        tool_description=(
            "売上データの品質や"
            "Join整合性を確認する"
        ),
    )
)
