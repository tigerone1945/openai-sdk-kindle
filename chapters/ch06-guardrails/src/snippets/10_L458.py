try:
    result = run_sales_agent(
        question=question,
        session_id=(
            st.session_state.session_id
        ),
    )

except InputGuardrailTripwireTriggered:
    st.warning(
        "このAIエージェントは、"
        "売上・受注データの分析に関する"
        "質問だけを扱います。"
    )
