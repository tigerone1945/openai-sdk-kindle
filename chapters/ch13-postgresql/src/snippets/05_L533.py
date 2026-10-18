from agents.decorators import tool

from repository import (
    fetch_sales_by_customer_type,
    fetch_sales_by_region,
    fetch_sales_summary,
)


@tool
def get_sales_summary() -> str:
    """
    売上全体の基本集計を返す。
    """

    row = fetch_sales_summary()

    return f"""
総レコード数: {row["order_count"]}
売上合計: {int(row["total_sales"]):,}円
キャンセル件数: {row["cancelled_count"]}
要レビュー件数: {row["review_count"]}
""".strip()
