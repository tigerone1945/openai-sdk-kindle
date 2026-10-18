"""第16章の Terraform(監視)を、ファイルと plan の両方から検査する。plan は AWS 認証情報が要る(作成はしない)。"""
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

needs_aws = pytest.mark.skipif(
    not (shutil.which("terraform") and shutil.which("aws") and subprocess.run(["aws", "sts", "get-caller-identity"], capture_output=True).returncode == 0),
    reason="terraform と AWS 認証情報が必要")


@pytest.fixture(scope="module")
def plan(tmp_path_factory):
    work = tmp_path_factory.mktemp("plan") / "tf"
    work.mkdir()
    for f in TF_SRC.glob("*.tf"):
        if f.name != "backend.tf":
            (work / f.name).write_text(f.read_text())
    shutil.copy(TF_SRC / ".terraform.lock.hcl", work)
    run = lambda *a: subprocess.run(["terraform", f"-chdir={work}", *a], capture_output=True, text=True)  # noqa: E731
    assert run("init", "-input=false", "-no-color").returncode == 0
    r = run("plan", "-input=false", "-no-color", "-out=p.tfplan")
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(run("show", "-json", "p.tfplan").stdout)


def created(plan, rtype):
    return [r["change"]["after"] for r in plan["resource_changes"] if r["type"] == rtype and r["change"]["actions"] == ["create"]]


@needs_aws
def test_runtime_health_alarms_exist_and_all_notify(plan):
    alarms = {a["alarm_name"]: a for a in created(plan, "aws_cloudwatch_metric_alarm")}
    expected = {"alb-target-5xx", "api-healthy-hosts", "api-unhealthy-hosts", "api-cpu", "api-memory", "analysis-failed", "analysis-latency-p95"}
    assert {n.removeprefix("ai-agent-practice-") for n in alarms} == expected
    # アラーム → SNS の経路は、apply 後に決まる値(ARN)。構成上、全アラームが alarm_actions を持つことを見る
    cfg = {r["name"]: r for r in plan["configuration"]["root_module"]["resources"] if r["type"] == "aws_cloudwatch_metric_alarm"}
    assert all("alarm_actions" in r["expressions"] for r in cfg.values())


@needs_aws
def test_missing_data_policy_matches_what_missing_means(plan):
    by = {a["alarm_name"].removeprefix("ai-agent-practice-"): a for a in created(plan, "aws_cloudwatch_metric_alarm")}
    assert by["api-healthy-hosts"]["treat_missing_data"] == "breaching"   # データが無い = 台が居ない
    assert by["alb-target-5xx"]["treat_missing_data"] == "notBreaching"   # リクエストが無い = 異常ではない


@needs_aws
def test_metric_filters_turn_structured_logs_into_metrics(plan):
    filters = {f["name"]: f for f in created(plan, "aws_cloudwatch_log_metric_filter")}
    assert set(filters) == {"analysis-failed", "analysis-duration", "http-5xx", "approval-not-found"}
    assert filters["analysis-duration"]["metric_transformation"][0]["value"] == "$.duration_ms"
    for f in filters.values():
        assert f["pattern"].startswith("{ $.event") and f["metric_transformation"][0]["namespace"] == "AiAgent"


@needs_aws
def test_logs_are_kept_for_30_days_by_default(plan):
    groups = created(plan, "aws_cloudwatch_log_group")
    assert len(groups) == 3 and {g["retention_in_days"] for g in groups} == {30}


@needs_aws
def test_alarm_topic_is_encrypted_and_has_no_subscription(plan):
    (topic,) = created(plan, "aws_sns_topic")
    assert topic["kms_master_key_id"] == "alias/aws/sns"
    assert not created(plan, "aws_sns_topic_subscription")  # 人に届く経路は、運用側で決める(MANUAL)


@needs_aws
def test_dashboard_is_created(plan):
    (dash,) = created(plan, "aws_cloudwatch_dashboard")
    assert dash["dashboard_name"] == "ai-agent-practice-runtime"


def test_default_api_image_tag_is_the_chapter_16_build():
    assert re.search(r'variable "api_image_tag".*?default\s*=\s*"v3"', TF["variables.tf"], re.S)


def test_backend_key_is_per_chapter_and_state_files_are_ignored():
    assert 'key    = "ch16/terraform.tfstate"' in (TF_SRC / "backend.hcl.example").read_text()
    assert {"*.tfstate", "terraform.tfvars", "backend.hcl", "*.tfplan"} <= set((TF_SRC / ".gitignore").read_text().split())


def test_ecs_defaults_are_still_spelled_out_after_copying_from_chapter_15():
    """第15章で見つけた、plan が収束しない原因(ECS が補う既定値)。複製で失われていないこと。"""
    text = TF["tasks.tf"].replace(" ", "")
    for fragment in ("systemControls=[]", "volumesFrom=[]", "hostPort=8000", 'add=[],drop=["ALL"]'):
        assert fragment in text
    assert "health_check_custom_config" not in TF["service_discovery.tf"]


def test_terraform_fmt_is_clean():
    if not shutil.which("terraform"):
        pytest.skip("terraform が必要")
    assert subprocess.run(["terraform", f"-chdir={TF_SRC}", "fmt", "-check", "-recursive"], capture_output=True).returncode == 0
