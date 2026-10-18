"""DB が使えないとき、状態の保存先(承認待ち・会話履歴)の失敗が、500 ではなく 503 になること。

第15章で足した保存先には、第13章の Repository が持っていた「DB の障害 → StorageUnavailableError」の翻訳が無かった。
第16章の障害演習(DB のパスワードを間違えた)で、利用者に 500 internal_error が返って発覚した。
"""
import json
from types import SimpleNamespace

import pytest
import psycopg
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, ProgrammingError

from conftest import M

service, api_main = M.service, M.api_main
StorageUnavailableError = service.StorageUnavailableError

DOWN_URL = "postgresql+psycopg://u:p@127.0.0.1:1/none"  # 繋がらない先


def down_engine():
    return create_engine(DOWN_URL, connect_args={"connect_timeout": 1})


@pytest.fixture
def database_mode(monkeypatch):
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setattr(service, "_state_engine", down_engine)


def test_saving_an_approval_while_the_database_is_down_is_unavailable_not_a_crash(database_mode):
    with pytest.raises(StorageUnavailableError):
        service.save_pending("s", "state")


def test_taking_an_approval_while_the_database_is_down_is_unavailable(database_mode):
    with pytest.raises(StorageUnavailableError):
        service.take_pending("x")


def auth_failure():
    """実機で見た失敗と同じ形: psycopg の認証エラーを、SQLAlchemy が包む。"""
    return OperationalError("SELECT 1", {}, psycopg.OperationalError('FATAL: password authentication failed for user "agent_rw"'))


@pytest.fixture
def runner_raising(monkeypatch, tmp_path):
    monkeypatch.delenv("DB_BACKEND", raising=False)
    monkeypatch.setattr(service.core, "SESSION_DB_PATH", tmp_path / "s.db")
    state = SimpleNamespace(error=None)

    async def run(agent, input, session=None):
        raise state.error

    monkeypatch.setattr(service.Runner, "run", run)
    return state


@pytest.mark.asyncio
async def test_a_session_store_failure_becomes_unavailable_and_is_logged_without_the_message(runner_raising, capsys):
    runner_raising.error = auth_failure()
    with pytest.raises(StorageUnavailableError):
        await service.run_analysis("q", "sess")
    out = capsys.readouterr().out
    rec = json.loads(out.strip().splitlines()[-1])
    assert rec["event"] == "analysis_failed" and rec["storage_unavailable"] is True and rec["error_type"] == "OperationalError"
    assert "password authentication" not in out and "agent_rw" not in out


@pytest.mark.asyncio
async def test_the_cause_chain_is_followed_when_the_sdk_wraps_the_error(runner_raising):
    wrapper = RuntimeError("wrapped by SDK")
    wrapper.__cause__ = auth_failure()
    runner_raising.error = wrapper
    with pytest.raises(StorageUnavailableError):
        await service.run_analysis("q", "sess")


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ValueError("bug"), ProgrammingError("SELECT", {}, Exception('relation "x" does not exist'))])
async def test_other_failures_are_not_disguised_as_an_outage(runner_raising, error):
    runner_raising.error = error
    with pytest.raises(type(error)):
        await service.run_analysis("q", "sess")


@pytest.mark.asyncio
async def test_resuming_an_approval_with_a_failing_database_is_unavailable(runner_raising, monkeypatch):
    monkeypatch.setattr(service, "take_pending", lambda approval_id: ("s", "state"))

    async def fake_from_string(agent, text):
        return SimpleNamespace(get_interruptions=lambda: [])

    monkeypatch.setattr(service.RunState, "from_string", fake_from_string)
    runner_raising.error = auth_failure()
    with pytest.raises(StorageUnavailableError):
        await service.resolve_approval("a", True)


# --- API を通して見える応答 ----------------------------------------------------


@pytest.mark.parametrize("body", [{"question": "地域別の売上は?", "session_id": "s1"}])
def test_the_http_response_is_503_database_unavailable_not_500(runner_raising, body):
    runner_raising.error = auth_failure()
    r = TestClient(api_main.app, raise_server_exceptions=False).post("/analysis", json=body)
    assert r.status_code == 503 and r.json()["error"]["code"] == "database_unavailable"
    assert "password" not in r.text and "agent_rw" not in r.text  # 内部の詳細は返さない


def test_a_real_unexpected_error_is_still_500(runner_raising):
    runner_raising.error = ValueError("bug")
    r = TestClient(api_main.app, raise_server_exceptions=False).post("/analysis", json={"question": "q", "session_id": "s1"})
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal_error"


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [psycopg.OperationalError("connection refused"), psycopg.InterfaceError("connection is closed")])
async def test_raw_driver_errors_not_wrapped_by_sqlalchemy_are_also_unavailable(runner_raising, raw):
    runner_raising.error = raw
    with pytest.raises(StorageUnavailableError):
        await service.run_analysis("q", "sess")
