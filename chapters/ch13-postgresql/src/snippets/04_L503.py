def fetch_sales_by_customer_type() -> list[dict]:
    sql = text(
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
    )

    with engine.connect() as conn:
        rows = conn.execute(
            sql
        ).mappings().all()

    return [
        dict(row)
        for row in rows
    ]
