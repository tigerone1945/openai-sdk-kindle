"""決定的な計算(合計)がToolの側にあることを、LLMなしで確認する。

第10章のData Accessとの違いは、集計の出力に「合計」の行が加わった点だけ。
"""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(SRC))

import agent_service as svc  # noqa: E402

NORMALIZE = SRC.parent.parent / "ch09-multitable" / "src" / "scripts" / "normalize_sales_db.py"
NUM = re.compile(r"\d{1,3}(?:,\d{3})+")


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ch09_normalize_for_ch11", NORMALIZE)
    norm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(norm)

    db = tmp_path / "sales.db"
    monkeypatch.setattr(norm, "DB_PATH", db)
    monkeypatch.setattr(svc, "SALES_DB_PATH", db)
    norm.main()


def as_int(text: str) -> int:
    return int(text.replace(",", ""))


@pytest.mark.parametrize("dimension", ["category", "region", "customer_type"])
def test_total_line_equals_overall_sales(dimension):
    *rows, total = svc.sales_by_dimension(dimension).splitlines()

    assert total.startswith("合計: ")
    assert as_int(NUM.findall(total)[0]) == sum(as_int(NUM.findall(r)[0]) for r in rows)

    overall = NUM.findall(svc.sales_summary().splitlines()[1])[0]
    assert as_int(NUM.findall(total)[0]) == as_int(overall)  # 切り口が違っても合計は同じ
