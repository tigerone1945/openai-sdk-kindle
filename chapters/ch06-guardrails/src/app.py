from uuid import uuid4

import streamlit as st
from agents import InputGuardrailTripwireTriggered

from agent_service import run_sales_agent


st.set_page_config(
    page_title="AI売上分析アシスタント",
    page_icon="📊",
)

st.title("AI売上分析アシスタント")
st.caption(
    "OpenAI Agents SDK "
    "+ Sessions + Tracing + Guardrails"
)


if "session_id" not in st.session_state:
    st.session_state.session_id = (
        f"sales_{uuid4().hex}"
    )


if "messages" not in st.session_state:
    st.session_state.messages = []


with st.sidebar:
    st.subheader("Conversation")

    st.code(
        st.session_state.session_id
    )

    if st.button(
        "新しい会話を開始"
    ):
        st.session_state.session_id = (
            f"sales_{uuid4().hex}"
        )
        st.session_state.messages = []
        st.rerun()


st.write("質問例:")

st.markdown(
    """
- 地域別の売上を分析してください
- カテゴリ別の売上を分析してください
- 売上全体をまとめてください
"""
)


for message in st.session_state.messages:
    with st.chat_message(
        message["role"]
    ):
        st.markdown(
            message["content"]
        )


question = st.chat_input(
    "売上データについて質問してください"
)


if question:

    st.session_state.messages.append(
        {
            "role": "user",
            "content": question,
        }
    )

    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):

        with st.spinner(
            "AIエージェントが"
            "分析しています..."
        ):
            try:
                result = run_sales_agent(
                    question=question,
                    session_id=(
                        st.session_state
                        .session_id
                    ),
                )

            except InputGuardrailTripwireTriggered:
                guardrail_message = (
                    "このAIエージェントは、"
                    "売上・受注データの分析に関する"
                    "質問だけを扱います。"
                )

                st.warning(guardrail_message)

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": guardrail_message,
                    }
                )

            except Exception as e:
                st.error(
                    "分析中にエラーが"
                    "発生しました。"
                )
                st.exception(e)

            else:
                response = (
                    f"### 分析概要\n"
                    f"{result.result_summary}\n\n"
                    f"### 重要な発見\n"
                    + "\n".join(
                        f"- {item}"
                        for item
                        in result.key_findings
                    )
                    + "\n\n"
                    f"### 次のアクション\n"
                    f"{result.next_action}"
                )

                st.markdown(response)

                with st.expander(
                    "Structured Output"
                ):
                    st.json(
                        result.model_dump()
                    )

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": response,
                    }
                )
