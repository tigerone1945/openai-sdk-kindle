"""状態(承認待ち・会話履歴)を DB に置くことの検査。

「別のタスク」は、別の Engine(別の接続の集まり)で表す。タスクをまたいで状態が見えるかが、この章の論点。
"""
import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from conftest import M, SRC, needs_pg

service = M.service


@pytest.fixture
def as_database(pg, monkeypatch):
    """service を DB モードにし、状態の接続を、テスト専用 schema の agent_rw にする。"""
    monkeypatch.setenv("DB_BACKEND", "postgres")
    engines = []

    def make_task():
        """新しい「タスク」: 自分専用の同期・非同期の Engine を持つ。"""
        sync, aio = pg.sync_engine("agent_rw", "test-rw"), pg.async_engine("agent_rw", "test-rw")
        engines.extend([sync, aio])
        return sync, aio

    def switch_to(task):
        monkeypatch.setattr(service, "_state_engine", lambda: task[0])
        monkeypatch.setattr(service, "_state_async_engine", lambda: task[1])

    yield SimpleNamespace(make_task=make_task, switch_to=switch_to)
    for e in engines:
        if hasattr(e, "sync_engine"):
            asyncio.run(e.dispose())
        else:
            e.dispose()


# --- 承認待ち -----------------------------------------------------


@needs_pg
def test_approval_saved_by_one_task_can_be_taken_by_another(as_database):
    task_a, task_b = as_database.make_task(), as_database.make_task()

    as_database.switch_to(task_a)
    approval_id = service.save_pending("sess-1", "RUNSTATE-JSON")

    as_database.switch_to(task_b)  # 別のタスク(ALB が別の台へ振り分けた)
    assert service.take_pending(approval_id) == ("sess-1", "RUNSTATE-JSON")


@needs_pg
def test_approval_is_one_time_use(as_database):
    task = as_database.make_task()
    as_database.switch_to(task)
    approval_id = service.save_pending("s", "state")
    service.take_pending(approval_id)
    with pytest.raises(service.ApprovalNotFoundError):
        service.take_pending(approval_id)


@needs_pg
def test_expired_approval_is_not_found_and_swept(as_database, monkeypatch):
    task = as_database.make_task()
    as_database.switch_to(task)
    approval_id = service.save_pending("s", "state")
    real_time = time.time  # 差し替え後の lambda が、自分自身を呼ばないように
    monkeypatch.setattr(service.time, "time", lambda: real_time() + service.APPROVAL_TTL_SECONDS + 5)
    with pytest.raises(service.ApprovalNotFoundError):
        service.take_pending(approval_id)
    with task[0].connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM pending_approvals")).scalar() == 0


@needs_pg
def test_only_one_of_many_concurrent_requests_gets_an_approval(as_database):
    """本物の take_pending を、同時に 8 本から呼ぶ。承認は 1 回しか使えない。"""
    as_database.switch_to(as_database.make_task())
    approval_id = service.save_pending("s", "state")
    outcomes, barrier = [], threading.Barrier(8)

    def attempt():
        barrier.wait()
        try:
            service.take_pending(approval_id)
            outcomes.append("取れた")
        except service.ApprovalNotFoundError:
            outcomes.append("無い")

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(outcomes) == ["取れた"] + ["無い"] * 7


# --- 会話履歴 -----------------------------------------------------


@needs_pg
def test_conversation_history_is_shared_across_tasks(as_database):
    task_a, task_b = as_database.make_task(), as_database.make_task()
    item = {"role": "user", "content": "地域別の売上を分析してください"}

    as_database.switch_to(task_a)
    asyncio.run(service.open_session("conv-1").add_items([item]))

    as_database.switch_to(task_b)
    assert asyncio.run(service.open_session("conv-1").get_items()) == [item]


@needs_pg
def test_conversation_history_is_separate_per_session(as_database):
    as_database.switch_to(as_database.make_task())
    asyncio.run(service.open_session("a").add_items([{"role": "user", "content": "A"}]))
    assert asyncio.run(service.open_session("b").get_items()) == []


# --- 権限 -----------------------------------------------------------


@needs_pg
def test_read_only_role_cannot_see_pending_approvals_or_history(pg):
    ro = pg.sync_engine("agent_ro", "test-ro")
    for table in ("pending_approvals", "agent_sessions", "agent_messages"):
        with pytest.raises(ProgrammingError, match="permission denied"):
            with ro.connect() as conn:
                conn.execute(text(f"SELECT 1 FROM {table}"))
    ro.dispose()


@needs_pg
def test_app_write_role_has_dml_but_no_ddl(pg):
    rw = pg.sync_engine("agent_rw", "test-rw")
    with rw.begin() as conn:
        conn.execute(text("INSERT INTO pending_approvals VALUES ('x', 's', 'st', 1.0)"))
    for ddl in ("DROP TABLE pending_approvals", "CREATE TABLE evil (x int)", "ALTER TABLE agent_messages ADD COLUMN y int"):
        with pytest.raises(ProgrammingError, match="permission denied|must be owner"):
            with rw.begin() as conn:
                conn.execute(text(ddl))
    rw.dispose()


@needs_pg
def test_migration_schema_matches_what_the_sdk_expects(pg):
    """0003 の列が、SDK が自動で作る表と一致すること(SDK を更新したときの食い違いを検出する)。"""
    from agents.extensions.memory import SQLAlchemySession
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine

    from conftest import TEST_PG_URL

    admin = create_engine(TEST_PG_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("CREATE SCHEMA sdk_ref"))

    async def build():
        engine = create_async_engine(make_url(TEST_PG_URL), connect_args={"options": "-csearch_path=sdk_ref"})
        await SQLAlchemySession("x", engine=engine, create_tables=True)._ensure_tables()
        await engine.dispose()

    try:
        asyncio.run(build())

        def shape(engine, schema):
            insp = inspect(engine)
            return {
                t: sorted((c["name"], str(c["type"]).split("(")[0], c["nullable"]) for c in insp.get_columns(t, schema=schema))
                for t in ("agent_sessions", "agent_messages")
            }

        assert shape(pg.owner, pg.name) == shape(admin, "sdk_ref")
    finally:
        with admin.connect() as conn:
            conn.execute(text("DROP SCHEMA sdk_ref CASCADE"))
        admin.dispose()


# --- 手元(SQLite)の動き -----------------------------------------------


def test_without_database_backend_state_stays_in_local_files(tmp_path, monkeypatch):
    monkeypatch.delenv("DB_BACKEND", raising=False)
    monkeypatch.setattr(service, "APPROVALS_DB_PATH", tmp_path / "approvals.db")
    approval_id = service.save_pending("s", "state")
    assert (tmp_path / "approvals.db").exists()
    assert service.take_pending(approval_id) == ("s", "state")
    assert type(service.open_session("s")).__name__ == "SQLiteSession"


def test_database_backend_uses_sdk_sqlalchemy_session(monkeypatch):
    monkeypatch.setenv("DB_BACKEND", "postgres")
    from sqlalchemy.ext.asyncio import create_async_engine

    # 作るだけで接続はしない(接続は最初の操作まで遅延される)
    engine = create_async_engine("postgresql+psycopg://u:p@127.0.0.1:1/none")
    monkeypatch.setattr(service, "_state_async_engine", lambda: engine)
    session = service.open_session("s")
    assert type(session).__name__ == "SQLAlchemySession"
