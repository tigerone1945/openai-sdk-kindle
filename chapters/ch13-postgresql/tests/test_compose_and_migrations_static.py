"""第13章のコンテナ構成を、Dockerなし・DBなしで検査する。重点は、権限と秘密の分離。"""
import json
import re
import tomllib
from pathlib import Path

import pytest
import yaml

from conftest import M, ROOT, SRC

COMPOSE = yaml.safe_load((SRC / "compose.yaml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]
DOCKERFILE = SRC / "Dockerfile.api"
OWNER_VARS = {"DB_OWNER_USER", "DB_OWNER_PASSWORD"}


def instructions(path: Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8").replace("\\\n", " ")
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, _, rest = line.partition(" ")
            out.append((name.upper(), rest.strip()))
    return out


def env_of(service: str) -> dict:
    return SERVICES[service].get("environment") or {}


# --- 権限と秘密の分離 --------------------------------------------


def test_only_the_migration_job_holds_the_owner_credentials():
    """DDL(Tableの作成・削除)ができる管理者の資格情報は、migrate だけ。apiが破られても、スキーマは壊せない。"""
    for name in ("api", "ui"):
        assert not (set(env_of(name)) & OWNER_VARS), name
    assert OWNER_VARS <= set(env_of("migrate"))


def test_api_gets_only_the_restricted_roles():
    env = env_of("api")
    assert {"DB_RO_PASSWORD", "DB_RW_PASSWORD"} <= set(env)
    assert env["DB_BACKEND"] == "postgres"


def test_ui_knows_nothing_about_the_database_or_the_model_key():
    env = env_of("ui")
    assert set(env) == {"API_URL"}


def test_passwords_are_required_and_never_literal():
    text = (SRC / "compose.yaml").read_text(encoding="utf-8")
    assert "${DB_OWNER_PASSWORD:?" in text and "${DB_RO_PASSWORD:?" in text and "${DB_RW_PASSWORD:?" in text
    # 秘密らしい名前の環境変数は、すべて「${...}」(実行時に外から渡す)。値が直接書かれていない。
    for service, definition in SERVICES.items():
        for name, value in (definition.get("environment") or {}).items():
            if re.search(r"(PASSWORD|KEY|SECRET|TOKEN)", name):
                assert str(value).startswith("${"), f"{service}.{name}"


def test_database_port_is_not_published():
    assert "ports" not in SERVICES["db"]
    for name in ("api", "ui"):
        assert all(p.startswith("127.0.0.1:") for p in SERVICES[name]["ports"])


def test_database_image_is_pinned_by_digest():
    assert re.search(r"@sha256:[0-9a-f]{64}$", SERVICES["db"]["image"])


def test_state_lives_in_two_named_volumes_with_clear_owners():
    assert set(COMPOSE["volumes"]) == {"pg-data", "app-data"}
    assert SERVICES["db"]["volumes"] == ["pg-data:/var/lib/postgresql/data"]
    assert SERVICES["api"]["volumes"] == ["app-data:/app/data"]
    assert "volumes" not in SERVICES["migrate"] and "volumes" not in SERVICES["ui"]


def test_startup_order_db_then_migration_then_api_then_ui():
    assert SERVICES["migrate"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert SERVICES["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert SERVICES["ui"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert SERVICES["migrate"]["restart"] == "no"
    assert "pg_isready" in SERVICES["db"]["healthcheck"]["test"][-1]


def test_api_health_means_the_database_is_reachable():
    """apiのhealthcheckは /ready(DBまで確かめる)。uiは、DBが使えるapiを待つ。"""
    assert "/ready" in SERVICES["api"]["healthcheck"]["test"][-1]


@pytest.mark.parametrize("name", ["migrate", "api", "ui"])
def test_app_containers_are_hardened(name):
    s = SERVICES[name]
    assert s["read_only"] is True and s["cap_drop"] == ["ALL"] and "no-new-privileges:true" in s["security_opt"]


def test_database_container_keeps_only_the_capabilities_it_needs():
    s = SERVICES["db"]
    assert s["cap_drop"] == ["ALL"] and set(s["cap_add"]) == {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"}
    assert s["read_only"] is True


# --- Dockerfile ----------------------------------------------------


def test_dockerfile_basics():
    steps = instructions(DOCKERFILE)
    cmds = [a for n, a in steps if n == "CMD"]
    assert len(cmds) == 1 and isinstance(json.loads(cmds[0]), list)
    assert [a for n, a in steps if n == "USER"][-1] not in {"root", "0"}
    assert all(re.search(r"@sha256:[0-9a-f]{64}$", a) for n, a in steps if n == "FROM")
    sync = next(a for n, a in steps if n == "RUN" and "uv sync" in a)
    assert "--locked" in sync and "--only-group api" in sync
    for name, arg in steps:
        if name in {"ENV", "ARG"}:
            assert not re.search(r"(KEY|SECRET|TOKEN|PASSWORD)", arg, re.IGNORECASE), arg


def test_every_copied_file_is_allowlisted_and_exists():
    ignore = DOCKERFILE.with_name("Dockerfile.api.dockerignore").read_text(encoding="utf-8").splitlines()
    assert ignore[0] == "*"
    allowed = [l[1:] for l in ignore if l.startswith("!")]
    for entry in allowed:
        assert (ROOT / entry).exists(), entry
        assert ".env" not in entry and ".db" not in entry
    for name, arg in instructions(DOCKERFILE):
        if name == "COPY":
            for src in [p for p in arg.split()[:-1] if not p.startswith("--")]:
                covered = any(src == a or src.rstrip("/") == a.rstrip("/") or src.startswith(a.rstrip("/") + "/") for a in allowed)
                assert covered or src in {"pyproject.toml", "uv.lock"}, src
                assert (ROOT / src).exists(), src


def test_api_dependency_group_has_the_database_drivers():
    groups = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["dependency-groups"]
    names = {re.split(r"[\[>=<~! ]", r, maxsplit=1)[0].lower() for r in groups["api"]}
    assert {"sqlalchemy", "psycopg"} <= names
    assert {"sqlalchemy", "psycopg"}.isdisjoint({re.split(r"[\[>=<~! ]", r, maxsplit=1)[0].lower() for r in groups["ui"]})


# --- マイグレーション --------------------------------------------


MIGRATIONS = sorted((SRC / "migrations").glob("*.sql"))


def test_migration_files_are_numbered_without_gaps():
    numbers = [int(p.name[:4]) for p in MIGRATIONS]
    assert numbers == list(range(1, len(numbers) + 1))


def test_no_secret_is_written_in_sql():
    """役割のパスワードは、SQLファイルではなく、migrate.py が環境変数から設定する。"""
    for path in MIGRATIONS:
        assert not re.search(r"\bPASSWORD\b", path.read_text(encoding="utf-8"), re.IGNORECASE), path.name


def test_every_created_table_has_a_primary_key():
    sql = (SRC / "migrations/0001_schema.sql").read_text(encoding="utf-8")
    for block in re.findall(r"CREATE TABLE (\w+) \((.*?)\n\);", sql, re.S):
        assert "PRIMARY KEY" in block[1], block[0]


def test_schema_columns_match_the_sqlite_schema_names():
    """PostgreSQLのスキーマと、SQLite版(第9章)が、同じ列名を持つ(Repositoryが両方で動くための前提)。"""
    sql = (SRC / "migrations/0001_schema.sql").read_text(encoding="utf-8")
    postgres_orders = re.search(r"CREATE TABLE orders \((.*?)\n\);", sql, re.S).group(1)
    columns = [l.split()[0] for l in postgres_orders.strip().splitlines() if l.strip() and not l.strip().startswith(("--", "CHECK", "PRIMARY", "FOREIGN"))]
    sqlite_sql = (ROOT / "chapters/ch09-multitable/src/scripts/normalize_sales_db.py").read_text(encoding="utf-8")
    sqlite_orders = re.search(r"CREATE TABLE orders \((.*?)\n\);", sqlite_sql, re.S).group(1)
    sqlite_columns = [l.split()[0] for l in sqlite_orders.strip().splitlines() if l.strip()]
    assert columns == sqlite_columns
