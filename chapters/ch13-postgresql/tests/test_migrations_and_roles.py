"""マイグレーション・シード・DBの権限(役割)を確認する。PostgreSQLが必要(TEST_PG_URL)。"""
import shutil
import threading
import uuid

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from conftest import CSV, M, TEST_PG_URL

migrate, seed = M.migrate, M.seed
RegisterResult, SqlSalesRepository = M.repository.RegisterResult, M.repository.SqlSalesRepository

pytestmark = pytest.mark.skipif(not TEST_PG_URL, reason="TEST_PG_URL が未設定のため、PostgreSQLのテストは実行しません")

ROLES = {"agent_ro": "test-ro", "agent_rw": "test-rw"}


def tables(engine) -> set[str]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"))}


# --- マイグレーション ---------------------------------------------


def test_migrations_apply_once_in_order(empty_schema):
    engine, _ = empty_schema
    first = migrate.run(engine, ROLES)
    assert first == ["0001_schema", "0002_privileges"]
    assert migrate.run(engine, ROLES) == []  # 2回目は何もしない(冪等)
    assert {"orders", "customers", "products", "review_requests", "schema_migrations"} <= tables(engine)


def test_editing_an_applied_migration_is_rejected(empty_schema, tmp_path):
    engine, _ = empty_schema
    for f in migrate.MIGRATIONS_DIR.glob("*.sql"):
        shutil.copy(f, tmp_path / f.name)
    migrate.run(engine, ROLES, directory=tmp_path)

    with (tmp_path / "0001_schema.sql").open("a", encoding="utf-8") as f:
        f.write("\n-- 後から書き足した\n")

    with pytest.raises(migrate.MigrationError, match="書き換えられています"):
        migrate.run(engine, ROLES, directory=tmp_path)


def test_failed_migration_leaves_nothing_behind(empty_schema, tmp_path):
    """PostgreSQLはDDLもトランザクションに入る。途中で失敗したら、最初のTableも作られなかったことになる。"""
    engine, _ = empty_schema
    (tmp_path / "0001_ok.sql").write_text("CREATE TABLE good (id INT PRIMARY KEY);", encoding="utf-8")
    (tmp_path / "0002_bad.sql").write_text("CREATE TABLE other (id INT); SELECT * FROM does_not_exist;", encoding="utf-8")

    with pytest.raises(ProgrammingError):
        migrate.run(engine, ROLES, directory=tmp_path)

    assert "good" not in tables(engine) and "other" not in tables(engine)
    assert "schema_migrations" not in tables(engine)  # 版の記録も、残らない


def test_concurrent_migrations_apply_each_version_once(empty_schema):
    """2つのコンテナが同時に起動しても、各版が1回だけ適用される(アドバイザリロック)。"""
    engine, _ = empty_schema
    results, errors = [], []

    def worker():
        try:
            results.append(migrate.run(engine, ROLES))
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert errors == []
    applied = sorted(v for r in results for v in r)
    assert applied == ["0001_schema", "0002_privileges"]  # 4並行でも、各版は1回だけ


# --- シード --------------------------------------------------------


def test_seed_is_idempotent(empty_schema):
    engine, _ = empty_schema
    migrate.run(engine, ROLES)
    assert "orders 300" in seed.seed_demo_data(engine, CSV)
    assert "入れません" in seed.seed_demo_data(engine, CSV)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM orders")).scalar_one() == 300


def test_seed_with_conflicting_attributes_fails_and_leaves_nothing(empty_schema, tmp_path):
    engine, _ = empty_schema
    migrate.run(engine, ROLES)
    df = pd.read_csv(CSV)
    df.loc[0, "customer_name"] = "別の名前"  # 同じcustomer_idで、名前が食い違う
    bad = tmp_path / "bad.csv"
    df.to_csv(bad, index=False)

    with pytest.raises(IntegrityError):
        seed.seed_demo_data(engine, bad)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM customers")).scalar_one() == 0  # 途中まで入ったものも残らない


# --- DBの権限(役割)------------------------------------------------


@pytest.fixture(scope="module")
def priv_db():
    """本物の public schema を持つ、専用のデータベース。ここで、役割ごとの権限を確かめる。"""
    admin = create_engine(TEST_PG_URL, isolation_level="AUTOCOMMIT")
    name = f"ch13_priv_{uuid.uuid4().hex[:8]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))

    base = make_url(TEST_PG_URL)
    owner = create_engine(base.set(database=name))
    migrate.run(owner, ROLES)
    seed.seed_demo_data(owner, CSV)
    ro = create_engine(base.set(database=name, username="agent_ro", password="test-ro"))
    rw = create_engine(base.set(database=name, username="agent_rw", password="test-rw"))

    yield owner, ro, rw

    for e in (owner, ro, rw):
        e.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


