@tool
def suggest_join(
    left_table: str,
    right_table: str,
) -> str:
    """
    2つのTable間で許可されたJoin Keyを返す。
    """

    key = (
        left_table,
        right_table,
    )

    reverse_key = (
        right_table,
        left_table,
    )

    if key in ALLOWED_JOINS:
        left_key, right_key = (
            ALLOWED_JOINS[key]
        )

        return (
            f"{left_table}.{left_key} = "
            f"{right_table}.{right_key}"
        )

    if reverse_key in ALLOWED_JOINS:
        right_key, left_key = (
            ALLOWED_JOINS[reverse_key]
        )

        return (
            f"{left_table}.{left_key} = "
            f"{right_table}.{right_key}"
        )

    return "許可されたJoinはありません。"
