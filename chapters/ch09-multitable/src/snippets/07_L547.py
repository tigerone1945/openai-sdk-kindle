@tool
def validate_join(
    left_table: str,
    right_table: str,
) -> str:
    """
    許可されたJoinについて、
    Keyの重複状態を検証する。
    """

    relation = resolve_join(
        left_table,
        right_table,
    )

    if relation is None:
        return "許可されていないJoinです。"

    left_key, right_key = relation

    with get_connection() as conn:
        left_dup = count_duplicates(
            conn,
            left_table,
            left_key,
        )

        right_dup = count_duplicates(
            conn,
            right_table,
            right_key,
        )

    return (
        f"{left_table}.{left_key} "
        f"重複Key数: {left_dup}\n"
        f"{right_table}.{right_key} "
        f"重複Key数: {right_dup}"
    )
