@tool
def get_sales_by_region() -> str:
    """
    地域別の売上を集計する。
    """

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                region,
                SUM(sales_amount) AS sales
            FROM sales
            GROUP BY region
            ORDER BY sales DESC
            """
        ).fetchall()

    return "\n".join(
        f'{row["region"]}: '
        f'{int(row["sales"]):,}円'
        for row in rows
    )
