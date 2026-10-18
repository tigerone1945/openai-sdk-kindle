@tool
def get_sales_by_product_category() -> str:
    """
    商品カテゴリ別売上を集計する。
    """

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                p.category,
                SUM(o.sales_amount) AS sales
            FROM orders AS o
            JOIN products AS p
              ON o.product_id = p.product_id
            GROUP BY p.category
            ORDER BY sales DESC
            """
        ).fetchall()

    return "\n".join(
        (
            f'{row["category"]}: '
            f'{int(row["sales"]):,}円'
        )
        for row in rows
    )
