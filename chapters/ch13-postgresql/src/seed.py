"""デモ用の売上データを入れる(本番では実行しない。SEED_DEMO_DATA=true のときだけ)。"""
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, text

ORDER_COLUMNS = [
    "order_id", "order_date", "customer_id", "product_id", "unit_price", "quantity",
    "discount_rate", "subtotal", "total_amount", "sales_amount", "region",
    "salesperson", "status", "review_flag",
]


def python_values(frame: pd.DataFrame) -> list[dict]:
    """numpyの型を、Pythonの素朴な型にして、DBドライバに渡す。"""
    return [
        {k: (v.item() if hasattr(v, "item") else v) for k, v in row.items()}
        for row in frame.to_dict("records")
    ]


def seed_demo_data(engine: Engine, csv_path: Path) -> str:
    """Tableが空のときだけ入れる。データがあれば、何もしない。"""
    df = pd.read_csv(csv_path)

    with engine.begin() as conn:
        if conn.execute(text("SELECT COUNT(*) FROM orders")).scalar_one() > 0:
            return "orders にデータがあるため、デモデータは入れません。"

        # 属性が食い違うキーがあれば、主キー違反で失敗する(黙って上書きしない)。
        customers = df[["customer_id", "customer_name", "customer_type"]].drop_duplicates()
        products = df[["product_id", "product_name", "category"]].drop_duplicates()

        conn.execute(text("INSERT INTO customers VALUES (:customer_id, :customer_name, :customer_type)"), python_values(customers))
        conn.execute(text("INSERT INTO products VALUES (:product_id, :product_name, :category)"), python_values(products))
        placeholders = ", ".join(f":{c}" for c in ORDER_COLUMNS)
        conn.execute(text(f"INSERT INTO orders ({', '.join(ORDER_COLUMNS)}) VALUES ({placeholders})"), python_values(df[ORDER_COLUMNS]))

    return f"デモデータを入れました(customers {len(customers)} / products {len(products)} / orders {len(df)})。"
