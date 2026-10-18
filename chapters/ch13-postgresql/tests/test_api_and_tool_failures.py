"""DBが障害のとき、Toolと、APIがどう振る舞うか(LLMなし・DBなし)。"""
import asyncio
import json
import time

import pytest
from agents.tool_context import ToolContext
from fastapi.testclient import TestClient

from conftest import M

svc, api_main, service = M.agent_service, M.api_main, M.service
StorageUnavailableError = M.repository.StorageUnavailableError
SalesSummary = M.repository.SalesSummary


class Repo:
    """ping と sales_summary だけ持つ、障害を再現できる偽のRepository。"""

    def __init__(self, error=None, delay=0.0):
        self.error, self.delay = error, delay

    def ping(self):
        if self.error:
            raise self.error

    def sales_summary(self):
        if self.delay:
            time.sleep(self.delay)  # 同期の待ち(ネットワーク越しのDBの遅さに相当)
        if self.error:
            raise self.error
        return SalesSummary(300, 28_298_695, 14, 37)

    def sales_by_dimension(self, dimension):
        raise ValueError(f"許可されていない切り口です: {dimension}")


@pytest.fixture(autouse=True)
def reset():
    yield
    svc.set_repository(None)


@pytest.fixture
def client():
    return TestClient(api_main.app, raise_server_exceptions=False)


# --- API:/health(生きているか)と /ready(受けられるか) ------------------


def test_health_does_not_touch_the_database(client):
    svc.set_repository(Repo(error=StorageUnavailableError("down")))
    assert client.get("/health").status_code == 200  # DBが落ちても、プロセスは生きている


def test_ready_is_ok_when_the_database_answers(client):
    svc.set_repository(Repo())
    assert client.get("/ready").json() == {"status": "ready"}


def test_ready_is_503_when_the_database_is_down(client):
    svc.set_repository(Repo(error=StorageUnavailableError("down")))
    r = client.get("/ready")
    assert r.status_code == 503 and r.json()["error"]["code"] == "database_unavailable"


def test_openapi_documents_ready_and_database_errors(client):
    schema = client.get("/openapi.json").json()
    assert "/ready" in schema["paths"]
    assert "503" in schema["paths"]["/analysis"]["post"]["responses"]


def test_database_failure_during_analysis_is_503_without_leaking(client, monkeypatch):
    async def fail(question, session_id):
        raise StorageUnavailableError("connection to server at 'db' failed: password=hunter2")

    monkeypatch.setattr(service, "run_analysis", fail)
    r = client.post("/analysis", json={"question": "売上", "session_id": "s1"})

    assert r.status_code == 503 and r.json()["error"]["code"] == "database_unavailable"
    assert "hunter2" not in r.text and "server at" not in r.text
    assert r.json()["error"]["request_id"] == r.headers["X-Request-ID"]


# --- Tool:インフラの障害は上へ通し、入力の誤りはモデルへ返す --------------


def tool_context(tool, arguments: dict | None = None) -> ToolContext:
    return ToolContext(context=None, tool_name=tool.name, tool_call_id="call-1", tool_arguments=json.dumps(arguments or {}))


def invoke(tool, arguments: dict | None = None):
    return asyncio.run(tool.on_invoke_tool(tool_context(tool, arguments), json.dumps(arguments or {})))


class AlwaysDown:
    """どのメソッドを呼んでも、保存先の障害になるRepository。"""

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise StorageUnavailableError("down")

        return fail


def test_infrastructure_failure_is_raised_not_turned_into_an_answer():
    """DBの障害がエラー文としてモデルに渡ると、Agentは「失敗した」という普通の回答を作り、APIは200を返してしまう。"""
    svc.set_repository(Repo(error=StorageUnavailableError("down")))
    with pytest.raises(StorageUnavailableError):
        invoke(svc.get_sales_summary)


def test_input_errors_are_still_returned_to_the_model():
    """存在しない切り口などは、モデルが自分で直せる。エラー文として返す(例外にしない)。"""
    svc.set_repository(Repo())
    result = invoke(svc.get_sales_by_category)
    assert isinstance(result, str) and "切り口" in result


DATA_TOOL_CALLS = [
    ("get_sales_summary", {}), ("get_sales_by_category", {}), ("get_sales_by_region", {}),
    ("get_sales_by_customer_type", {}), ("get_review_orders", {"limit": 3}),
    ("validate_join", {"left_table": "orders", "right_table": "customers"}),
    ("preview_join", {"left_table": "orders", "right_table": "customers", "limit": 2}),
    ("inspect_table", {"table_name": "orders"}),
]


@pytest.mark.parametrize("name,arguments", DATA_TOOL_CALLS, ids=[c[0] for c in DATA_TOOL_CALLS])
def test_every_data_tool_raises_when_storage_is_down(name, arguments):
    """どのTool経由でも、DBの障害は、回答に化けず、例外として上がる(振る舞いで確認する)。"""
    svc.set_repository(AlwaysDown())
    with pytest.raises(StorageUnavailableError):
        invoke(getattr(svc, name), arguments)


