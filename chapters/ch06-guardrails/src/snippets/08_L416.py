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
