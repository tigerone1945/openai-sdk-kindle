def fetch_sales_by_region() -> list[dict]:
    sql = text(
        """
        SELECT
            region,
            SUM(sales_amount) AS sales
        FROM orders
        GROUP BY region
        ORDER BY sales DESC
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(
            sql
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]
