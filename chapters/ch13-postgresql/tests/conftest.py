"""テスト用のRepositoryを、SQLiteとPostgreSQLの両方で用意する。

PostgreSQLは、環境変数 TEST_PG_URL(管理者の接続。例: postgresql+psycopg://postgres:pass@127.0.0.1:55432/postgres)
があるときに使う。無いときは、PostgreSQLのテストを「スキップ」ではなく、理由つきで明示的に飛ばす。
各テストは、専用のschemaを作って使い、終わったら消す(テスト同士が干渉しない)。
"""
import importlib.util
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

SRC = Path(__file__).parent.parent / "src"
ROOT = SRC.parent.parent.parent
CH11_SRC = ROOT / "chapters/ch11-fastapi/src"


def import_chapter_modules() -> SimpleNamespace:
    """第13章のモジュールを、他の章の同名モジュール(agent_service・api など)と衝突しないように読み込む。

    読み込みの間だけ sys.modules と sys.path を差し替え、終わったら元に戻す。
    実際のコンテナの構成と同じ並び: 第13章の src が先、API が使う service.py は第11章のもの。
    """
    names = ["agent_service", "service", "api", "api.main", "db", "repository", "catalog", "migrate", "seed"]
    saved = {n: sys.modules.pop(n) for n in names if n in sys.modules}
    saved_path = list(sys.path)
    sys.path[:0] = [str(SRC), str(CH11_SRC)]
    try:
        import agent_service, catalog, db, migrate, repository, seed, service  # noqa: E401
        from api import main as api_main
        return SimpleNamespace(
            agent_service=agent_service, catalog=catalog, db=db, migrate=migrate,
            repository=repository, seed=seed, service=service, api_main=api_main,
        )
    finally:
        for n in names:
            sys.modules.pop(n, None)
        sys.modules.update(saved)
        sys.path[:] = saved_path


M = import_chapter_modules()
migrate, seed, repository = M.migrate, M.seed, M.repository
SqlSalesRepository = repository.SqlSalesRepository
make_sqlite_engine = M.db.make_sqlite_engine

CSV = ROOT / "data/raw/ai_agent_practice_sales.csv"
NORMALIZE = ROOT / "chapters/ch09-multitable/src/scripts/normalize_sales_db.py"
TEST_PG_URL = os.environ.get("TEST_PG_URL")

BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.skipif(
    not TEST_PG_URL, reason="TEST_PG_URL が未設定のため、PostgreSQLのテストは実行しません"))]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_sqlite(tmp_path: Path):
    """第9章の取り込みで、SQLiteのDBを作る(第11・12章が使ってきたものと同じ)。"""
    normalize = load_module("ch09_normalize_for_ch13", NORMALIZE)
    db_path = tmp_path / "sales.db"
    normalize.DB_PATH = db_path
    normalize.main()
    return SqlSalesRepository(
        make_sqlite_engine(db_path, read_only=True), make_sqlite_engine(db_path, read_only=False)
    ), db_path


@pytest.fixture
def pg_schema():
    """テスト専用のschemaを作り、その中にスキーマとデモデータを入れて、Engineを返す。終わったら消す。"""
    admin = create_engine(TEST_PG_URL, isolation_level="AUTOCOMMIT")
    name = f"t_{uuid.uuid4().hex[:10]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{name}"'))

    url = make_url(TEST_PG_URL)
    engine = create_engine(url, connect_args={"options": f"-csearch_path={name}"})

    # 役割(agent_ro / agent_rw)はクラスタ共通。GRANT は、このschemaのTableに対して効く。
    roles = {"agent_ro": "test-ro", "agent_rw": "test-rw"}
    applied = migrate.run(engine, roles, directory=migrate.MIGRATIONS_DIR)
    assert applied, "マイグレーションが適用されませんでした"
    seed.seed_demo_data(engine, CSV)

    yield engine, name, url

    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
    admin.dispose()


@pytest.fixture(params=BACKENDS)
def repo(request, tmp_path):
    """同じテストを、SQLiteとPostgreSQLの両方で実行するためのRepository。"""
    if request.param == "sqlite":
        repository, _ = build_sqlite(tmp_path)
        yield repository
        return

    engine, _, _ = request.getfixturevalue("pg_schema")
    yield SqlSalesRepository(engine, engine)


@pytest.fixture
def empty_schema():
    """まっさらなschema(マイグレーション前)。"""
    admin = create_engine(TEST_PG_URL, isolation_level="AUTOCOMMIT")
    name = f"m_{uuid.uuid4().hex[:10]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{name}"'))
    engine = create_engine(make_url(TEST_PG_URL), connect_args={"options": f"-csearch_path={name}"})
    yield engine, name
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
    admin.dispose()
