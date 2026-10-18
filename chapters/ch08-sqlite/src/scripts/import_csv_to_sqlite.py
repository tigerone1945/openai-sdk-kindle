import sqlite3
from pathlib import Path

import pandas as pd


CSV_PATH = Path("data/raw/ai_agent_practice_sales.csv")
DB_PATH = Path("data/sales.db")

# to_sql() に型と制約を任せず、スキーマを明示する。
SCHEMA = """
CREATE TABLE sales (
    order_id       TEXT PRIMARY KEY,
    order_date     TEXT NOT NULL,
    customer_id    TEXT NOT NULL,
    customer_name  TEXT NOT NULL,
    customer_type  TEXT NOT NULL,
    product_id     TEXT NOT NULL,
    product_name   TEXT NOT NULL,
    category       TEXT NOT NULL,
    unit_price     INTEGER NOT NULL,
    quantity       INTEGER NOT NULL CHECK (quantity > 0),
    discount_rate  REAL NOT NULL CHECK (discount_rate BETWEEN 0 AND 1),
    subtotal       INTEGER NOT NULL,
    total_amount   INTEGER NOT NULL,
    sales_amount   INTEGER NOT NULL,
    region         TEXT NOT NULL,
    salesperson    TEXT NOT NULL,
    status         TEXT NOT NULL,
    review_flag    TEXT NOT NULL
);

CREATE INDEX idx_sales_category ON sales(category);
CREATE INDEX idx_sales_region ON sales(region);
CREATE INDEX idx_sales_review_flag ON sales(review_flag);

CREATE TABLE review_requests (
    order_id    TEXT PRIMARY KEY REFERENCES sales(order_id),
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


def main() -> None:
    # pandas は BOM 付き UTF-8 を自動で処理する。
    df = pd.read_csv(CSV_PATH)

    # 実行のたびに作り直す。review_requests も消えるので、
    # 本番相当のデータがある環境では実行しない(第13章以降で扱う)。
    DB_PATH.unlink(missing_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        df.to_sql("sales", conn, if_exists="append", index=False)

    print(f"{len(df)}件を{DB_PATH}へ取り込みました。")


if __name__ == "__main__":
    main()
