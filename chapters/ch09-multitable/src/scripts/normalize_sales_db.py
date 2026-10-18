import sqlite3
from pathlib import Path

import pandas as pd


CSV_PATH = Path("data/raw/ai_agent_practice_sales.csv")
DB_PATH = Path("data/sales.db")

SCHEMA = """
CREATE TABLE customers (
    customer_id    TEXT PRIMARY KEY,
    customer_name  TEXT NOT NULL,
    customer_type  TEXT NOT NULL
);

CREATE TABLE products (
    product_id    TEXT PRIMARY KEY,
    product_name  TEXT NOT NULL,
    category      TEXT NOT NULL
);

CREATE TABLE orders (
    order_id       TEXT PRIMARY KEY,
    order_date     TEXT NOT NULL,
    customer_id    TEXT NOT NULL REFERENCES customers(customer_id),
    product_id     TEXT NOT NULL REFERENCES products(product_id),
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

CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_product_id ON orders(product_id);
CREATE INDEX idx_orders_review_flag ON orders(review_flag);

CREATE TABLE review_requests (
    order_id    TEXT PRIMARY KEY REFERENCES orders(order_id),
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


def unique_by_key(df: pd.DataFrame, key: str, columns: list[str]) -> pd.DataFrame:
    """キーごとに1行へまとめる。同じキーで属性が食い違うなら、取り込まずに失敗する。"""
    result = df[columns].drop_duplicates().sort_values(key)

    conflicts = result[result.duplicated(key, keep=False)]
    if not conflicts.empty:
        raise ValueError(
            f"{key}ごとに属性が一意になりません。\n{conflicts.to_string()}"
        )

    return result


def main() -> None:
    df = pd.read_csv(CSV_PATH)

    customers = unique_by_key(
        df, "customer_id", ["customer_id", "customer_name", "customer_type"]
    )
    products = unique_by_key(
        df, "product_id", ["product_id", "product_name", "category"]
    )
    orders = df.drop(
        columns=["customer_name", "customer_type", "product_name", "category"]
    )

    # 実行のたびに作り直す。review_requests も消えるので、
    # 本番相当のデータがある環境では実行しない(第13章以降で扱う)。
    DB_PATH.unlink(missing_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
        customers.to_sql("customers", conn, if_exists="append", index=False)
        products.to_sql("products", conn, if_exists="append", index=False)
        orders.to_sql("orders", conn, if_exists="append", index=False)

    print(
        f"customers {len(customers)}件 / products {len(products)}件 / "
        f"orders {len(orders)}件を{DB_PATH}へ取り込みました。"
    )


if __name__ == "__main__":
    main()
