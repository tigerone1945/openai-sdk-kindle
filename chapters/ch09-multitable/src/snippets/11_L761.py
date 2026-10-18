def resolve_join(
    left_table: str,
    right_table: str,
) -> tuple[str, str] | None:

    direct = (
        left_table,
        right_table,
    )

    reverse = (
        right_table,
        left_table,
    )

    if direct in ALLOWED_JOINS:
        return ALLOWED_JOINS[direct]

    if reverse in ALLOWED_JOINS:
        right_key, left_key = (
            ALLOWED_JOINS[reverse]
        )
        return (
            left_key,
            right_key,
        )

    return None
