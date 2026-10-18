"""コンテナの設定を、Dockerなし・LLMなしで検査する(ビルドの失敗や設定の事故を、ビルド前に見つける)。

実行(リポジトリのルートから):
    uv run --with pytest pytest chapters/ch12-docker/tests -q
Dockerを使う検証(ビルド・起動・永続性・秘密の混入)は、chapters/ch12-docker/README.md の手順で行う。
"""
import importlib.util
import json
import re
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

CHAPTER = Path(__file__).parent.parent
SRC = CHAPTER / "src"
ROOT = CHAPTER.parent.parent

DOCKERFILES = [SRC / "Dockerfile.api", SRC / "Dockerfile.ui"]
SECRET_WORDS = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD)", re.IGNORECASE)


def instructions(dockerfile: Path) -> list[tuple[str, str]]:
    """行の継続(\\)をつなげて、(命令, 引数)の一覧にする。"""
    text = dockerfile.read_text(encoding="utf-8").replace("\\\n", " ")
    result = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, _, rest = line.partition(" ")
            result.append((name.upper(), rest.strip()))
    return result


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load((SRC / "compose.yaml").read_text(encoding="utf-8"))


# --- Dockerfile ---------------------------------------------------


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.name)
def test_cmd_is_single_line_exec_form(dockerfile):
    """複数行のCMDは構文エラーになる(Zenn版)。exec形式なら、シグナルがアプリへ直接届く。"""
    cmds = [arg for name, arg in instructions(dockerfile) if name == "CMD"]
    assert len(cmds) == 1
    assert isinstance(json.loads(cmds[0]), list)


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.name)
def test_runs_as_non_root(dockerfile):
    users = [arg for name, arg in instructions(dockerfile) if name == "USER"]
    assert users and users[-1] not in {"root", "0"}


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.name)
def test_base_image_is_pinned_by_digest(dockerfile):
    base = [arg for name, arg in instructions(dockerfile) if name == "FROM"]
    assert all(re.search(r"@sha256:[0-9a-f]{64}$", b) for b in base)


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.name)
def test_no_secret_in_env_or_arg(dockerfile):
    for name, arg in instructions(dockerfile):
        if name in {"ENV", "ARG"}:
            assert not SECRET_WORDS.search(arg), f"{name} {arg}"


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.name)
def test_dependencies_are_installed_before_app_code(dockerfile):
    """依存(変わりにくい)を先に入れ、コードだけの変更でキャッシュが効くようにする。"""
    steps = instructions(dockerfile)
    sync = next(i for i, (n, a) in enumerate(steps) if n == "RUN" and "uv sync" in a)
    app_copies = [i for i, (n, a) in enumerate(steps) if n == "COPY" and "chapters/" in a]
    assert app_copies and all(sync < i for i in app_copies)


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.name)
def test_uses_locked_lockfile_without_dev(dockerfile):
    """--frozen は、ロックの更新漏れ(pyproject.toml に足した依存が入らない)に気づかず通る。--locked は失敗する。"""
    sync = next(a for n, a in instructions(dockerfile) if n == "RUN" and "uv sync" in a)
    assert "--locked" in sync and "--frozen" not in sync
    assert "--no-dev" in sync and "--only-group" in sync


# --- .dockerignore(許可リスト)------------------------------------


def allowlist(dockerfile: Path) -> list[str]:
    ignore = dockerfile.with_name(dockerfile.name + ".dockerignore")
    lines = [l.strip() for l in ignore.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines[0] == "*", "何も入れない(*)ところから、許可する方式にする"
    return [l[1:] for l in lines if l.startswith("!")]


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.name)
def test_allowlisted_paths_exist(dockerfile):
    for entry in allowlist(dockerfile):
        assert (ROOT / entry).exists(), entry


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.name)
def test_secrets_and_state_are_never_allowed(dockerfile):
    for entry in allowlist(dockerfile):
        assert ".env" not in entry and ".db" not in entry and "audit_log" not in entry, entry


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.name)
def test_every_copy_source_is_allowlisted(dockerfile):
    """COPYする物が許可リストにないと、ビルドが「見つからない」で失敗する。"""
    allowed = allowlist(dockerfile)
    for name, arg in instructions(dockerfile):
        if name != "COPY":
            continue
        sources = [p for p in arg.split()[:-1] if not p.startswith("--")]
        for src in sources:
            covered = any(src == a or src.rstrip("/") == a.rstrip("/") or src.startswith(a.rstrip("/") + "/") for a in allowed)
            assert covered or src in {"pyproject.toml", "uv.lock"}, f"{dockerfile.name}: {src}"
            assert (ROOT / src).exists(), src


