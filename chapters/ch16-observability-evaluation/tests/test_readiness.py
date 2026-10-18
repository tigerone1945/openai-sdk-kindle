"""Production Readiness の判定(check_readiness.judge)を、固定の事実に対して検査する。AWS には触れない。"""
import copy
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts/check_readiness.py"
spec = importlib.util.spec_from_file_location("check_readiness", SCRIPT)
readiness = importlib.util.module_from_spec(spec)
sys.modules["check_readiness"] = readiness
spec.loader.exec_module(readiness)

P = "ai-agent-practice"
SECRET_ARN = "arn:aws:secretsmanager:ap-northeast-1:111122223333:secret:x"


def container(name, secrets=(), env=(), image="123.dkr.ecr.ap-northeast-1.amazonaws.com/ai-agent-practice-api:v3"):
    return {"name": name, "image": image, "environment": [{"name": n, "value": "v"} for n in env],
            "secrets": [{"name": n, "valueFrom": SECRET_ARN} for n in secrets]}


GOOD = {
    "rds": {"PubliclyAccessible": False, "StorageEncrypted": True, "BackupRetentionPeriod": 1, "DeletionProtection": False, "MultiAZ": False},
    "security_groups": {f"{P}-db": [{"IpRanges": []}], f"{P}-alb": [{"IpRanges": [{"CidrIp": "203.0.113.7/32"}]}]},
    "task_definitions": {
        "api": {"containerDefinitions": [container("api", ["DB_RO_PASSWORD", "DB_RW_PASSWORD", "OPENAI_API_KEY"], ["DB_HOST"])]},
        "ui": {"containerDefinitions": [container("ui", env=["API_URL"])]},
        "migrate": {"containerDefinitions": [container("migrate", ["DB_OWNER_PASSWORD"])]},
    },
    "service": {"deploymentConfiguration": {"deploymentCircuitBreaker": {"enable": True, "rollback": True}}},
    "ecr_mutability": {f"{P}-api": "IMMUTABLE", f"{P}-ui": "IMMUTABLE"},
    "task_roles": {"api-task": {"attached": [], "inline": []}, "ui-task": {"attached": [], "inline": []}},
    "execution_secret_policy": {"Statement": [{"Resource": [SECRET_ARN]}]},
    "log_groups": [{"logGroupName": f"/ecs/{P}/api", "retentionInDays": 30}],
    "recent_log_lines": ['{"ts": "t", "event": "analysis_completed", "duration_ms": 10}'],
    "alarms": [{"AlarmName": f"{P}-{n}", "AlarmActions": ["arn:sns"]} for n in readiness.REQUIRED_ALARMS],
}


def status(facts):
    return {r["item"].split(":")[0] + ":" + r["item"].split(":")[-1][:12]: r["status"] for r in readiness.judge(facts)}, readiness.judge(facts)


def verdicts(facts):
    return {r["item"]: r["status"] for r in readiness.judge(facts)}


def test_a_healthy_stack_has_no_failures_and_keeps_manual_items_manual():
    v = verdicts(GOOD)
    assert "FAIL" not in v.values()
    assert sum(s == "MANUAL" for s in v.values()) == 3  # 購読者・デプロイ後の評価・回帰評価は、機械では決めない
    assert sum(s == "WARN" for s in v.values()) == 1    # 学習用 DB(削除保護なし・Single-AZ)


def mutate(path, value):
    f = copy.deepcopy(GOOD)
    target = f
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return f


@pytest.mark.parametrize("facts,failing_item", [
    (mutate(["rds", "PubliclyAccessible"], True), "Network: RDS を公開していない"),
    (mutate(["rds", "StorageEncrypted"], False), "DB: 暗号化・バックアップ"),
    (mutate(["rds", "BackupRetentionPeriod"], 0), "DB: 暗号化・バックアップ"),
    (mutate(["security_groups", f"{P}-db"], [{"IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]), "Network: RDS を公開していない"),
    (mutate(["security_groups", f"{P}-alb"], [{"IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]), "Network: ALB の入口が 0.0.0.0/0 でない"),
    (mutate(["task_roles", "api-task", "inline"], ["admin"]), "IAM: タスクロールに権限を付けていない"),
    (mutate(["execution_secret_policy"], {"Statement": [{"Resource": "*"}]}), "IAM: 実行ロールが読めるのは、必要なシークレットだけ"),
    (mutate(["log_groups"], [{"logGroupName": "/ecs/x"}]), "Logs: 保持期間 30 日以上"),
    (mutate(["log_groups"], [{"logGroupName": "/ecs/x", "retentionInDays": 14}]), "Logs: 保持期間 30 日以上"),
    (mutate(["recent_log_lines"], ["plain text line"]), "Logs: アプリのエラーを追跡できる(構造化ログ)"),
    (mutate(["recent_log_lines"], ['{"ts": "t", "event": "x", "question": "顧客 A の売上"}']), "Logs: アプリのエラーを追跡できる(構造化ログ)"),
    (mutate(["alarms"], GOOD["alarms"][:-1]), "Metrics: 5xx・正常ホスト・CPU・メモリ・失敗・遅延のアラーム"),
    (mutate(["alarms"], [{"AlarmName": f"{P}-{n}", "AlarmActions": []} for n in readiness.REQUIRED_ALARMS]), "Metrics: アラームに通知先がある"),
    (mutate(["ecr_mutability", f"{P}-api"], "MUTABLE"), "Deployment: バージョンを特定できる"),
    (mutate(["service"], {"deploymentConfiguration": {"deploymentCircuitBreaker": {"enable": True, "rollback": False}}}), "Rollback: 起動に失敗する版は自動で戻る"),
])
def test_each_violation_is_caught_by_the_matching_item(facts, failing_item):
    assert verdicts(facts)[failing_item] == "FAIL"


def test_plaintext_secret_in_environment_is_caught():
    f = copy.deepcopy(GOOD)
    f["task_definitions"]["api"]["containerDefinitions"][0]["environment"].append({"name": "OPENAI_API_KEY", "value": "sk-leak"})
    assert verdicts(f)["Secrets"] == "FAIL"


def test_owner_credentials_in_api_are_caught():
    f = copy.deepcopy(GOOD)
    f["task_definitions"]["api"]["containerDefinitions"][0]["secrets"].append({"name": "DB_OWNER_PASSWORD", "valueFrom": SECRET_ARN})
    assert verdicts(f)["Secrets: 管理者の資格情報を api に渡さない"] == "FAIL"


def test_latest_tag_is_not_a_version():
    f = copy.deepcopy(GOOD)
    f["task_definitions"]["api"]["containerDefinitions"][0]["image"] = "x/ai-agent-practice-api:latest"
    assert verdicts(f)["Deployment: バージョンを特定できる"] == "FAIL"
