from pathlib import Path

import pandas as pd

from db import engine


CSV_PATH = Path(
    "data/ai_agent_practice_sales.csv"
)


def main() -> None:
    df = pd.read_csv(CSV_PATH)

    customers = (
        df[
            [
                "customer_id",
                "customer_name",
                "customer_type",
            ]
        ]
        .drop_duplicates()
        .sort_values("customer_id")
    )

    products = (
        df[
            [
                "product_id",
                "product_name",
                "category",
            ]
        ]
        .drop_duplicates()
        .sort_values("product_id")
    )

    orders = df[
        [
            "order_id",
            "order_date",
            "customer_id",
            "product_id",
            "unit_price",
            "quantity",
            "discount_rate",
            "subtotal",
            "total_amount",
            "sales_amount",
            "region",
            "salesperson",
            "status",
            "review_flag",
        ]
    ].copy()

    orders["order_date"] = pd.to_datetime(
        orders["order_date"]
    )

    customers.to_sql(
        "customers",
        engine,
        if_exists="replace",
        index=False,
    )

    products.to_sql(
        "products",
        engine,
        if_exists="replace",
        index=False,
    )

    orders.to_sql(
        "orders",
        engine,
        if_exists="replace",
        index=False,
    )

    print(
        f"{len(orders)}件を"
        "PostgreSQLへ取り込みました。"
    )


if __name__ == "__main__":
    main()
