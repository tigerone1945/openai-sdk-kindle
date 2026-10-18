"""SQLite(第8〜12章)の業務データを、PostgreSQLへ移す。移した後に、全行を照合する。

使い方(DB_* の環境変数は、migrate.py と同じ。owner の接続を使う):
    python scripts/migrate_sqlite_to_postgres.py path/to/sales.db [--timezone UTC]

- 移行先のTableが空でなければ、何もせずに中止する(黙って混ぜたり、上書きしたりしない)。
- 全部を1つのトランザクションで入れ、全行を照合してから確定する。1つでも食い違えば、全体を取り消す。
- SQLite側のレビュー依頼の登録日時は、タイムゾーンのない文字列。何時として読むかを --timezone で明示する。
"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Engine, text

sys.path.insert(0, str(Path(__file__).parent.parent))
import db  # noqa: E402

# 外部キーの順(親が先)。
TABLES = ["customers", "products", "orders", "review_requests"]


class MigrationVerificationError(Exception):
    pass


def read_sqlite(path: Path) -> dict[str, list[dict]]:
    # 読み取り専用で開く(移行元を、誤って書き換えない)。
    conn = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1")] for t in TABLES}
    finally:
        conn.close()


def to_utc(value: str, zone: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo(zone))


def prepared(data: dict[str, list[dict]], zone: str) -> dict[str, list[dict]]:
    out = {t: [dict(r) for r in rows] for t, rows in data.items()}
    for row in out["review_requests"]:
        row["created_at"] = to_utc(row["created_at"], zone)
    return out


def insert_all(conn: Connection, data: dict[str, list[dict]]) -> None:
    for table in TABLES:
        rows = data[table]
        if not rows:
            continue
        columns = list(rows[0])
        conn.execute(
            text(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(f':{c}' for c in columns)})"),
            rows,
        )


def normalized(value):
    """DBごとに違う型を、比べられる形にそろえる。"""
    if hasattr(value, "isoformat"):
        return value.astimezone(ZoneInfo("UTC")).isoformat() if isinstance(value, datetime) else value.isoformat()
    if value is None or isinstance(value, (str, int)):
        return value
    return round(float(value), 2)


def verify(conn: Connection, data: dict[str, list[dict]]) -> dict[str, int]:
    """移行先の全行を読み直して、移行元と1行ずつ比べる。件数・合計だけの照合より強い。"""
    counts = {}
    for table in TABLES:
        source = data[table]
        key = next(iter(source[0])) if source else "1"
        got = conn.execute(text(f"SELECT * FROM {table} ORDER BY {key}")).mappings().all()

        if len(got) != len(source):
            raise MigrationVerificationError(f"{table}: 件数が違います(移行元 {len(source)} / 移行先 {len(got)})")

        for expected, actual in zip(source, got):
            for column, value in expected.items():
                if normalized(value) != normalized(actual[column]):
                    raise MigrationVerificationError(
                        f"{table}.{column}: 値が違います({expected[next(iter(expected))]}: {value!r} → {actual[column]!r})"
                    )
        counts[table] = len(got)
    return counts


def migrate(engine: Engine, source_path: Path, zone: str = "UTC") -> dict[str, int]:
    data = prepared(read_sqlite(source_path), zone)
    original = read_sqlite(source_path)
    original["review_requests"] = data["review_requests"]  # 登録日時は、変換後の値で照合する

    with engine.begin() as conn:  # 例外が出れば、全体が取り消される
        for table in TABLES:
            if conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() > 0:
                raise RuntimeError(f"移行先の {table} が空ではありません。何もせずに中止します。")

        insert_all(conn, data)
        return verify(conn, original)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sqlite_path", type=Path)
    parser.add_argument("--timezone", default="UTC", help="登録日時(タイムゾーンなし)を、何時として読むか")
    args = parser.parse_args(argv)

    engine = db.make_postgres_engine(db.postgres_url("owner"))
    counts = migrate(engine, args.sqlite_path, args.timezone)
    print("移行して、全行を照合しました:", ", ".join(f"{t} {n}件" for t, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