def denied(engine, sql: str) -> bool:
    """権限がなくて、拒否されたか。"""
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
    except DBAPIError as e:
        # 所有者でない者のDROPは「must be owner」、それ以外は「permission denied」/ 読み取り専用のトランザクション
        return any(m in str(e) for m in ("permission denied", "must be owner", "read-only transaction"))
    return False


def test_read_role_can_only_read_business_tables(priv_db):
    _, ro, _ = priv_db
    with ro.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM orders")).scalar_one() == 300
        assert conn.execute(text("SHOW default_transaction_read_only")).scalar_one() == "on"
        assert conn.execute(text("SHOW statement_timeout")).scalar_one() == "10s"

    assert denied(ro, "INSERT INTO customers VALUES ('C999', 'x', 'y')")
    assert denied(ro, "DELETE FROM orders")
    assert denied(ro, "CREATE TABLE evil (id INT)")
    assert denied(ro, "SELECT * FROM review_requests")  # 書き込み先のTableは、見えない
    assert denied(ro, "DROP TABLE orders")


def test_read_role_cannot_switch_off_read_only_to_write(priv_db):
    """接続の設定(default_transaction_read_only)を、自分で外しても、権限がないので書けない。"""
    _, ro, _ = priv_db
    with ro.connect() as conn:
        conn.execute(text("SET default_transaction_read_only = off"))
        conn.commit()  # 次のトランザクションからは、読み取り専用ではなくなる
        assert conn.execute(text("SHOW transaction_read_only")).scalar_one() == "off"
        with pytest.raises(DBAPIError, match="permission denied"):  # それでも、権限がないので消せない
            conn.execute(text("DELETE FROM orders"))


def test_write_role_can_only_insert_review_requests(priv_db):
    _, _, rw = priv_db
    with rw.begin() as conn:
        conn.execute(text("INSERT INTO review_requests (order_id, reason) VALUES ('O0001', 'x')"))

    assert denied(rw, "UPDATE orders SET sales_amount = 0")      # 売上は、書き換えられない
    assert denied(rw, "DELETE FROM review_requests")             # 登録したものを、消せない
    assert denied(rw, "TRUNCATE review_requests")
    assert denied(rw, "DROP TABLE review_requests")
    with rw.connect() as conn:  # 拒否されただけでなく、Tableが残っている
        assert conn.execute(text("SELECT COUNT(*) FROM review_requests")).scalar_one() >= 1
    assert denied(rw, "CREATE TABLE evil (id INT)")
    assert denied(rw, "INSERT INTO customers VALUES ('C999', 'x', 'y')")


def test_repository_works_with_the_restricted_roles(priv_db):
    """Repositoryの全機能が、制限された役割だけで動く(スキーマの取得を含む)。"""
    _, ro, rw = priv_db
    repo = SqlSalesRepository(ro, rw)

    repo.ping()
    assert repo.sales_summary().order_count == 300
    assert repo.sales_by_dimension("category")
    assert repo.review_orders(3)
    assert [c.name for c in repo.table_columns("customers")] == ["customer_id", "customer_name", "customer_type"]
    assert repo.join_counts("orders", "products").left_duplicate_keys == 12
    assert repo.preview_join("orders", "customers", 2)
    assert repo.register_review_request("O0002", "確認") is RegisterResult.REGISTERED
    assert repo.register_review_request("O0002", "確認") is RegisterResult.ALREADY_REGISTERED


def test_read_engine_cannot_register(priv_db):
    """読み取り用の接続しか持たない部品が、登録に使われても、DBが拒否する(アプリの書き間違いへの備え)。"""
    _, ro, _ = priv_db
    with pytest.raises(DBAPIError):
        SqlSalesRepository(ro, ro).register_review_request("O0003", "x")


def test_password_with_special_characters_survives(priv_db):
    """@ / : % を含むパスワードでも、部品から組み立てれば接続できる。"""
    owner, _, _ = priv_db
    tricky = "p@ss/w:rd%40#?'\""
    migrate.run(owner, {"agent_ro": tricky, "agent_rw": "test-rw"})  # 本番と同じ経路(ensure_roles)でパスワードを設定する
    url = make_url(TEST_PG_URL).set(database=owner.url.database, username="agent_ro", password=tricky)
    engine = create_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar_one() == 1
    engine.dispose()
    migrate.run(owner, ROLES)
