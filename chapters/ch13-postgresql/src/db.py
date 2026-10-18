"""接続(Engine)の作り方。設定は環境変数から読む。

パスワードは、接続URLの文字列に埋め込まず、部品(ユーザー・パスワード・ホスト…)から組み立てる。
`@` や `/` を含むパスワードを、URLの書き方の間違いで壊さないため。
"""
import os
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL

from repository import SqlSalesRepository

# 接続プール:同時に持てる接続の数と、待つ時間。
POOL_SETTINGS = dict(
    pool_size=5,         # 常に持つ接続
    max_overflow=5,      # 足りないときに、一時的に増やせる接続
    pool_timeout=5,      # 空きを待つ秒数。超えたら例外(待ち続けない)
    pool_recycle=1800,   # 古い接続を作り直す秒数(途中のネットワーク機器が切る前に)
    pool_pre_ping=True,  # 使う前に生きているか確かめる(DBの再起動後の最初の失敗を防ぐ)
)


# アプリが使う役割の名前。migrations/0002_privileges.sql の GRANT と同じ名前でなければならない
# (食い違いは、tests が検出する)。パスワードだけを、環境変数から受け取る。
ROLE_NAMES = {"ro": "agent_ro", "rw": "agent_rw"}


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"環境変数 {name} が未設定です。")
    return value


def postgres_url(role: str) -> URL:
    """role は "owner"(DDL)・"rw"(書き込み)・"ro"(読み取り)のいずれか。"""
    prefix = f"DB_{role.upper()}"
    # ro / rw の名前は固定。owner(DDLをする管理者)だけは、環境から受け取る(DBの作成時に決まる)。
    username = ROLE_NAMES[role] if role in ROLE_NAMES else require_env(f"{prefix}_USER")
    return URL.create(
        "postgresql+psycopg",
        username=username,
        password=require_env(f"{prefix}_PASSWORD"),
        host=os.environ.get("DB_HOST", "db"),
        port=int(os.environ.get("DB_PORT", "5432")),
        database=require_env("DB_NAME"),
    )


def make_postgres_engine(url: URL, **overrides) -> Engine:
    settings = {**POOL_SETTINGS, **overrides}
    # 接続できない相手を、いつまでも待たない。
    return create_engine(url, connect_args={"connect_timeout": 5}, **settings)


def make_sqlite_engine(path: Path, read_only: bool) -> Engine:
    if read_only:
        return create_engine(f"sqlite:///file:{Path(path).resolve()}?mode=ro&uri=true")
    return create_engine(f"sqlite:///{path}")


def build_repository() -> SqlSalesRepository:
    """DB_BACKEND で、PostgreSQL か SQLite(手元の開発・テスト)かを選ぶ。"""
    backend = os.environ.get("DB_BACKEND", "sqlite")

    if backend == "postgres":
        return SqlSalesRepository(
            read_engine=make_postgres_engine(postgres_url("ro")),
            write_engine=make_postgres_engine(postgres_url("rw")),
        )

    if backend == "sqlite":
        path = Path(os.environ.get("SQLITE_PATH", "data/sales.db"))
        return SqlSalesRepository(
            read_engine=make_sqlite_engine(path, read_only=True),
            write_engine=make_sqlite_engine(path, read_only=False),
        )

    raise RuntimeError(f"DB_BACKEND は postgres か sqlite です: {backend}")
