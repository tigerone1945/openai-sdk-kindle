@tool
def inspect_table(
    table_name: str,
) -> str:
    """
    指定TableのSchemaを返す。
    """

    allowed = {
        "orders",
        "customers",
        "products",
    }

    if table_name not in allowed:
        return "許可されていないTableです。"

    with get_connection() as conn:
        rows = conn.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()

    return "\n".join(
        (
            f'{row["name"]} | '
            f'{row["type"]}'
        )
        for row in rows
    )
