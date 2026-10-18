@tool
def get_review_orders(
    limit: int = 10,
) -> str:
    """
    要レビュー注文を最大limit件返す。
    """

    safe_limit = max(
        1,
        min(limit, 50),
    )

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                order_id,
                customer_name,
                product_name,
                total_amount,
                status,
                review_flag
            FROM sales
            WHERE review_flag = '要レビュー'
            ORDER BY total_amount DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()

    if not rows:
        return "要レビュー注文はありません。"

    return "\n".join(
        (
            f'{row["order_id"]} | '
            f'{row["customer_name"]} | '
            f'{row["product_name"]} | '
            f'{int(row["total_amount"]):,}円 | '
            f'{row["status"]}'
        )
        for row in rows
    )
