@tool
def preview_join(
    left_table: str,
    right_table: str,
    limit: int = 5,
) -> str:
    """
    許可されたJoinのPreviewを返す。
    """

    relation = resolve_join(
        left_table,
        right_table,
    )

    if relation is None:
        return "許可されていないJoinです。"

    left_key, right_key = relation

    safe_limit = max(
        1,
        min(limit, 20),
    )

    sql = f"""
    SELECT *
    FROM {left_table} AS l
    JOIN {right_table} AS r
      ON l.{left_key} = r.{right_key}
    LIMIT ?
    """

    with get_connection() as conn:
        rows = conn.execute(
            sql,
            (safe_limit,),
        ).fetchall()

    if not rows:
        return "Join結果は0件です。"

    return "\n".join(
        str(dict(row))
        for row in rows
    )
