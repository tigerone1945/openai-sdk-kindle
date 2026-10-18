"""Streamlit画面:Agentを知らず、HTTP APIだけと話す。"""
import os
from uuid import uuid4

import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
# サーバー側の上限(120秒)より少し長くして、サーバーのエラーを先に受け取る。
CLIENT_TIMEOUT_SECONDS = 130.0


class ApiCallError(Exception):
    """APIが返したエラー、または通信の失敗。画面に出してよい文だけを持つ。"""


def call_api(path: str, payload: dict) -> dict:
    try:
        response = httpx.post(
            f"{API_URL}{path}", json=payload, timeout=CLIENT_TIMEOUT_SECONDS
        )
    except httpx.TimeoutException as e:
        raise ApiCallError("応答がありませんでした。時間をおいて再試行してください。") from e
    except httpx.HTTPError as e:
        raise ApiCallError("APIに接続できませんでした。") from e

    if response.is_success:
        return response.json()

    try:
        error = response.json()["error"]
        raise ApiCallError(f"{error['message']}(ID: {error['request_id'][:8]})")
    except (ValueError, KeyError):
        raise ApiCallError(f"予期しない応答です(HTTP {response.status_code})。")


def render_result(result: dict) -> str:
    return (
        f"### 分析概要\n{result['result_summary']}\n\n"
        "### 重要な発見\n"
        + "\n".join(f"- {item}" for item in result["key_findings"])
        + f"\n\n### 次のアクション\n{result['next_action']}"
    )


def start_new_conversation() -> None:
    st.session_state.session_id = f"sales_{uuid4().hex}"
    st.session_state.messages = []
    st.session_state.approval = None


st.set_page_config(page_title="AI売上分析アシスタント", page_icon="📊")
st.title("AI売上分析アシスタント")
st.caption("Streamlit → HTTP → FastAPI → Manager Agent")

if "session_id" not in st.session_state:
    start_new_conversation()

with st.sidebar:
    st.subheader("Conversation")
    st.code(st.session_state.session_id)
    if st.button("新しい会話を開始"):
        start_new_conversation()
        st.rerun()


def handle_response(data: dict) -> None:
    """APIの応答を、画面の状態に反映する。"""
    if data["status"] == "completed":
        st.session_state.approval = None
        st.session_state.messages.append(
            {"role": "assistant", "content": render_result(data["result"])}
        )
    else:
        st.session_state.approval = data["approval"]


for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 承認待ち:人が内容を見て、承認か却下を選ぶ。
approval = st.session_state.approval
if approval:
    with st.chat_message("assistant"):
        st.warning("次の操作は、承認が必要です。")
        for item in approval["items"]:
            st.write(f"**{item['tool']}**")
            st.json(item["arguments"])

        approve_col, reject_col = st.columns(2)
        decision = None
        if approve_col.button("承認する", type="primary"):
            decision = "approve"
        if reject_col.button("却下する"):
            decision = "reject"

        if decision:
            try:
                with st.spinner("実行しています..."):
                    data = call_api(
                        f"/approvals/{approval['approval_id']}", {"decision": decision}
                    )
            except ApiCallError as e:
                st.session_state.approval = None
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"エラー: {e}"}
                )
            else:
                handle_response(data)
            st.rerun()

question = st.chat_input("売上データについて質問してください")

if question and not approval:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    try:
        with st.spinner("AIエージェントが分析しています..."):
            data = call_api(
                "/analysis",
                {"question": question, "session_id": st.session_state.session_id},
            )
    except ApiCallError as e:
        st.session_state.messages.append({"role": "assistant", "content": f"エラー: {e}"})
    else:
        handle_response(data)
    st.rerun()
