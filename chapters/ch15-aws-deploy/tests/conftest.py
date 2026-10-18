"""第15章のテスト用の部品。PostgreSQL は TEST_PG_URL(管理者の接続)があるときだけ使う(第13章と同じ)。"""
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

SRC = Path(__file__).parent.parent / "src"
ROOT = SRC.parent.parent.parent
CH13_SRC = ROOT / "chapters/ch13-postgresql/src"
TEST_PG_URL = os.environ.get("TEST_PG_URL")

needs_pg = pytest.mark.skipif(not TEST_PG_URL, reason="TEST_PG_URL が未設定のため、PostgreSQLのテストは実行しません")


def import_chapter_modules() -> SimpleNamespace:
    """第15章のモジュールを、他の章の同名モジュールと衝突しないように読み込む(第13章の conftest と同じ方法)。

    実際のコンテナと同じ並び: agent_service・service は第15章、それ以外(db・repository・api など)は第13章。
    """
    names = ["agent_service", "service", "api", "api.main", "db", "repository", "catalog", "migrate", "seed"]
    saved = {n: sys.modules.pop(n) for n in names if n in sys.modules}
    saved_path = list(sys.path)
    sys.path[:0] = [str(SRC), str(CH13_SRC)]
    try:
        import agent_service, catalog, db, migrate, repository, seed, service  # noqa: E401
        return SimpleNamespace(
            agent_service=agent_service, catalog=catalog, db=db, migrate=migrate,
            repository=repository, seed=seed, service=service,
        )
    finally:
        for n in names:
            sys.modules.pop(n, None)
        sys.modules.update(saved)
        sys.path[:] = saved_path


M = import_chapter_modules()


class PgSchema(SimpleNamespace):
    """テスト専用の schema と、そこへ繋ぐ Engine を作る道具。"""

    def sync_engine(self, user=None, password=None):
        url = make_url(TEST_PG_URL)
        if user:
            url = url.set(username=user, password=password)
        return create_engine(url, connect_args={"options": f"-csearch_path={self.name}"})

    def async_engine(self, user, password):
        url = make_url(TEST_PG_URL).set(username=user, password=password)
        return create_async_engine(url, connect_args={"options": f"-csearch_path={self.name}"})


@pytest.fixture
def pg():
    """第15章のマイグレーション(0001〜0003)を、専用 schema に適用する。終わったら消す。"""
    admin = create_engine(TEST_PG_URL, isolation_level="AUTOCOMMIT")
    name = f"s_{uuid.uuid4().hex[:10]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{name}"'))
    schema = PgSchema(name=name)
    owner = schema.sync_engine()
    applied = M.migrate.run(owner, {"agent_ro": "test-ro", "agent_rw": "test-rw"}, directory=SRC / "migrations")
    assert applied[-1] == "0003_state"
    # 本番は public schema(0002 が USAGE を付ける)。テストは専用 schema なので、同じ前提を作る。
    # (USAGE が無い schema は、search_path から黙って読み飛ばされ、「表が無い」と見える)
    with admin.connect() as conn:
        conn.execute(text(f'GRANT USAGE ON SCHEMA "{name}" TO agent_ro, agent_rw'))
    schema.owner = owner
    yield schema
    owner.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
    admin.dispose()
