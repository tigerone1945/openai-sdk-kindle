business_insight_tool = (
    business_insight_agent.as_tool(
        tool_name="create_business_insight",
        tool_description=(
            "分析結果から"
            "業務上の示唆を整理する"
        ),
    )
)
