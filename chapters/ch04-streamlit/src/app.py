import streamlit as st

from agent_service import run_sales_agent


st.set_page_config(
    page_title="AI売上分析アシスタント",
    page_icon="📊",
)

st.title("AI売上分析アシスタント")
st.caption("OpenAI Agents SDK + pandas + Streamlit")

st.write("質問例:")

st.markdown(
    """
- 売上全体をまとめてください
- カテゴリ別の売上を分析してください
- 地域別の売上を比較してください
"""
)

with st.form("analysis_form"):
    question = st.text_area(
        "分析したい内容を入力してください",
        value="カテゴリ別の売上を分析してください。",
        height=100,
    )

    submitted = st.form_submit_button(
        "分析する"
    )


if submitted:
    if not question.strip():
        st.warning(
            "分析したい内容を入力してください。"
        )
    else:
        with st.spinner(
            "AIエージェントが分析しています..."
        ):
            try:
                result = run_sales_agent(
                    question=question.strip(),
                )

            except Exception as e:
                st.error(
                    "分析中にエラーが発生しました。"
                )
                st.exception(e)

            else:
                st.success(
                    "分析が完了しました。"
                )

                st.subheader("分析概要")
                st.write(
                    result.result_summary
                )

                st.subheader("重要な発見")
                for finding in result.key_findings:
                    st.markdown(
                        f"- {finding}"
                    )

                st.subheader("次のアクション")
                st.info(
                    result.next_action
                )

                with st.expander(
                    "Structured Outputを確認"
                ):
                    st.json(
                        result.model_dump()
                    )
