"""第15章の Terraform を、ルールとして検査する。

AWS には何も作らない(plan は読み取りのみ)。plan には terraform と AWS 認証情報が要る。
無い環境では、plan を使う検査だけ理由を表示して飛ばす。ファイルだけで済む検査は、常に実行する。
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

TF_SRC = Path(__file__).resolve().parents[1] / "src" / "terraform"
TF = {p.name: p.read_text() for p in TF_SRC.glob("*.tf")}

os.environ.setdefault("TF_PLUGIN_CACHE_DIR", tempfile.mkdtemp(prefix="tf-plugin-cache-"))


def _have_aws() -> bool:
    return bool(shutil.which("terraform") and shutil.which("aws")) and subprocess.run(
        ["aws", "sts", "get-caller-identity"], capture_output=True).returncode == 0


needs_aws = pytest.mark.skipif(not _have_aws(), reason="terraform と AWS 認証情報が必要")


def _plan(tmp_path: Path, **variables) -> dict:
    work = tmp_path / "tf"
    work.mkdir()
    for f in TF_SRC.glob("*.tf"):
        if f.name != "backend.tf":  # state は一時ディレクトリのローカルに置く
            (work / f.name).write_text(f.read_text())
    shutil.copy(TF_SRC / ".terraform.lock.hcl", work)
    run = lambda *a: subprocess.run(["terraform", f"-chdir={work}", *a], capture_output=True, text=True)  # noqa: E731
    assert run("init", "-input=false", "-no-color").returncode == 0
    args = ["plan", "-input=false", "-no-color", "-out=p.tfplan"] + [f"-var={k}={v}" for k, v in variables.items()]
    r = run(*args)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(run("show", "-json", "p.tfplan").stdout)


def _created(plan, rtype):
    return [r["change"]["after"] for r in plan["resource_changes"] if r["type"] == rtype and r["change"]["actions"] == ["create"]]


@pytest.fixture(scope="module")
def default_plan(tmp_path_factory):
    return _plan(tmp_path_factory.mktemp("default"))


@pytest.fixture(scope="module")
def no_nat_plan(tmp_path_factory):
    return _plan(tmp_path_factory.mktemp("nonat"), enable_nat_gateway="false")


def _assign_public_ip(plan) -> dict:
    """サービスごとの assign_public_ip(local の値は plan の時点で確定している)。"""
    return {
        r["name"]: r["change"]["after"]["network_configuration"][0]["assign_public_ip"]
        for r in plan["resource_changes"] if r["type"] == "aws_ecs_service"
    }


# --- plan に対する検査 -------------------------------------------------


@needs_aws
def test_default_plan_only_creates_and_starts_no_tasks(default_plan):
    assert {a for r in default_plan["resource_changes"] for a in r["change"]["actions"]} <= {"create", "read"}
    for svc in _created(default_plan, "aws_ecs_service"):
        assert svc["desired_count"] == 0  # シークレットとイメージが用意できる前に、タスクを起動して失敗させない


@needs_aws
def test_standard_configuration_has_nat_and_tasks_stay_private(default_plan):
    assert len(_created(default_plan, "aws_nat_gateway")) == 1
    assert _assign_public_ip(default_plan) == {"api": False, "ui": False}


@needs_aws
def test_without_nat_tasks_use_public_subnets_but_nothing_else_changes(default_plan, no_nat_plan):
    assert not _created(no_nat_plan, "aws_nat_gateway") and not _created(no_nat_plan, "aws_eip")
    assert _assign_public_ip(no_nat_plan) == {"api": True, "ui": True}
    # 入口のルールは、NAT の有無で変わらない(公開 IP を持っても、入口は ALB の SG だけ)
    def ingress(plan):
        return sorted((r["from_port"], str(r.get("cidr_ipv4"))) for r in _created(plan, "aws_vpc_security_group_ingress_rule"))
    assert ingress(default_plan) == ingress(no_nat_plan)


@needs_aws
def test_no_ingress_from_the_internet_by_default(default_plan):
    for rule in _created(default_plan, "aws_vpc_security_group_ingress_rule"):
        assert rule.get("cidr_ipv4") is None and rule.get("cidr_ipv6") is None, rule


@needs_aws
def test_alb_ingress_accepts_only_the_given_cidr_and_rejects_open_internet(tmp_path_factory):
    plan = _plan(tmp_path_factory.mktemp("cidr"), alb_ingress_cidrs='["203.0.113.7/32"]')
    cidr_rules = [r for r in _created(plan, "aws_vpc_security_group_ingress_rule") if r.get("cidr_ipv4")]
    assert [(r["cidr_ipv4"], r["from_port"]) for r in cidr_rules] == [("203.0.113.7/32", 80)]
    work = tmp_path_factory.mktemp("open") / "tf"
    work.mkdir()
    for f in TF_SRC.glob("*.tf"):
        if f.name != "backend.tf":
            (work / f.name).write_text(f.read_text())
    shutil.copy(TF_SRC / ".terraform.lock.hcl", work)
    subprocess.run(["terraform", f"-chdir={work}", "init", "-input=false"], capture_output=True)
    r = subprocess.run(["terraform", f"-chdir={work}", "plan", "-input=false", "-no-color", '-var=alb_ingress_cidrs=["0.0.0.0/0"]'], capture_output=True, text=True)
    assert r.returncode != 0 and "0.0.0.0/0" in r.stdout + r.stderr


@needs_aws
def test_ecr_tags_are_immutable_and_scanned(default_plan):
    repos = _created(default_plan, "aws_ecr_repository")
    assert len(repos) == 2
    for r in repos:
        assert r["image_tag_mutability"] == "IMMUTABLE" and r["image_scanning_configuration"][0]["scan_on_push"] is True


@needs_aws
def test_secrets_are_containers_only_and_never_get_values_from_terraform(default_plan):
    types = {r["type"] for r in default_plan["resource_changes"]}
    assert "aws_secretsmanager_secret" in types
    assert "aws_secretsmanager_secret_version" not in types  # 値を Terraform に渡すと、state に入る
    assert not any("random_password" in t for t in types)


@needs_aws
def test_task_roles_have_no_permissions_and_execution_role_reads_only_four_secrets(default_plan):
    assert len(_created(default_plan, "aws_iam_role")) == 3
    assert not _created(default_plan, "aws_iam_role_policy_attachment")[1:]  # 実行ロールの AWS 管理ポリシー 1 つだけ
    cfg = {r["address"]: r for r in default_plan["configuration"]["root_module"]["resources"]}
    doc = cfg["data.aws_iam_policy_document.read_secrets"]["expressions"]["statement"][0]
    assert doc["actions"]["constant_value"] == ["secretsmanager:GetSecretValue"]
    assert len(doc["resources"]["references"]) >= 4 and "*" not in json.dumps(doc["resources"])


@needs_aws
def test_load_balancer_checks_liveness_not_database_readiness(default_plan):
    groups = {g["name"]: g for g in _created(default_plan, "aws_lb_target_group")}
    assert groups["ai-agent-practice-api"]["health_check"][0]["path"] == "/health"


@needs_aws
def test_services_roll_back_automatically_and_use_arm64(default_plan):
    for svc in _created(default_plan, "aws_ecs_service"):
        assert svc["deployment_circuit_breaker"][0] == {"enable": True, "rollback": True}
    # イメージは arm64 で作る(deploy_images.sh)。タスク定義も ARM64 でないと、起動時に exec format error になる
    assert TF["tasks.tf"].count('cpu_architecture        = "ARM64"') == 3


# --- ファイルだけの検査 ----------------------------------------------------


def _block(text: str, header: str) -> str:
    start = text.index(header)
    return text[start:text.index("\nresource ", start + 1) if "\nresource " in text[start + 1:] else len(text)]


def test_no_plaintext_secret_in_task_environment():
    names = re.findall(r'\{ name = "(\w+)", value =', TF["tasks.tf"])
    assert names, "environment の定義が見つかりません"
    assert not [n for n in names if re.search(r"PASSWORD|KEY|SECRET|TOKEN", n)], names


def test_api_gets_only_app_roles_and_migrate_alone_gets_the_owner_credentials():
    api = _block(TF["tasks.tf"], 'resource "aws_ecs_task_definition" "api"')
    migrate = _block(TF["tasks.tf"], 'resource "aws_ecs_task_definition" "migrate"')
    shared = _block(TF["tasks.tf"], "app_db_secrets")
    assert "local.app_db_secrets" in api and "db_secret_arn" not in api and "DB_OWNER" not in api
    assert {"DB_RO_PASSWORD", "DB_RW_PASSWORD"} == set(re.findall(r'name = "(DB_\w+)"', shared.split("hardening")[0]))
    assert "DB_OWNER_USER" in migrate and "DB_OWNER_PASSWORD" in migrate


def test_task_definitions_spell_out_the_defaults_ecs_adds_itself():
    """これが無いと、plan のたびに「差分あり」になり、タスク定義が毎回作り直される(実測)。"""
    text = TF["tasks.tf"]
    for fragment in ("systemControls = []", "volumesFrom    = []", "hostPort = 8000", "hostPort = 8501", 'add = [], drop = ["ALL"]'):
        assert fragment.replace(" ", "") in text.replace(" ", ""), fragment
    assert "health_check_custom_config" not in TF["service_discovery.tf"]  # 空ブロックが毎回の作り直しを起こす(実測)


def test_containers_are_hardened():
    assert TF["tasks.tf"].count("readonlyRootFilesystem = true") == 1  # local.hardening に 1 回。3 コンテナが merge で使う
    assert TF["tasks.tf"].count("local.hardening") == 3  # api・ui・migrate の全部
    assert 'drop = ["ALL"]' in TF["tasks.tf"]


def test_nat_is_the_standard_and_the_switch_is_documented():
    assert re.search(r'variable "enable_nat_gateway".*?default\s*=\s*true', TF["variables.tf"], re.S)
    assert "task_assign_public_ip = !var.enable_nat_gateway" in TF["network.tf"].replace("  ", " ") or "!var.enable_nat_gateway" in TF["network.tf"]


def test_backend_is_s3_with_lockfile_and_state_key_is_per_chapter():
    assert "use_lockfile = true" in TF["backend.tf"] and "bucket" not in TF["backend.tf"]
    assert 'key    = "ch15/terraform.tfstate"' in (TF_SRC / "backend.hcl.example").read_text()
    ignored = (TF_SRC / ".gitignore").read_text().split()
    assert {"*.tfstate", "terraform.tfvars", "backend.hcl", "*.tfplan"} <= set(ignored)


def test_terraform_fmt_is_clean():
    if not shutil.which("terraform"):
        pytest.skip("terraform が必要")
    assert subprocess.run(["terraform", f"-chdir={TF_SRC}", "fmt", "-check", "-recursive"], capture_output=True).returncode == 0
