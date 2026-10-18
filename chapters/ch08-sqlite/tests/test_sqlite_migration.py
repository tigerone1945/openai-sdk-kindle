"""CSV版とSQLite版の同一性、およびDB側の制約を、LLMなしで確認する。

実行(リポジトリのルートから):
    uv run python chapters/ch08-sqlite/src/scripts/import_csv_to_sqlite.py
    uv run --with pytest pytest chapters/ch08-sqlite/tests -q
"""
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

SRC = Path(__file__).parent.parent / "src"

def load_module(name: str, path: Path):
    """章ごとに同名の agent_service.py があるため、一意な名前で読み込む。"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


svc = load_module("ch08_agent_service", SRC / "agent_service.py")
imp = load_module("ch08_import", SRC / "scripts" / "import_csv_to_sqlite.py")

CSV_PATH = Path("data/raw/ai_agent_practice_sales.csv")


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """テストごとに、まっさらなDBと監査ログを使う(テスト間の依存をなくす)。"""
    db = tmp_path / "sales.db"
    monkeypatch.setattr(imp, "DB_PATH", db)
    monkeypatch.setattr(svc, "SALES_DB_PATH", db)
    monkeypatch.setattr(svc, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    imp.main()
    return db


@pytest.fixture
def df():
    return pd.read_csv(CSV_PATH)


def test_summary_matches_csv(df):
    text = svc.sales_summary()
    assert f"総レコード数: {len(df)}" in text
    assert f"売上合計: {int(df['sales_amount'].sum()):,}円" in text
    assert f"キャンセル件数: {int((df['status'] == 'キャンセル').sum())}" in text
    assert f"要レビュー件数: {int((df['review_flag'] == '要レビュー').sum())}" in text


@pytest.mark.parametrize("column,func", [
    ("category", "sales_by_category"),
    ("region", "sales_by_region"),
])
def test_group_by_matches_pandas(df, column, func):
    expected = df.groupby(column)["sales_amount"].sum().sort_values(ascending=False)
    lines = getattr(svc, func)().splitlines()
    assert lines == [f"{k}: {int(v):,}円" for k, v in expected.items()]


def test_review_orders_limit_is_clamped(df):
    assert len(svc.review_orders(1000).splitlines()) <= 50
    assert len(svc.review_orders(-5).splitlines()) == 1


def test_sql_injection_is_just_a_value():
    # order_id に SQL を入れても、値として扱われ、何も壊れない。
    result = svc.register_review_request("O0001'; DROP TABLE sales; --", "x")
    assert "存在しない注文ID" in result
    assert "総レコード数: 300" in svc.sales_summary()


def test_register_then_duplicate_is_rejected():
    assert "登録しました" in svc.register_review_request("O0001", "高額")
    assert "既に登録済み" in svc.register_review_request("O0001", "高額")
    with svc.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM review_requests").fetchone()[0] == 1


def test_unknown_order_is_rejected():
    assert "存在しない注文ID" in svc.register_review_request("O9999", "x")


def test_db_enforces_foreign_key():
    # Tool の検証を迂回しても、DB側の制約が不整合を防ぐ。
    with svc.get_connection() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO review_requests VALUES ('O9999', 'x', 'now')"
            )


def test_missing_db_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "SALES_DB_PATH", tmp_path / "none.db")
    with pytest.raises(FileNotFoundError, match="import_csv_to_sqlite"):
        svc.sales_summary()
