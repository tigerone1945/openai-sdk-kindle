"""起動できない版(存在しないイメージタグ)を出して、自動ロールバック(circuit breaker)が働くかを測る。

  python bad_deploy_drill.py <ALB のホスト名>

新しいタスク定義の版を、タグだけ存在しないものにして登録し、サービスを更新する。
その間、ALB の /health を 5 秒ごとに呼び、利用者から見て止まるかを記録する。自分の AWS 環境だけで使うこと。
終わったら、登録した版は取り消す(Terraform が管理している版は、触らない)。
"""
import json
import subprocess
import sys
import time
import urllib.request

ALB = sys.argv[1]
CLUSTER, SERVICE, FAMILY = "ai-agent-practice-cluster", "ai-agent-practice-api", "ai-agent-practice-api"
T0 = time.time()


def aws(*args):
    r = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[:300])
    return json.loads(r.stdout) if r.stdout.strip() else None


def mark(msg):
    print(f"[{time.time() - T0:6.0f}s] {msg}", flush=True)


def health():
    try:
        with urllib.request.urlopen(f"http://{ALB}/health", timeout=5) as r:
            return r.status
    except Exception as e:  # noqa: BLE001
        return type(e).__name__


current = aws("ecs", "describe-task-definition", "--task-definition", FAMILY)["taskDefinition"]
good_arn = current["taskDefinitionArn"]
spec = {k: v for k, v in current.items() if k in (
    "family", "taskRoleArn", "executionRoleArn", "networkMode", "containerDefinitions", "volumes", "requiresCompatibilities", "cpu", "memory", "runtimePlatform")}
spec["containerDefinitions"][0]["image"] = spec["containerDefinitions"][0]["image"].rsplit(":", 1)[0] + ":v999-does-not-exist"
bad_arn = aws("ecs", "register-task-definition", "--cli-input-json", json.dumps(spec))["taskDefinition"]["taskDefinitionArn"]
mark(f"起動できない版を登録: {bad_arn.rsplit('/', 1)[-1]}(元は {good_arn.rsplit('/', 1)[-1]})")

aws("ecs", "update-service", "--cluster", CLUSTER, "--service", SERVICE, "--task-definition", bad_arn)
mark("サービスを、起動できない版に更新")

probes: list[tuple[float, object]] = []
last = None
while time.time() - T0 < 1500:
    svc = aws("ecs", "describe-services", "--cluster", CLUSTER, "--services", SERVICE)["services"][0]
    deps = svc["deployments"]
    primary = next(d for d in deps if d["status"] == "PRIMARY")
    state = (primary["rolloutState"], primary["taskDefinition"].rsplit("/", 1)[-1], primary.get("failedTasks", 0), len(deps))
    if state != last:
        mark(f"デプロイ: rolloutState={state[0]} 主の版={state[1]} 失敗タスク={state[2]} デプロイ数={state[3]}")
        last = state
    probes.append((time.time() - T0, health()))
    if primary["taskDefinition"] == good_arn and len(deps) == 1 and primary["rolloutState"] == "COMPLETED":
        mark("元の版に戻って、安定した")
        break
    time.sleep(5)

bad = [(round(t), c) for t, c in probes if c != 200]
mark(f"/health の確認 {len(probes)} 回のうち、200 以外 {len(bad)} 回 {bad[:5]}")
aws("ecs", "deregister-task-definition", "--task-definition", bad_arn)
mark("登録した版を取り消した")
