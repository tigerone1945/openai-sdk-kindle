def count_duplicates(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> int:
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS cnt
        FROM (
            SELECT {column_name}
            FROM {table_name}
            GROUP BY {column_name}
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()

    return int(row["cnt"])
