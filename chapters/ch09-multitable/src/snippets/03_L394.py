from agents.decorators import tool


@tool
def list_tables() -> str:
    """
    利用可能な業務Table一覧を返す。
    """

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN (
                'orders',
                'customers',
                'products'
              )
            ORDER BY name
            """
        ).fetchall()

    return "\n".join(
        row["name"]
        for row in rows
    )
