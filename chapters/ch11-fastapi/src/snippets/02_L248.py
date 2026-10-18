async def run_sales_agent_async(
    question: str,
    session_id: str,
) -> SalesAnalysisResult:

    session = SQLiteSession(
        session_id,
        str(SESSION_DB_PATH),
    )

    with trace(
        workflow_name="sales_analysis_api",
        group_id=session_id,
    ):
        result = await Runner.run(
            manager_agent,
            question,
            session=session,
        )

    return result.final_output
