@tool
def get_sales_by_customer_type() -> str:
    """
    顧客種別別の売上を集計する。
    """

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                c.customer_type,
                SUM(o.sales_amount) AS sales
            FROM orders AS o
            JOIN customers AS c
              ON o.customer_id = c.customer_id
            GROUP BY c.customer_type
            ORDER BY sales DESC
            """
        ).fetchall()

    return "\n".join(
        (
            f'{row["customer_type"]}: '
            f'{int(row["sales"]):,}円'
        )
        for row in rows
    )
