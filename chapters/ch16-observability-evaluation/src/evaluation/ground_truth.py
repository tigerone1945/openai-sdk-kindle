"""正解データ: CSV から、Agent とは独立に計算する(Agent の Tool・DB を通らない)。

売上の定義は、本書の Tool と同じ: sales_amount の合計(キャンセルは 0 円として入っている)。
"""
from functools import lru_cache
from itertools import combinations
from pathlib import Path

import pandas as pd

CSV = Path(__file__).resolve().parents[4] / "data/raw/ai_agent_practice_sales.csv"


@lru_cache(maxsize=1)
def _frame() -> pd.DataFrame:
    return pd.read_csv(CSV, encoding="utf-8-sig")


def _sum_by(column: str) -> dict[str, int]:
    return {k: int(v) for k, v in _frame().groupby(column).sales_amount.sum().items()}


def truth() -> dict:
    df = _frame()
    return {
        "total": int(df.sales_amount.sum()),
        "cancelled_count": int((df.status == "キャンセル").sum()),
        "order_count": int(len(df)),
        "region": _sum_by("region"),
        "category": _sum_by("category"),
        "customer_type": _sum_by("customer_type"),
    }


def allowed_amounts(entities: dict[str, int], total: int) -> set[int]:
    """その切り口の数値として、見てよい金額: 各項目の値、合計、2 項目の差・和。

    Agent が「差」や「合計」を言うのは正当(ただし、その計算が正しいことは、ここで確かめる)。
    """
    values = list(entities.values())
    derived = {abs(a - b) for a, b in combinations(values, 2)} | {a + b for a, b in combinations(values, 2)}
    return set(values) | {total} | derived
