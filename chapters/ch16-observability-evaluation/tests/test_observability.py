"""構造化ログ: 何を残し、何を残さないか。"""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from conftest import M

obs, service = M.observability, M.service


def lines(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]


def test_log_event_is_one_json_line_with_timestamp_level_and_event(capsys):
    obs.log_event("analysis_completed", analysis_type="region_sales", duration_ms=1350)
    (rec,) = lines(capsys)
    assert rec["event"] == "analysis_completed" and rec["level"] == "info" and rec["duration_ms"] == 1350
    assert rec["ts"].endswith("+00:00")


def test_forbidden_fields_are_dropped_by_name_and_their_values_never_appear(capsys):
    obs.log_event("x", question="北斗システムの売上は?", api_key="sk-secret", result_summary="東北が最大", ok=1)
    out = capsys.readouterr().out
    rec = json.loads(out)
    assert rec["ok"] == 1 and rec["dropped_fields"] == ["api_key", "question", "result_summary"]
    for value in ("北斗システム", "sk-secret", "東北が最大"):
        assert value not in out


def test_forbidden_names_match_case_insensitively(capsys):
    obs.log_event("x", Password="p", TOKEN="t")
    assert "dropped_fields" in capsys.readouterr().out


def make_app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):  # 第13章の API と同じ順序・同じ名前
        request.state.request_id = "req-123"
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/items/{item_id}")
    async def item(item_id: str):
        return {"id": item_id}

    @app.get("/boom")
    async def boom():
        raise HTTPException(status_code=503, detail="x")

    obs.install(app)
    return app


def test_request_is_logged_with_route_template_not_the_id_value(capsys):
    TestClient(make_app()).get("/items/ORDER-SECRET-77")
    (rec,) = lines(capsys)
    assert rec["event"] == "request_completed" and rec["path"] == "/items/{item_id}"
    assert "ORDER-SECRET-77" not in json.dumps(rec)
    assert rec["status"] == 200 and rec["request_id"] == "req-123" and rec["duration_ms"] >= 0


def test_health_checks_are_not_logged(capsys):
    TestClient(make_app()).get("/health")
    assert lines(capsys) == []


def test_5xx_is_logged_at_error_level(capsys):
    TestClient(make_app()).get("/boom")
    (rec,) = lines(capsys)
    assert rec["status"] == 503 and rec["level"] == "error"


def test_unhandled_exception_is_still_logged_as_500(capsys):
    app = make_app()

    @app.get("/crash")
    async def crash():
        raise RuntimeError("内部の詳細: 顧客 北斗システム")

    with pytest.raises(RuntimeError):
        TestClient(app).get("/crash")
    (rec,) = lines(capsys)
    assert rec["status"] == 500 and rec["level"] == "error"
    assert "北斗システム" not in json.dumps(rec, ensure_ascii=False)


# --- service の記録 -------------------------------------------------------


@pytest.fixture
def fake_runner(monkeypatch, tmp_path):
    monkeypatch.delenv("DB_BACKEND", raising=False)
    monkeypatch.setattr(service.core, "SESSION_DB_PATH", tmp_path / "s.db")
    state = SimpleNamespace(outcome=None, error=None)

    async def run(agent, input, session=None):
        if state.error:
            raise state.error
        return state.outcome

    monkeypatch.setattr(service.Runner, "run", run)
    return state


def completed(summary="東北が最大です。顧客 北斗システム"):
    result = M.agent_service.SalesAnalysisResult(
        question="q", analysis_type="region_sales", result_summary=summary, key_findings=["f"], next_action="n")
    return SimpleNamespace(interruptions=[], final_output=result)


@pytest.mark.asyncio
async def test_completed_analysis_logs_type_and_duration_but_no_content(fake_runner, capsys):
    fake_runner.outcome = completed()
    await service.run_analysis("北斗システムの売上を教えて", "sess-1")
    out = capsys.readouterr().out
    rec = json.loads(out.strip().splitlines()[-1])
    assert rec["event"] == "analysis_completed" and rec["analysis_type"] == "region_sales" and rec["session_id"] == "sess-1"
    assert "北斗システム" not in out and "東北が最大" not in out


@pytest.mark.asyncio
async def test_failure_logs_the_error_type_but_not_its_message(fake_runner, capsys):
    fake_runner.error = ValueError("顧客 北斗システム の行で失敗")
    with pytest.raises(ValueError):
        await service.run_analysis("q", "sess-2")
    out = capsys.readouterr().out
    rec = json.loads(out.strip().splitlines()[-1])
    assert rec["event"] == "analysis_failed" and rec["level"] == "error" and rec["error_type"] == "ValueError"
    assert "北斗システム" not in out


@pytest.mark.asyncio
async def test_missing_approval_is_logged_as_a_warning(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("DB_BACKEND", raising=False)
    monkeypatch.setattr(service, "APPROVALS_DB_PATH", tmp_path / "a.db")
    with pytest.raises(service.ApprovalNotFoundError):
        await service.resolve_approval("nope", True)
    rec = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rec["event"] == "approval_not_found" and rec["level"] == "warning"
