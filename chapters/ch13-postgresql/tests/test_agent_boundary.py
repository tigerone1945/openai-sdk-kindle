"""Tool層がSQLを知らないこと、保存先を替えても出力が変わらないことを確認する。"""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

from conftest import M, SRC, TEST_PG_URL, build_sqlite

svc = M.agent_service
Column, JoinCounts, LabeledSales, RegisterResult, ReviewOrder, SalesSummary, SqlSalesRepository = (
    M.repository.Column, M.repository.JoinCounts, M.repository.LabeledSales, M.repository.RegisterResult,
    M.repository.ReviewOrder, M.repository.SalesSummary, M.repository.SqlSalesRepository,
)

CH11_AGENT = SRC.parent.parent / "ch11-fastapi/src/agent_service.py"
TEXT_FUNCTIONS = [
    lambda s: s.sales_summary(),
    lambda s: s.sales_by_dimension("category"),
    lambda s: s.sales_by_dimension("customer_type"),
    lambda s: s.sales_by_dimension("region"),
    lambda s: s.review_orders(5),
    lambda s: s.list_business_tables(),
    lambda s: s.suggest_join_text("orders", "customers"),
    lambda s: s.validate_join_text("orders", "customers"),
    lambda s: s.validate_join_text("customers", "products"),
    lambda s: s.preview_join_text("orders", "products", 3),
    lambda s: s.preview_join_text("customers", "products", 3),
]


class FakeRepository:
    """DBなしでToolの振る舞いを確認するための、偽のRepository(Repositoryを挟んだ効果)。"""

    def __init__(self, join_counts=JoinCounts(10, 0, 0, 0)):
        self.calls = []
        self._join_counts = join_counts

    def sales_summary(self): return SalesSummary(300, 28_298_695, 14, 37)
    def sales_by_dimension(self, d): self.calls.append(("dim", d)); return [LabeledSales("A", 700), LabeledSales("B", 300)]
    def review_orders(self, limit): self.calls.append(("review", limit)); return [ReviewOrder("O1", "顧客", "商品", 1_000_000, "完了")]
    def register_review_request(self, o, r): return {"O1": RegisterResult.REGISTERED, "O2": RegisterResult.ALREADY_REGISTERED}.get(o, RegisterResult.UNKNOWN_ORDER)
    def table_columns(self, t): return [Column("a", "TEXT")]
    def join_counts(self, left, right): return self._join_counts
    def preview_join(self, left, right, limit): self.calls.append(("preview", limit)); return [{"k": 1}]
    def ping(self): pass


@pytest.fixture(autouse=True)
def reset_repository():
    yield
    svc.set_repository(None)


def test_tool_layer_contains_no_sql():
    """SQLを知っているのはRepositoryだけ。agent_service.py にSQLの文もDBドライバもない。"""
    source = SRC.joinpath("agent_service.py").read_text(encoding="utf-8")
    assert not re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|PRAGMA)\b", source)
    assert "sqlite3" not in source and "sqlalchemy" not in source and "psycopg" not in source


def test_totals_and_formatting_come_from_the_tool_layer():
    svc.set_repository(FakeRepository())
    assert svc.sales_by_dimension("category").splitlines() == ["A: 700円", "B: 300円", "合計: 1,000円"]
    assert svc.sales_summary().splitlines()[1] == "売上合計: 28,298,695円"


@pytest.mark.parametrize("requested,expected", [(1000, 50), (-5, 1), (7, 7)])
def test_review_limit_is_clamped_before_reaching_the_repository(requested, expected):
    repo = FakeRepository()
    svc.set_repository(repo)
    svc.review_orders(requested)
    assert ("review", expected) in repo.calls


def test_preview_limit_is_clamped_and_many_to_many_is_blocked():
    repo = FakeRepository()
    svc.set_repository(repo)
    svc.preview_join_text("orders", "customers", 999)
    assert ("preview", 20) in repo.calls

    blocked = FakeRepository(join_counts=JoinCounts(3, 3, 0, 0))
    svc.set_repository(blocked)
    assert "実行しません" in svc.preview_join_text("orders", "customers", 5)
    assert blocked.calls == []  # Many-to-Manyなら、Repositoryのpreviewを呼ばない


def test_register_messages():
    svc.set_repository(FakeRepository())
    assert "登録しました" in svc.register_review_request("O1", "x")
    assert "既に登録済み" in svc.register_review_request("O2", "x")
    assert "存在しない注文ID" in svc.register_review_request("O3", "x")


def test_refactoring_did_not_change_any_tool_output(tmp_path):
    """第11章(リファクタ前。SQLをToolが直接持っていた版)と、同じDBで、同じ出力を返す。"""
    repo, db_path = build_sqlite(tmp_path)
    svc.set_repository(repo)

    spec = importlib.util.spec_from_file_location("ch11_agent_for_regression", CH11_AGENT)
    old = importlib.util.module_from_spec(spec)
    sys.modules["ch11_agent_for_regression"] = old
    spec.loader.exec_module(old)
    old.SALES_DB_PATH = db_path

    for fn in TEXT_FUNCTIONS:
        new_out, old_out = fn(svc), fn(old)
        # SQLiteの型名の表記だけは、SQLAlchemy経由で変わりうるので、先頭の列名だけ比べる(下のテスト)
        assert new_out == old_out


@pytest.mark.skipif(not TEST_PG_URL, reason="TEST_PG_URL が未設定のため、PostgreSQLとの比較は実行しません")
def test_sqlite_and_postgres_return_identical_tool_output(tmp_path, pg_schema):
    sqlite_repo, _ = build_sqlite(tmp_path)
    engine, _, _ = pg_schema
    pg_repo = SqlSalesRepository(engine, engine)

    for fn in TEXT_FUNCTIONS:
        svc.set_repository(sqlite_repo)
        from_sqlite = fn(svc)
        svc.set_repository(pg_repo)
        from_postgres = fn(svc)
        assert from_postgres == from_sqlite
