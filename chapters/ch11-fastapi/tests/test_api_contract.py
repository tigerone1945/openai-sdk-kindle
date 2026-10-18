"""API契約・エラー対応・承認の保管・非同期の動作を、LLMなしで確認する。

実行(リポジトリのルートから):
    uv run --with pytest --with pytest-asyncio pytest chapters/ch11-fastapi/tests -q
"""
import asyncio
import sys
import time
from pathlib import Path

import httpx
import openai
import pytest
from agents.exceptions import MaxTurnsExceeded
from fastapi.testclient import TestClient
from pydantic import BaseModel

SRC = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(SRC))

import service  # noqa: E402
from agent_service import SalesAnalysisResult  # noqa: E402
from api import main  # noqa: E402

VALID = {"question": "カテゴリ別の売上を分析して", "session_id": "demo-session"}


def completed(analysis_type="category_sales") -> service.AnalysisOutcome:
    return service.AnalysisOutcome(
        result=SalesAnalysisResult(
            question="q",
            analysis_type=analysis_type,
            result_summary="要約",
            key_findings=["発見1", "発見2"],
            next_action="次の分析",
        ),
        pending=None,
    )


def pending() -> service.AnalysisOutcome:
    return service.AnalysisOutcome(
        result=None,
        pending=service.PendingApproval(
            approval_id="abc123",
            items=[service.PendingItem("create_review_request", {"order_id": "O0001", "reason": "確認"})],
        ),
    )


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


def patch_analysis(monkeypatch, outcome=None, error=None):
    async def fake(question, session_id):
        if error:
            raise error
        return outcome

    monkeypatch.setattr(service, "run_analysis", fake)


# --- 契約 -------------------------------------------------------


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_completed_response_shape(client, monkeypatch):
    patch_analysis(monkeypatch, completed())
    r = client.post("/analysis", json=VALID)
    body = r.json()

    assert r.status_code == 200
    assert body["status"] == "completed" and body["approval"] is None
    assert set(body["result"]) == {"analysis_type", "result_summary", "key_findings", "next_action"}
    assert body["request_id"] == r.headers["X-Request-ID"]


def test_response_is_backward_compatible_for_old_clients(client, monkeypatch):
    """後から足した request_id を知らない古いクライアントでも、読める。"""

    class OldResult(BaseModel):
        analysis_type: str
        result_summary: str
        key_findings: list[str]
        next_action: str

    class OldResponse(BaseModel):  # request_id を知らない
        status: str
        result: OldResult | None = None

    patch_analysis(monkeypatch, completed())
    parsed = OldResponse.model_validate(client.post("/analysis", json=VALID).json())
    assert parsed.result.result_summary == "要約"


def test_request_ignores_unknown_fields_from_newer_clients(client, monkeypatch):
    patch_analysis(monkeypatch, completed())
    r = client.post("/analysis", json={**VALID, "future_option": True})
    assert r.status_code == 200


def test_analysis_type_is_a_closed_set(client):
    schema = client.get("/openapi.json").json()["components"]["schemas"]["AnalysisResult"]
    values = schema["properties"]["analysis_type"]["enum"]
    assert "other" in values and "category_sales" in values
    assert len(values) == len(set(values))


def test_openapi_documents_error_responses(client):
    responses = client.get("/openapi.json").json()["paths"]["/analysis"]["post"]["responses"]
    assert {"200", "422", "502", "503", "504"} <= set(responses)


# --- 入力の検証 -------------------------------------------------


@pytest.mark.parametrize("payload,field", [
    ({"question": "", "session_id": "s1"}, "question"),
    ({"question": "   ".strip(), "session_id": "s1"}, "question"),
    ({"question": "x" * 2001, "session_id": "s1"}, "question"),
    ({"question": "q", "session_id": "bad id/../"}, "session_id"),
    ({"question": "q", "session_id": "a" * 65}, "session_id"),
    ({"question": "q"}, "session_id"),
])
def test_invalid_input_is_422_without_echoing_values(client, payload, field):
    r = client.post("/analysis", json=payload)
    error = r.json()["error"]

    assert r.status_code == 422 and error["code"] == "validation_error"
    assert field in error["message"]
    assert "bad id" not in r.text and "xxxx" not in r.text


# --- Error Model ------------------------------------------------


def test_out_of_scope_is_422_with_generic_message(client, monkeypatch):
    patch_analysis(monkeypatch, error=service.OutOfScopeError())
    r = client.post("/analysis", json=VALID)

    assert r.status_code == 422 and r.json()["error"]["code"] == "out_of_scope"
    assert r.json()["error"]["request_id"] == r.headers["X-Request-ID"]


