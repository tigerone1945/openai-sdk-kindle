"""Production Readiness チェックリストを、稼働中の AWS に対して判定する。

  python check_readiness.py                # 人が読む表と、終了コード(FAIL があれば 1)
  python check_readiness.py --json         # 機械が読む形

collect(): AWS CLI で事実を集める(読み取りだけ)。judge(): 事実から、PASS / FAIL / WARN / MANUAL を決める(AWS に触れない)。
「確認できる」ことと「確認できない(人が決める)」ことを分ける。MANUAL は、判定を偽らず、人に残す項目。
"""
import json
import re
import subprocess
import sys

PROJECT = "ai-agent-practice"
REQUIRED_ALARMS = ["alb-target-5xx", "api-healthy-hosts", "api-unhealthy-hosts", "api-cpu", "api-memory", "analysis-failed", "analysis-latency-p95"]
SECRET_NAME = re.compile(r"PASSWORD|SECRET|TOKEN|API_?KEY", re.I)
MIN_RETENTION_DAYS = 30


def aws(*args):
    out = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"aws {' '.join(args[:3])} が失敗: {out.stderr.strip()[:200]}")
    return json.loads(out.stdout or "null")


def collect(project: str = PROJECT) -> dict:
    facts: dict = {}
    facts["rds"] = aws("rds", "describe-db-instances", "--db-instance-identifier", f"{project}-postgres")["DBInstances"][0]
    sgs = aws("ec2", "describe-security-groups", "--filters", f"Name=group-name,Values={project}-*")["SecurityGroups"]
    facts["security_groups"] = {g["GroupName"]: g["IpPermissions"] for g in sgs}
    facts["task_definitions"] = {
        fam: aws("ecs", "describe-task-definition", "--task-definition", f"{project}-{fam}")["taskDefinition"]
        for fam in ("api", "ui", "migrate")
    }
    facts["service"] = aws("ecs", "describe-services", "--cluster", f"{project}-cluster", "--services", f"{project}-api")["services"][0]
    facts["ecr_mutability"] = {
        r["repositoryName"]: r["imageTagMutability"]
        for r in aws("ecr", "describe-repositories")["repositories"] if r["repositoryName"].startswith(project)
    }
    facts["task_roles"] = {}
    for role in ("api-task", "ui-task"):
        name = f"{project}-{role}"
        facts["task_roles"][role] = {
            "attached": aws("iam", "list-attached-role-policies", "--role-name", name)["AttachedPolicies"],
            "inline": aws("iam", "list-role-policies", "--role-name", name)["PolicyNames"],
        }
    exec_role = f"{project}-ecs-execution"
    facts["execution_secret_policy"] = aws("iam", "get-role-policy", "--role-name", exec_role, "--policy-name", "read-task-secrets")["PolicyDocument"]
    facts["log_groups"] = aws("logs", "describe-log-groups", "--log-group-name-prefix", f"/ecs/{project}")["logGroups"]
    events = aws("logs", "filter-log-events", "--log-group-name", f"/ecs/{project}/api", "--max-items", "200", "--query", "events[].message")
    facts["recent_log_lines"] = [m for m in (events or []) if isinstance(m, str)]
    facts["alarms"] = aws("cloudwatch", "describe-alarms", "--alarm-name-prefix", project)["MetricAlarms"]
    return facts


def result(item, status, detail):
    return {"item": item, "status": status, "detail": detail}


