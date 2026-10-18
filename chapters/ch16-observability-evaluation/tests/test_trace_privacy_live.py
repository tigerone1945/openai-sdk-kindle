"""OpenAI を実際に呼んで、質問・Tool の入出力が、どこに残るかを確かめる(数円)。

RUN_LIVE_TESTS=1 と本物の OPENAI_API_KEY があるときだけ実行する。
各検査には「対照(positive control)」がある: 設定を外すと中身が見える、を同じ方法で確かめる。
対照が見えなければ、検査自体が壊れている。
"""
import asyncio
import json
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1" or os.environ.get("OPENAI_API_KEY", "").startswith("sk-test"),
    reason="RUN_LIVE_TESTS=1 と本物の OPENAI_API_KEY が必要(OpenAI を呼ぶ)",
)

MARKER = "KOKYAKU-7731"
QUESTION = f"顧客コード {MARKER} の注文について、2 と 3 を足した数だけ答えてください"


def run_with_trace(include_sensitive: str):
    """Tool を使う実行を 1 回。トレースは OpenAI へ送らず、手元で集めて返す。"""
    from agents import Agent, Runner, function_tool, set_default_openai_client, set_trace_processors, set_tracing_disabled
    from agents.tracing import TracingProcessor
    from openai import AsyncOpenAI

    os.environ["OPENAI_AGENTS_TRACE_INCLUDE_SENSITIVE_DATA"] = include_sensitive
    spans: list[dict] = []

    class Capture(TracingProcessor):
        def on_trace_start(self, trace): pass
        def on_trace_end(self, trace): pass
        def on_span_start(self, span): pass
        def on_span_end(self, span): spans.append(span.export())
        def shutdown(self): pass
        def force_flush(self): pass

    @function_tool
    def add(a: int, b: int) -> int:
        """2 つの整数を足す。"""
        return a + b

    set_tracing_disabled(False)
    set_default_openai_client(AsyncOpenAI(), use_for_tracing=False)  # テストごとに新しい接続
    set_trace_processors([Capture()])
    agent = Agent(name="calc", instructions="必ず add ツールで計算して、数字だけ答える。", tools=[add])
    asyncio.run(Runner.run(agent, QUESTION))
    return [s["span_data"] for s in spans]


def test_trace_flag_removes_tool_arguments_and_results_from_traces():
    hidden = [s for s in run_with_trace("false") if s["type"] == "function"]
    assert hidden and all(not s.get("input") and not s.get("output") for s in hidden)


def test_positive_control_sdk_default_puts_tool_arguments_and_results_in_traces():
    shown = [s for s in run_with_trace("true") if s["type"] == "function"]
    assert shown and any(s.get("input") for s in shown) and any(s.get("output") for s in shown)


def retrievable(agent) -> bool:
    """その Agent の実行で返ったレスポンスを、ID で取り出せるか(OpenAI 側に保存されているか)。"""
    from agents import Runner, set_default_openai_client
    from openai import AsyncOpenAI, NotFoundError

    async def go():
        client = AsyncOpenAI()
        set_default_openai_client(client, use_for_tracing=False)
        result = await Runner.run(agent, QUESTION)
        response_id = result.raw_responses[-1].response_id
        try:
            await client.responses.retrieve(response_id)
            items = await client.responses.input_items.list(response_id)  # 質問(入力)は、こちらにある
            return MARKER in json.dumps([i.model_dump() for i in items.data], ensure_ascii=False)
        except NotFoundError:
            return False

    os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"
    return asyncio.run(go())


def test_positive_control_responses_are_stored_and_retrievable_by_default():
    from agents import Agent
    assert retrievable(Agent(name="a", instructions="復唱する")) is True


def test_application_agents_do_not_store_the_question_at_openai():
    from conftest import M
    for name in ("guardrail_agent", "manager_agent"):
        assert retrievable(getattr(M.agent_service, name).clone(tools=[], handoffs=[], input_guardrails=[], output_type=None)) is False, name
