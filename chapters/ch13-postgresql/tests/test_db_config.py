"""接続の設定(DBなしで確認できるもの)。"""
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import TimeoutError as PoolTimeout

from conftest import M

db = M.db
SqlSalesRepository = M.repository.SqlSalesRepository


@pytest.fixture
def pg_env(monkeypatch):
    for k, v in {
        "DB_HOST": "db", "DB_PORT": "5432", "DB_NAME": "app",
        "DB_RO_PASSWORD": "p@ss/w:rd%40", "DB_RW_PASSWORD": "plain",
        "DB_OWNER_USER": "owner", "DB_OWNER_PASSWORD": "o",
    }.items():
        monkeypatch.setenv(k, v)


def test_url_is_built_from_parts_so_special_characters_survive(pg_env):
    url = db.postgres_url("ro")
    assert url.password == "p@ss/w:rd%40" and url.host == "db" and url.database == "app"
    # 部品から組み立てた文字列は、解析し直しても、同じパスワードになる
    assert make_url(url.render_as_string(hide_password=False)).password == "p@ss/w:rd%40"


def test_naive_url_string_with_special_characters_is_misparsed():
    """URLの文字列に、そのまま埋め込むと、パスワードの `@` や `/` で、別の部分として解釈される。"""
    naive = make_url("postgresql+psycopg://user:p@ss/w:rd@db:5432/app")
    assert naive.password != "p@ss/w:rd"


def test_password_is_hidden_in_logs(pg_env):
    assert "p@ss" not in str(db.postgres_url("ro")) and "***" in str(db.postgres_url("ro"))


def test_missing_setting_gives_a_clear_error(monkeypatch):
    monkeypatch.delenv("DB_RO_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="DB_RO_PASSWORD"):
        db.postgres_url("ro")


def test_role_names_are_fixed_and_match_the_privilege_migration(pg_env):
    """GRANTの宛先(SQL)と、アプリが使う役割名(コード)が、食い違わない。"""
    grants = (M.migrate.MIGRATIONS_DIR / "0002_privileges.sql").read_text(encoding="utf-8")
    for name in db.ROLE_NAMES.values():
        assert name in grants
    assert db.postgres_url("ro").username == "agent_ro" and db.postgres_url("rw").username == "agent_rw"
    assert db.postgres_url("owner").username == "owner"  # 管理者だけは、環境から


def test_unknown_backend_is_rejected(monkeypatch):
    monkeypatch.setenv("DB_BACKEND", "mysql")
    with pytest.raises(RuntimeError, match="postgres か sqlite"):
        db.build_repository()


def test_default_backend_is_sqlite_for_local_work(monkeypatch, tmp_path):
    monkeypatch.delenv("DB_BACKEND", raising=False)
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "x.db"))
    assert isinstance(db.build_repository(), SqlSalesRepository)


def test_pool_settings_are_explicit(pg_env):
    engine = db.make_postgres_engine(db.postgres_url("ro"))
    pool = engine.pool
    assert (pool.size(), pool._max_overflow, pool._timeout, pool._recycle) == (5, 5, 5, 1800)
    assert pool._pre_ping is True


def test_pool_exhaustion_fails_fast_instead_of_waiting_forever(tmp_path):
    """接続が足りないとき、待ち続けず、決めた時間で例外になる(リクエストが溜まり続けるのを防ぐ)。"""
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}", pool_size=1, max_overflow=0, pool_timeout=0.5)
    held = engine.connect()
    try:
        started = time.perf_counter()
        with pytest.raises(PoolTimeout):
            engine.connect()
        assert time.perf_counter() - started < 2.0
    finally:
        held.close()
