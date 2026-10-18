@tool
def get_sales_summary() -> str:
    """
    売上データ全体の基本集計を返す。
    """

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS order_count,
                SUM(sales_amount) AS total_sales,
                SUM(
                    CASE
                        WHEN status = 'キャンセル'
                        THEN 1
                        ELSE 0
                    END
                ) AS cancelled_count,
                SUM(
                    CASE
                        WHEN review_flag = '要レビュー'
                        THEN 1
                        ELSE 0
                    END
                ) AS review_count
            FROM sales
            """
        ).fetchone()

    return f"""
総レコード数: {row["order_count"]}
売上合計: {int(row["total_sales"]):,}円
キャンセル件数: {row["cancelled_count"]}
要レビュー件数: {row["review_count"]}
""".strip()