@pytest.mark.parametrize("error,status,code", [
    (openai.APIConnectionError(request=httpx.Request("POST", "http://x")), 503, "model_unavailable"),
    (MaxTurnsExceeded("too many"), 502, "agent_failed"),
    (RuntimeError("secret internal detail: /Users/x/.env"), 500, "internal_error"),
])
def test_exceptions_map_to_error_codes_without_leaking(client, monkeypatch, error, status, code):
    patch_analysis(monkeypatch, error=error)
    r = client.post("/analysis", json=VALID)

    assert r.status_code == status and r.json()["error"]["code"] == code
    assert "secret" not in r.text and "/Users" not in r.text and "too many" not in r.text


def test_timeout_is_504(client, monkeypatch):
    async def slow(question, session_id):
        await asyncio.sleep(5)

    monkeypatch.setattr(service, "run_analysis", slow)
    monkeypatch.setattr(main, "ANALYSIS_TIMEOUT_SECONDS", 0.05)
    r = client.post("/analysis", json=VALID)

    assert r.status_code == 504 and r.json()["error"]["code"] == "timeout"


# --- 承認 -------------------------------------------------------


def test_approval_flow_over_http(client, monkeypatch):
    patch_analysis(monkeypatch, pending())
    first = client.post("/analysis", json=VALID).json()

    assert first["status"] == "approval_required" and first["result"] is None
    assert first["approval"]["approval_id"] == "abc123"
    assert first["approval"]["items"][0]["arguments"]["order_id"] == "O0001"
    assert "state" not in str(first).lower()  # RunStateは、クライアントへ返さない

    async def fake_resolve(approval_id, approve):
        assert (approval_id, approve) == ("abc123", False)
        return completed("review_request")

    monkeypatch.setattr(service, "resolve_approval", fake_resolve)
    second = client.post("/approvals/abc123", json={"decision": "reject"})
    assert second.status_code == 200 and second.json()["status"] == "completed"


def test_invalid_decision_is_422(client):
    r = client.post("/approvals/abc123", json={"decision": "maybe"})
    assert r.status_code == 422 and "decision" in r.json()["error"]["message"]


def test_unknown_approval_is_404(client, monkeypatch, tmp_path):
    monkeypatch.setattr(service, "APPROVALS_DB_PATH", tmp_path / "approvals.db")
    r = client.post("/approvals/does-not-exist", json={"decision": "approve"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "approval_not_found"


# --- 承認待ちの保管 ---------------------------------------------


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "APPROVALS_DB_PATH", tmp_path / "approvals.db")


def test_pending_can_be_taken_only_once(store):
    approval_id = service.save_pending("s1", "STATE-TEXT")
    assert service.take_pending(approval_id) == ("s1", "STATE-TEXT")
    with pytest.raises(service.ApprovalNotFoundError):
        service.take_pending(approval_id)  # 二重承認はできない


def test_expired_pending_is_gone(store, monkeypatch):
    approval_id = service.save_pending("s1", "STATE")
    monkeypatch.setattr(service, "APPROVAL_TTL_SECONDS", -1)
    with pytest.raises(service.ApprovalNotFoundError):
        service.take_pending(approval_id)


def test_approval_ids_are_unguessable(store):
    ids = {service.save_pending("s", "x") for _ in range(50)}
    assert len(ids) == 50 and all(len(i) == 32 for i in ids)


# --- 非同期 -----------------------------------------------------


@pytest.mark.asyncio
async def test_health_responds_while_analysis_is_running(monkeypatch):
    async def slow(question, session_id):
        await asyncio.sleep(0.6)
        return completed()

    monkeypatch.setattr(service, "run_analysis", slow)
    transport = httpx.ASGITransport(app=main.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        running = asyncio.create_task(c.post("/analysis", json=VALID))
        await asyncio.sleep(0.1)

        t = time.perf_counter()
        health = await c.get("/health")
        elapsed = time.perf_counter() - t

        assert health.status_code == 200 and elapsed < 0.3
        assert (await running).status_code == 200


@pytest.mark.asyncio
async def test_requests_run_concurrently(monkeypatch):
    async def slow(question, session_id):
        await asyncio.sleep(0.5)
        return completed()

    monkeypatch.setattr(service, "run_analysis", slow)
    transport = httpx.ASGITransport(app=main.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        t = time.perf_counter()
        responses = await asyncio.gather(*[c.post("/analysis", json=VALID) for _ in range(3)])
        elapsed = time.perf_counter() - t

    assert all(r.status_code == 200 for r in responses)
    assert elapsed < 1.0  # 直列なら 1.5 秒以上かかる
