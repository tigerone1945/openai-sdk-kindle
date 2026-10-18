"""3 Table化・Join Validation・読み取り専用接続を、LLMなしで確認する。

実行(リポジトリのルートから):
    uv run --with pytest pytest chapters/ch09-multitable/tests -q
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


svc = load_module("ch09_agent_service", SRC / "agent_service.py")
norm = load_module("ch09_normalize", SRC / "scripts" / "normalize_sales_db.py")

CSV_PATH = Path("data/raw/ai_agent_practice_sales.csv")


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """テストごとに、まっさらなDBと監査ログを使う。"""
    db = tmp_path / "sales.db"
    monkeypatch.setattr(norm, "DB_PATH", db)
    monkeypatch.setattr(svc, "SALES_DB_PATH", db)
    monkeypatch.setattr(svc, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    norm.main()
    return db


@pytest.fixture
def df():
    return pd.read_csv(CSV_PATH)


def expected_lines(series):
    items = sorted(series.items(), key=lambda kv: (-kv[1], kv[0]))
    return [f"{k}: {int(v):,}円" for k, v in items]


# --- 正規化:情報が失われていない --------------------------------


def test_normalization_keeps_rows_and_total(df):
    summary = svc.sales_summary()
    assert f"総レコード数: {len(df)}" in summary
    assert f"売上合計: {int(df['sales_amount'].sum()):,}円" in summary


def test_join_back_reproduces_original_csv(df, temp_db):
    """3 Tableを結合し直すと、元のCSVの全列が一致する(正規化で何も失っていない)。"""
    with sqlite3.connect(temp_db) as conn:
        joined = pd.read_sql_query(
            """
            SELECT o.order_id, o.order_date, o.customer_id, c.customer_name,
                   c.customer_type, o.product_id, p.product_name, p.category,
                   o.unit_price, o.quantity, o.discount_rate, o.subtotal,
                   o.total_amount, o.sales_amount, o.region, o.salesperson,
                   o.status, o.review_flag
            FROM orders o
            JOIN customers c ON o.customer_id = c.customer_id
            JOIN products p ON o.product_id = p.product_id
            ORDER BY o.order_id
            """,
            conn,
        )
    expected = df.sort_values("order_id").reset_index(drop=True)[list(joined.columns)]
    pd.testing.assert_frame_equal(joined, expected, check_dtype=False)


def test_normalize_fails_when_attributes_conflict():
    df = pd.DataFrame(
        {"customer_id": ["C1", "C1"], "customer_name": ["A", "B"], "customer_type": ["法人", "法人"]}
    )
    with pytest.raises(ValueError, match="customer_id"):
        norm.unique_by_key(df, "customer_id", list(df.columns))


# --- 集計:Interface(出力形式)と結果がCSV版と一致 -------------


@pytest.mark.parametrize("dimension,column", [
    ("category", "category"),
    ("customer_type", "customer_type"),
    ("region", "region"),
])
def test_dimension_matches_pandas(df, dimension, column):
    expected = df.groupby(column)["sales_amount"].sum()
    assert svc.sales_by_dimension(dimension).splitlines() == expected_lines(expected)


def test_unknown_dimension_is_rejected():
    with pytest.raises(ValueError, match="切り口"):
        svc.sales_by_dimension("customer_name; DROP TABLE orders")


def test_review_orders_joins_names(df):
    top = df[df["review_flag"] == "要レビュー"].sort_values(
        ["total_amount", "order_id"], ascending=[False, True]
    ).iloc[0]
    first = svc.review_orders(1)
    assert top["order_id"] in first and top["customer_name"] in first


# --- Join Validation ----------------------------------------


def test_allowed_join_resolves_in_both_directions():
    assert svc.resolve_join("orders", "customers") == ("customer_id", "customer_id")
    assert svc.resolve_join("customers", "orders") == ("customer_id", "customer_id")
    assert svc.suggest_join_text("products", "orders") == "products.product_id = orders.product_id"


def test_unallowed_join_is_rejected():
    assert svc.resolve_join("customers", "products") is None
    assert "ありません" in svc.suggest_join_text("customers", "products")
    assert "許可されていない" in svc.validate_join_text("customers", "products")
    assert "許可されていない" in svc.preview_join_text("customers", "products", 5)


def test_validate_reports_one_to_many_ok():
    check = svc.check_join("orders", "customers")
    assert check.relation == "Many-to-One"
    assert not check.many_to_many
    assert check.left_unmatched_rows == check.right_unmatched_rows == 0
    assert svc.validate_join_text("orders", "customers").endswith("判定: OK")


def test_many_to_many_is_blocked(monkeypatch):
    """orders同士を非ユニークな列で結合する想定。Validationが止め、Previewも実行しない。"""
    monkeypatch.setitem(svc.ALLOWED_JOINS, ("orders", "orders"), ("region", "region"))
    check = svc.check_join("orders", "orders")
    assert check.many_to_many and check.relation == "Many-to-Many"
    assert "NG" in svc.validate_join_text("orders", "orders")
    assert "実行しません" in svc.preview_join_text("orders", "orders", 5)


def test_unmatched_rows_warn(temp_db):
    # 外部キーを無効にした接続で、親のない注文を作る(制約が防ぐ不整合の再現)。
    with sqlite3.connect(temp_db) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("UPDATE orders SET customer_id = 'C999' WHERE order_id = 'O0001'")
    text = svc.validate_join_text("orders", "customers")
    assert "警告(1行" in text


def test_preview_keeps_both_key_columns():
    line = svc.preview_join_text("orders", "customers", 1)
    assert "l_customer_id" in line and "r_customer_id" in line


def test_preview_limit_is_clamped():
    assert len(svc.preview_join_text("orders", "products", 1000).splitlines()) == 20
    assert len(svc.preview_join_text("orders", "products", -3).splitlines()) == 1


# --- Query Safety -------------------------------------------


def test_read_connection_cannot_write():
    with svc.get_connection() as conn:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM orders")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("CREATE TABLE x (a)")


def test_inspect_table_allowlist():
    assert "customer_type" in svc.table_schema("customers")
    assert "許可されていない" in svc.table_schema("sqlite_master")
    assert "許可されていない" in svc.table_schema("orders; DROP TABLE orders")


def test_identifier_allowlist():
    with pytest.raises(ValueError):
        svc.require_table("sqlite_master")


def test_register_review_request_still_works():
    assert "登録しました" in svc.register_review_request("O0001", "高額")
    assert "既に登録済み" in svc.register_review_request("O0001", "高額")
    assert "存在しない" in svc.register_review_request("O9999'; DROP TABLE orders; --", "x")
    assert "総レコード数: 300" in svc.sales_summary()


def test_db_enforces_foreign_keys(temp_db):
    with svc.get_connection(read_only=False) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO review_requests VALUES ('O9999', 'x', 'now')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE orders SET product_id = 'P999' WHERE order_id = 'O0001'")


def test_missing_db_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "SALES_DB_PATH", tmp_path / "none.db")
    with pytest.raises(FileNotFoundError, match="normalize_sales_db"):
        svc.sales_summary()
