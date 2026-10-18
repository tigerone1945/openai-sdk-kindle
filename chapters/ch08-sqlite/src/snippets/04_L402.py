@tool
def get_sales_by_category() -> str:
    """
    商品カテゴリ別の売上を集計する。
    """

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                category,
                SUM(sales_amount) AS sales
            FROM sales
            GROUP BY category
            ORDER BY sales DESC
            """
        ).fetchall()

    return "\n".join(
        f'{row["category"]}: '
        f'{int(row["sales"]):,}円'
        for row in rows
    )