def test_approval_tool_raises_when_storage_is_down():
    svc.set_repository(AlwaysDown())
    with pytest.raises(StorageUnavailableError):
        asyncio.run(
            svc.create_review_request.on_invoke_tool(
                tool_context(svc.create_review_request, {"order_id": "O0001", "reason": "x"}),
                json.dumps({"order_id": "O0001", "reason": "x"}),
            )
        )


def test_specialist_agent_tools_use_the_failure_handler():
    """専門AgentのToolは、LLMなしでは動かせないので、設定を確認する。
    注意: `_failure_error_function` はSDKの内部属性。SDKの更新で名前が変わったら、このテストを見直す。"""
    agent_tools = [t for t in svc.manager_agent.tools if t.name != "create_review_request"]
    assert len(agent_tools) == 3
    for tool in agent_tools:
        assert tool._failure_error_function is svc.tool_error_handler, tool.name


# --- 同期のDB呼び出しが、イベントループを止めない --------------------------


def test_slow_synchronous_repository_does_not_block_the_event_loop():
    """SDKは、同期のToolを別スレッドで動かす。DBが遅くても、他のリクエスト(/health など)が待たされない。"""
    svc.set_repository(Repo(delay=0.6))

    async def scenario():
        ticks = []

        async def heartbeat():
            while True:
                ticks.append(time.perf_counter())
                await asyncio.sleep(0.02)

        beat = asyncio.create_task(heartbeat())
        started = time.perf_counter()
        ctx = tool_context(svc.get_sales_summary)
        await asyncio.gather(*[svc.get_sales_summary.on_invoke_tool(ctx, "{}") for _ in range(3)])
        elapsed = time.perf_counter() - started
        beat.cancel()
        gaps = [b - a for a, b in zip(ticks, ticks[1:])]
        return elapsed, max(gaps)

    elapsed, longest_gap = asyncio.run(scenario())
    assert elapsed < 1.2        # 3件が並行で動く(直列なら1.8秒)
    assert longest_gap < 0.25   # イベントループは、止まらなかった


# --- SDKが包んだ例外でも、原因をたどって判定する ------------------------------

is_storage_unavailable = M.repository.is_storage_unavailable


def wrapped(cause: Exception, depth: int = 1) -> Exception:
    """SDKがToolの例外を UserError に包む様子を再現する(専門Agentの入れ子なら、二重に包まれる)。"""
    from agents.exceptions import UserError

    error = cause
    for _ in range(depth):
        outer = UserError(f"Error running tool: {error}")
        outer.__cause__ = error
        error = outer
    return error


@pytest.mark.parametrize("depth", [0, 1, 2])
def test_storage_failure_is_recognized_through_wrapping(depth):
    assert is_storage_unavailable(wrapped(StorageUnavailableError("down"), depth) if depth else StorageUnavailableError("down"))


def test_unrelated_errors_are_not_mistaken_for_storage_failures():
    assert not is_storage_unavailable(ValueError("x"))
    assert not is_storage_unavailable(wrapped(ValueError("x"), 2))
    assert not is_storage_unavailable(None)


def test_cyclic_cause_chain_does_not_loop_forever():
    a, b = ValueError("a"), ValueError("b")
    a.__cause__, b.__cause__ = b, a
    assert not is_storage_unavailable(a)


@pytest.mark.parametrize("depth", [1, 2])
def test_handler_reraises_wrapped_storage_failure_but_not_wrapped_input_errors(depth):
    ctx = tool_context(svc.get_sales_summary)
    with pytest.raises(Exception) as raised:
        svc.tool_error_handler(ctx, wrapped(StorageUnavailableError("down"), depth))
    assert is_storage_unavailable(raised.value)
    assert isinstance(svc.tool_error_handler(ctx, wrapped(ValueError("切り口が不正"), depth)), str)


@pytest.mark.parametrize("depth", [1, 2])
def test_api_maps_wrapped_storage_failure_to_503_and_other_agent_failures_to_502(client, monkeypatch, depth):
    async def storage_down(question, session_id):
        raise wrapped(StorageUnavailableError("down"), depth)

    async def agent_broken(question, session_id):
        raise wrapped(ValueError("モデルの出力が不正"), depth)

    body = {"question": "売上", "session_id": "s1"}

    monkeypatch.setattr(service, "run_analysis", storage_down)
    r = client.post("/analysis", json=body)
    assert (r.status_code, r.json()["error"]["code"]) == (503, "database_unavailable")

    monkeypatch.setattr(service, "run_analysis", agent_broken)
    r = client.post("/analysis", json=body)
    assert (r.status_code, r.json()["error"]["code"]) == (502, "agent_failed")