def judge(f: dict, project: str = PROJECT) -> list[dict]:
    out = []

    # Secrets: 平文の秘密がタスク定義にない / 注入は Secrets Manager 経由
    plain, injected = [], []
    for fam, td in f["task_definitions"].items():
        for c in td["containerDefinitions"]:
            plain += [f"{fam}:{e['name']}" for e in c.get("environment", []) if SECRET_NAME.search(e["name"])]
            injected += [s["valueFrom"] for s in c.get("secrets", [])]
    ok = not plain and injected and all(":secretsmanager:" in v for v in injected)
    out.append(result("Secrets", "PASS" if ok else "FAIL", "平文の秘密なし・注入は Secrets Manager" if ok else f"平文の疑い: {plain}"))

    # api に DDL ができる資格情報を渡していない
    api_secrets = {s["name"] for c in f["task_definitions"]["api"]["containerDefinitions"] for s in c.get("secrets", [])}
    bad = sorted(n for n in api_secrets if "OWNER" in n)
    out.append(result("Secrets: 管理者の資格情報を api に渡さない", "FAIL" if bad else "PASS", str(bad) if bad else "api の secrets は " + ", ".join(sorted(api_secrets))))

    # Network
    rds = f["rds"]
    db_sg = f["security_groups"].get(f"{project}-db", [])
    db_open = [r for p in db_sg for r in p.get("IpRanges", [])]
    out.append(result("Network: RDS を公開していない", "PASS" if not rds["PubliclyAccessible"] and not db_open else "FAIL",
                      f"PubliclyAccessible={rds['PubliclyAccessible']} / DB の SG の CIDR 入口={len(db_open)}"))
    alb_open = [r["CidrIp"] for p in f["security_groups"].get(f"{project}-alb", []) for r in p.get("IpRanges", []) if r["CidrIp"] == "0.0.0.0/0"]
    out.append(result("Network: ALB の入口が 0.0.0.0/0 でない", "FAIL" if alb_open else "PASS", "全開放あり" if alb_open else "入口は限定されている"))

    # IAM
    roles = f["task_roles"]
    with_perm = [r for r, v in roles.items() if v["attached"] or v["inline"]]
    out.append(result("IAM: タスクロールに権限を付けていない", "FAIL" if with_perm else "PASS", f"権限あり: {with_perm}" if with_perm else "api・ui とも 0"))
    resources = [r for st in f["execution_secret_policy"]["Statement"] for r in (st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]])]
    out.append(result("IAM: 実行ロールが読めるのは、必要なシークレットだけ", "FAIL" if any("*" in r for r in resources) else "PASS", f"{len(resources)} 個の ARN を個別に指定"))

    # Logs
    short = [g["logGroupName"] for g in f["log_groups"] if g.get("retentionInDays", 0) < MIN_RETENTION_DAYS]
    out.append(result(f"Logs: 保持期間 {MIN_RETENTION_DAYS} 日以上", "FAIL" if short else "PASS", f"不足: {short}" if short else f"{len(f['log_groups'])} グループとも設定済み"))
    parsed = [json.loads(m) for m in f["recent_log_lines"] if m.startswith("{")]
    structured = [p for p in parsed if "event" in p and "ts" in p]
    leaks = [p for p in parsed if "question" in p or "result_summary" in p]
    out.append(result("Logs: アプリのエラーを追跡できる(構造化ログ)", "PASS" if structured and not leaks else "FAIL",
                      f"構造化 {len(structured)} 件 / 質問・回答の混入 {len(leaks)} 件" if structured else "構造化ログが見つからない"))

    # Metrics / Alarms
    names = {a["AlarmName"]: a for a in f["alarms"]}
    missing = [n for n in REQUIRED_ALARMS if f"{project}-{n}" not in names]
    no_action = [n for n, a in names.items() if not a["AlarmActions"]]
    out.append(result("Metrics: 5xx・正常ホスト・CPU・メモリ・失敗・遅延のアラーム", "FAIL" if missing else "PASS", f"不足: {missing}" if missing else f"{len(REQUIRED_ALARMS)} 個とも存在"))
    out.append(result("Metrics: アラームに通知先がある", "FAIL" if no_action else "PASS", f"通知先なし: {no_action}" if no_action else "全アラームに SNS"))
    out.append(result("Metrics: 購読者(人に届く経路)", "MANUAL", "本書では SNS トピックまで。メール・チャットへの購読は運用側で決める"))

    # DB
    out.append(result("DB: 暗号化・バックアップ", "PASS" if rds["StorageEncrypted"] and rds["BackupRetentionPeriod"] >= 1 else "FAIL",
                      f"暗号化={rds['StorageEncrypted']} / バックアップ {rds['BackupRetentionPeriod']} 日"))
    out.append(result("DB: 削除保護・Multi-AZ", "PASS" if rds["DeletionProtection"] and rds["MultiAZ"] else "WARN",
                      f"DeletionProtection={rds['DeletionProtection']} / MultiAZ={rds['MultiAZ']}(学習用の既定。本番では有効にする)"))

    # Deployment / Rollback
    images = [c["image"] for c in f["task_definitions"]["api"]["containerDefinitions"]]
    tag = images[0].rsplit(":", 1)[-1]
    out.append(result("Deployment: バージョンを特定できる", "PASS" if tag != "latest" and all(m == "IMMUTABLE" for m in f["ecr_mutability"].values()) else "FAIL",
                      f"api のタグ={tag} / ECR は {sorted(set(f['ecr_mutability'].values()))}"))
    cb = f["service"].get("deploymentConfiguration", {}).get("deploymentCircuitBreaker", {})
    out.append(result("Rollback: 起動に失敗する版は自動で戻る", "PASS" if cb.get("enable") and cb.get("rollback") else "FAIL", f"circuit breaker={cb}"))
    out.append(result("Rollback: 「起動した」だけでなく「動く」ことの確認(デプロイ後の評価)", "MANUAL", "ECS の成功は /health の成功。DB に繋がらなくても成功する(第16章の障害演習)。evaluation の smoke を流す"))
    out.append(result("Evaluation: 代表ケースの回帰評価", "MANUAL", "evaluation.runner の実行結果(合格率・flaky)を人が見て判断する"))
    return out


def main() -> int:
    results = judge(collect())
    if "--json" in sys.argv:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    else:
        for r in results:
            print(f"{r['status']:6s} {r['item']}\n         {r['detail']}")
        counts = {s: sum(r["status"] == s for r in results) for s in ("PASS", "FAIL", "WARN", "MANUAL")}
        print("\n" + " / ".join(f"{k} {v}" for k, v in counts.items()))
    return 1 if any(r["status"] == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