# --- compose.yaml -----------------------------------------------


def test_api_key_is_passed_at_runtime_and_required(compose):
    key = compose["services"]["api"]["environment"]["OPENAI_API_KEY"]
    assert key.startswith("${OPENAI_API_KEY:?"), "未設定なら、起動前に分かるエラーで止める"
    assert "sk-" not in (SRC / "compose.yaml").read_text(encoding="utf-8")


def test_only_api_receives_the_key(compose):
    for name in ("ui", "init"):
        assert "OPENAI_API_KEY" not in (compose["services"][name].get("environment") or {})


def test_ui_is_stateless(compose):
    assert "volumes" not in compose["services"]["ui"]


def test_state_lives_only_in_a_named_volume(compose):
    assert set(compose["volumes"]) == {"app-data"}
    for name in ("init", "api"):
        assert compose["services"][name]["volumes"] == ["app-data:/app/data"]


def test_ports_are_loopback_only_because_api_has_no_auth(compose):
    for name in ("api", "ui"):
        assert all(p.startswith("127.0.0.1:") for p in compose["services"][name]["ports"])


def test_ui_reaches_api_by_service_name(compose):
    url = compose["services"]["ui"]["environment"]["API_URL"]
    assert url == "http://api:8000" and "localhost" not in url and "127.0.0.1" not in url


def test_startup_order_waits_for_readiness_not_just_start(compose):
    services = compose["services"]
    assert services["api"]["depends_on"]["init"]["condition"] == "service_completed_successfully"
    assert services["ui"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert services["api"]["healthcheck"]["test"] and services["ui"]["healthcheck"]["test"]
    assert services["init"]["restart"] == "no"


@pytest.mark.parametrize("name", ["init", "api", "ui"])
def test_containers_are_hardened(compose, name):
    service = compose["services"][name]
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]


def test_build_contexts_are_the_repository_root(compose):
    for name in ("api", "ui"):
        context = (SRC / compose["services"][name]["build"]["context"]).resolve()
        assert context == ROOT.resolve()
        assert (context / compose["services"][name]["build"]["dockerfile"]).exists()


# --- 依存グループ -----------------------------------------------


def names(requirements):
    return {re.split(r"[\[>=<~! ]", r, maxsplit=1)[0].lower() for r in requirements}


def test_dependency_groups_match_the_project_dependencies():
    """グループ(コンテナ用)と、全章用の dependencies が食い違わない(片方だけ更新する事故を防ぐ)。"""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    groups = pyproject["dependency-groups"]
    in_groups = names(groups["api"]) | names(groups["ui"]) | names(groups["runtime"]) | names(groups["observability"])
    assert in_groups == names(pyproject["project"]["dependencies"])


def test_ui_group_has_no_agent_or_database_dependencies():
    groups = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["dependency-groups"]
    assert names(groups["ui"]).isdisjoint({"openai-agents", "pandas", "fastapi", "uvicorn"})


# --- 初期化ジョブ -----------------------------------------------


@pytest.fixture
def init_db(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ch12_init_db", SRC / "init_db.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "sales.db")
    monkeypatch.setattr(module, "SEED_CSV", ROOT / "data/raw/ai_agent_practice_sales.csv")
    monkeypatch.setattr(module, "NORMALIZE", ROOT / "chapters/ch09-multitable/src/scripts/normalize_sales_db.py")
    return module


def test_init_creates_db_once_and_never_wipes_state(init_db):
    import sqlite3

    assert init_db.main() == 0
    with sqlite3.connect(init_db.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 300
        conn.execute("INSERT INTO review_requests VALUES ('O0001', '確認', 'now')")

    assert init_db.main() == 0  # 2回目(コンテナの再起動)
    with sqlite3.connect(init_db.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM review_requests").fetchone()[0] == 1


def test_interrupted_init_leaves_no_half_built_db(init_db, monkeypatch):
    """作成の途中で失敗しても、中途半端なDBが本物の名前で残らない(残ると、次回は「ある」と判断して壊れたまま動く)。"""

    class Interrupted:
        CSV_PATH = DB_PATH = None

        @classmethod
        def main(cls):
            cls.DB_PATH.write_bytes(b"half-written")
            raise RuntimeError("killed")

    monkeypatch.setattr(init_db, "load_normalize", lambda: Interrupted)

    with pytest.raises(RuntimeError):
        init_db.main()
    assert not init_db.DB_PATH.exists()  # 次回は、もう一度作り直せる
