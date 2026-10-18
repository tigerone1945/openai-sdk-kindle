"""スキーマの変更を、順番に・一度だけ・競合せずに適用する。第12章の init_db.py の置き換え。

- 適用済みの版は schema_migrations に記録する。適用済みのファイルを後から書き換えたら、失敗する。
- PostgreSQLは、DDL(Tableの作成)もトランザクションに入る。途中で失敗したら、全部なかったことになる。
- 同時に2つ起動しても(2つのコンテナなど)、アドバイザリロックで順番に実行する。
"""
import hashlib
import sys
from pathlib import Path

from psycopg import sql
from sqlalchemy import Engine, text

import db

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
ADVISORY_LOCK_KEY = 7243901  # このアプリのマイグレーション専用の任意の数


class MigrationError(Exception):
    pass


def ensure_roles(conn, roles: dict[str, str]) -> None:
    """アプリが使う役割を、作る(無ければ)。パスワードは、実行のたびに環境変数の値へそろえる(更新できる)。"""
    cursor = conn.connection.cursor()  # SQLAlchemyの接続の下の、psycopgの接続
    for name, password in roles.items():
        exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :n"), {"n": name}).first()
        verb = "ALTER" if exists else "CREATE"
        cursor.execute(
            sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(name), sql.Literal(password))
        )


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(engine: Engine, roles: dict[str, str], directory: Path | None = None) -> list[str]:
    """適用した版の一覧を返す。"""
    files = sorted((directory or MIGRATIONS_DIR).glob("[0-9][0-9][0-9][0-9]_*.sql"))
    applied_now = []

    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADVISORY_LOCK_KEY})
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        ))
        recorded = dict(conn.execute(text("SELECT version, checksum FROM schema_migrations")).all())

        ensure_roles(conn, roles)

        for path in files:
            version = path.stem
            if version in recorded:
                if recorded[version] != checksum(path):
                    raise MigrationError(f"適用済みの {path.name} が書き換えられています。新しい版を足してください。")
                continue

            conn.exec_driver_sql(path.read_text(encoding="utf-8"))
            conn.execute(
                text("INSERT INTO schema_migrations (version, checksum) VALUES (:v, :c)"),
                {"v": version, "c": checksum(path)},
            )
            applied_now.append(version)

    return applied_now


def main() -> int:
    engine = db.make_postgres_engine(db.postgres_url("owner"))
    roles = {
        db.ROLE_NAMES["ro"]: db.require_env("DB_RO_PASSWORD"),
        db.ROLE_NAMES["rw"]: db.require_env("DB_RW_PASSWORD"),
    }

    applied = run(engine, roles)
    print("適用した版:", ", ".join(applied) if applied else "なし(最新です)")

    if db.os.environ.get("SEED_DEMO_DATA") == "true":
        import seed

        print(seed.seed_demo_data(engine, Path(db.os.environ.get("SEED_CSV_PATH", "/app/seed/ai_agent_practice_sales.csv"))))

    return 0


if __name__ == "__main__":
    sys.exit(main())
