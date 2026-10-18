"""SQLiteからPostgreSQLへのデータ移行を確認する。PostgreSQLが必要(TEST_PG_URL)。"""
import importlib.util
import sqlite3
import sys
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from conftest import M, ROOT, SRC, TEST_PG_URL, build_sqlite

migrate = M.migrate
SqlSalesRepository = M.repository.SqlSalesRepository

pytestmark = pytest.mark.skipif(not TEST_PG_URL, reason="TEST_PG_URL が未設定のため、PostgreSQLのテストは実行しません")

ROLES = {"agent_ro": "test-ro", "agent_rw": "test-rw"}

def load_mover():
    """移行スクリプトは db を import する。第13章の db を見えるようにして読み込む。"""
    saved = (sys.modules.pop("db", None), sys.modules.pop("repository", None), sys.modules.pop("catalog", None))
    sys.path.insert(0, str(SRC))
    try:
        spec = importlib.util.spec_from_file_location("migrate_sqlite_to_postgres", SRC / "scripts/migrate_sqlite_to_postgres.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SRC))
        for n in ("db", "repository", "catalog"):
            sys.modules.pop(n, None)
        for n, m in zip(("db", "repository", "catalog"), saved):
            if m is not None:
                sys.modules[n] = m


mover = load_mover()

svc = M.agent_service


@pytest.fixture
def source(tmp_path):
    """第12章までのSQLite:売上データと、登録済みのレビュー依頼2件(状態)。"""
    _, db_path = build_sqlite(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO review_requests VALUES (?, ?, ?)",
            [("O0001", "高額注文の確認", "2026-10-12T09:00:00"), ("O0007", "確認のため", "2026-10-12T10:30:00")],
        )
    return db_path


@pytest.fixture
def migrated_empty_schema(empty_schema):
    engine, name = empty_schema
    migrate.run(engine, ROLES)  # スキーマだけ(デモデータなし)
    return engine


def count(engine, table):
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()


def test_all_rows_and_state_are_moved_and_verified(migrated_empty_schema, source):
    engine = migrated_empty_schema
    counts = mover.migrate(engine, source)

    assert counts == {"customers": 10, "products": 12, "orders": 300, "review_requests": 2}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT order_id FROM review_requests ORDER BY 1")).scalars().all() == ["O0001", "O0007"]
        assert conn.execute(text("SELECT SUM(sales_amount) FROM orders")).scalar_one() == 28_298_695


def test_tool_output_is_identical_before_and_after_the_move(migrated_empty_schema, source):
    sqlite_repo = SqlSalesRepository(*(mover.db.make_sqlite_engine(source, ro) for ro in (True, False)))
    mover.migrate(migrated_empty_schema, source)
    pg_repo = SqlSalesRepository(migrated_empty_schema, migrated_empty_schema)

    outputs = []
    for repo in (sqlite_repo, pg_repo):
        svc.set_repository(repo)
        outputs.append([svc.sales_summary(), svc.sales_by_dimension("category"), svc.review_orders(10), svc.preview_join_text("orders", "customers", 3)])
        # 移行済みの注文は、既に登録済みとして扱われる(状態が引き継がれている)
        assert "既に登録済み" in svc.register_review_request("O0001", "再登録")
    svc.set_repository(None)
    assert outputs[0] == outputs[1]


def test_timestamps_are_read_in_the_declared_timezone(migrated_empty_schema, source):
    mover.migrate(migrated_empty_schema, source, zone="Asia/Tokyo")
    with migrated_empty_schema.connect() as conn:
        stored = conn.execute(text("SELECT created_at FROM review_requests WHERE order_id = 'O0001'")).scalar_one()
    # 09:00(東京)= 00:00(UTC)
    assert stored.astimezone(timezone.utc) == datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)


def test_refuses_to_run_into_a_non_empty_target(migrated_empty_schema, source):
    mover.migrate(migrated_empty_schema, source)
    with pytest.raises(RuntimeError, match="空ではありません"):
        mover.migrate(migrated_empty_schema, source)
    assert count(migrated_empty_schema, "orders") == 300  # 2回目で、増えても減ってもいない


def test_a_broken_source_leaves_the_target_untouched(migrated_empty_schema, source):
    """移行元に、存在しない注文を指すレビュー依頼があれば、全体を取り消す(途中まで入った状態を残さない)。"""
    with sqlite3.connect(source) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("INSERT INTO review_requests VALUES ('O9999', '孤児', '2026-10-12T11:00:00')")

    with pytest.raises(Exception, match="O9999|foreign key|外部キー"):
        mover.migrate(migrated_empty_schema, source)

    for table in ("customers", "products", "orders", "review_requests"):
        assert count(migrated_empty_schema, table) == 0


def test_verification_detects_a_single_changed_value(migrated_empty_schema, source):
    """検証が、本当に1行の食い違いを見つけられること(件数と合計だけでは、見逃す変更)。"""
    data = mover.prepared(mover.read_sqlite(source), "UTC")
    original = mover.read_sqlite(source)
    original["review_requests"] = data["review_requests"]

    with migrated_empty_schema.begin() as conn:
        mover.insert_all(conn, data)
        # 売上の合計が変わらない形で、2つの注文の金額を入れ替える(件数も合計も同じ)
        conn.execute(text("UPDATE orders SET sales_amount = sales_amount + 100 WHERE order_id = 'O0001'"))
        conn.execute(text("UPDATE orders SET sales_amount = sales_amount - 100 WHERE order_id = 'O0002'"))
        with pytest.raises(mover.MigrationVerificationError, match="sales_amount"):
            mover.verify(conn, original)


def test_source_is_opened_read_only(source):
    before = source.read_bytes()
    mover.read_sqlite(source)
    assert source.read_bytes() == before
