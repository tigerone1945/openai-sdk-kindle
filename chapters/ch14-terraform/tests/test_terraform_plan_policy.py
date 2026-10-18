"""Terraform の構成を、plan の JSON に対する「ルール」として検証する。

AWS には何も作らない(plan は読み取りのみ)。ただし plan は AWS の認証情報と
terraform コマンドを必要とするので、無い環境では理由を表示して skip する。
"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

TF_SRC = Path(__file__).resolve().parents[1] / "src" / "terraform"
SKIP_REASON = "terraform と AWS 認証情報(aws sts get-caller-identity が通る環境)が必要"


def _have_aws() -> bool:
    if not shutil.which("terraform") or not shutil.which("aws"):
        return False
    return subprocess.run(["aws", "sts", "get-caller-identity"], capture_output=True).returncode == 0


# provider(数百 MB)を、テストごとに取り直さない
os.environ.setdefault("TF_PLUGIN_CACHE_DIR", tempfile.mkdtemp(prefix="tf-plugin-cache-"))

needs_aws = pytest.mark.skipif(not _have_aws(), reason=SKIP_REASON)


def _workdir(tmp_path: Path, mutate=None) -> Path:
    """backend.tf を除いた作業コピーを作る(state は一時ディレクトリのローカルに置く)。"""
    work = tmp_path / "tf"
    work.mkdir()
    for f in TF_SRC.glob("*.tf"):
        if f.name != "backend.tf":
            work.joinpath(f.name).write_text(f.read_text())
    lock = TF_SRC / ".terraform.lock.hcl"
    if lock.exists():
        shutil.copy(lock, work / lock.name)
    if mutate:
        mutate(work)
    r = subprocess.run(["terraform", f"-chdir={work}", "init", "-input=false", "-no-color"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return work


def _plan(work: Path, **variables) -> dict:
    args = ["terraform", f"-chdir={work}", "plan", "-input=false", "-no-color", "-out=p.tfplan"]
    args += [f"-var={k}={v}" for k, v in variables.items()]
    r = subprocess.run(args, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    show = subprocess.run(["terraform", f"-chdir={work}", "show", "-json", "p.tfplan"], capture_output=True, text=True)
    return json.loads(show.stdout)


def _created(plan: dict, rtype: str) -> list[dict]:
    return [r["change"]["after"] for r in plan["resource_changes"] if r["type"] == rtype and r["change"]["actions"] == ["create"]]


@pytest.fixture(scope="module")
def plans(tmp_path_factory):
    out = {}
    for nat in ("false", "true"):
        out[nat] = _plan(_workdir(tmp_path_factory.mktemp(f"nat{nat}")), enable_nat_gateway=nat)
    return out


@needs_aws
def test_plan_only_creates_nothing_else(plans):
    for plan in plans.values():
        assert {a for r in plan["resource_changes"] for a in r["change"]["actions"]} == {"create"}


@needs_aws
def test_nat_toggle_adds_exactly_eip_nat_and_route(plans):
    def types(plan):
        return [r["type"] for r in plan["resource_changes"]]
    off, on = types(plans["false"]), types(plans["true"])
    assert "aws_nat_gateway" not in off and "aws_eip" not in off
    extra = sorted(set(on) - set(off))
    assert extra == ["aws_eip", "aws_nat_gateway", "aws_route"]
    assert len(on) - len(off) == 3


@needs_aws
def test_rds_is_private_encrypted_and_has_no_password_in_terraform(plans):
    (db,) = _created(plans["false"], "aws_db_instance")
    assert db["publicly_accessible"] is False
    assert db["storage_encrypted"] is True
    assert db["manage_master_user_password"] is True
    assert db["password"] is None and db.get("password_wo") is None


@needs_aws
def test_rds_sits_in_private_subnets_behind_db_security_group(plans):
    plan = plans["false"]
    # subnet の id は apply まで未確定。だから「何を参照しているか」を構成から読む
    cfg = {r["address"]: r for r in plan["configuration"]["root_module"]["resources"]}
    assert cfg["aws_db_subnet_group.main"]["expressions"]["subnet_ids"]["references"][0].startswith("aws_subnet.private")
    refs = cfg["aws_db_instance.postgres"]["expressions"]["vpc_security_group_ids"]["references"]
    assert "aws_security_group.db.id" in refs and not any("aws_security_group.alb" in r for r in refs)
    assert len(_created(plan, "aws_subnet")) == 4  # 公開 2 + 非公開 2(2 AZ)


@needs_aws
def test_no_ingress_rule_opens_to_the_internet(plans):
    # 既定(alb_ingress_cidrs = [])では、CIDR を送信元にした入口は 1 つも無い
    for rule in _created(plans["false"], "aws_vpc_security_group_ingress_rule"):
        assert rule.get("cidr_ipv4") is None and rule.get("cidr_ipv6") is None, rule


@needs_aws
def test_db_is_reachable_only_from_the_app_security_group(plans):
    rules = _created(plans["false"], "aws_vpc_security_group_ingress_rule")
    db_rules = [r for r in rules if r["from_port"] == 5432]
    assert len(db_rules) == 1 and db_rules[0]["to_port"] == 5432
    assert db_rules[0].get("cidr_ipv4") is None and db_rules[0].get("cidr_ipv6") is None


@needs_aws
def test_every_taggable_resource_carries_the_project_tag(plans):
    for r in plans["false"]["resource_changes"]:
        tags = r["change"]["after"].get("tags_all")
        if tags is not None:
            assert tags.get("Project") == "ai-agent-practice" and tags.get("ManagedBy") == "terraform", r["address"]


@needs_aws
def test_alb_ingress_validation_rejects_open_internet(tmp_path):
    work = _workdir(tmp_path)
    r = subprocess.run(
        ["terraform", f"-chdir={work}", "plan", "-input=false", "-no-color", '-var=alb_ingress_cidrs=["0.0.0.0/0"]'],
        capture_output=True, text=True,
    )
    assert r.returncode != 0 and "0.0.0.0/0" in (r.stdout + r.stderr)


@needs_aws
def test_alb_ingress_cidr_creates_one_rule_per_cidr(tmp_path):
    plan = _plan(_workdir(tmp_path), alb_ingress_cidrs='["203.0.113.7/32"]')
    http = [r for r in _created(plan, "aws_vpc_security_group_ingress_rule") if r["from_port"] == 80]
    assert [r["cidr_ipv4"] for r in http] == ["203.0.113.7/32"]


# --- 変異テスト: 壊した構成を、上のテスト群が検出できるか ---------------------------------


def _mutate(path_name: str, old: str, new: str):
    def apply(work: Path):
        f = work / path_name
        text = f.read_text()
        assert old in text, f"mutation target not found: {old!r}"
        f.write_text(text.replace(old, new))
    return apply


@needs_aws
@pytest.mark.parametrize(
    "file,old,new,reason",
    [
        ("rds.tf", "publicly_accessible    = false", "publicly_accessible    = true", "RDS が公開になる"),
        ("rds.tf", "storage_encrypted     = true", "storage_encrypted     = false", "暗号化が外れる"),
        ("rds.tf", "manage_master_user_password = true", 'password = "hunter2"', "パスワードを Terraform が持つ"),
        ("security.tf", "referenced_security_group_id = aws_security_group.app.id\n  from_port                    = 5432",
         'cidr_ipv4 = "0.0.0.0/0"\n  from_port = 5432', "5432 をインターネットへ開ける"),
    ],
)
def test_mutated_configuration_violates_a_policy(tmp_path, file, old, new, reason):
    work = _workdir(tmp_path, _mutate(file, old, new))
    plan = _plan(work, enable_nat_gateway="false")
    (db,) = _created(plan, "aws_db_instance")
    rules = _created(plan, "aws_vpc_security_group_ingress_rule")
    db_rules = [r for r in rules if r["from_port"] == 5432]
    violated = (
        db["publicly_accessible"] is not False
        or db["storage_encrypted"] is not True
        or db["password"] is not None
        or any(r.get("cidr_ipv4") or r.get("cidr_ipv6") for r in db_rules)
    )
    assert violated, f"ルールが変異を検出できなかった: {reason}"
