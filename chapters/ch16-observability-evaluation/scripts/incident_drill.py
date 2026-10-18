"""障害の演習: DB のパスワードを間違った値に差し替えて、何が見え、何が見えないかを測る。

  python incident_drill.py <ALB のホスト名>

手順: ①(間違った値を入れる)→ ② 再デプロイ → ③ 利用者のふりをして 3 秒ごとに質問 → ④ 各種の検知を記録 → ⑤ 元の値に戻す → ⑥ 復旧を記録
元の値は、Secrets Manager が持つ 1 つ前の版(AWSPREVIOUS)から戻す。値を画面にも変数にも出さない。
自分の AWS 環境だけで使うこと。
"""
import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

PROJECT = "ai-agent-practice"
SECRETS = [f"{PROJECT}/db-ro-password", f"{PROJECT}/db-rw-password"]
CLUSTER, SERVICE = f"{PROJECT}-cluster", f"{PROJECT}-api"
ALB = sys.argv[1]
T0 = time.time()
timeline: list[tuple[float, str]] = []


def mark(event: str) -> None:
    timeline.append((time.time() - T0, event))
    print(f"[{timeline[-1][0]:6.0f}s] {event}", flush=True)


def aws(*args, ok_fail=False):
    r = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True)
    if r.returncode != 0 and not ok_fail:
        raise RuntimeError(r.stderr[:300])
    return json.loads(r.stdout) if r.stdout.strip() else None


def alarm_states() -> dict[str, str]:
    return {a["AlarmName"].removeprefix(f"{PROJECT}-"): a["StateValue"] for a in aws("cloudwatch", "describe-alarms", "--alarm-name-prefix", PROJECT)["MetricAlarms"]}


def post(path, body, timeout=60):
    req = urllib.request.Request(f"http://{ALB}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)
    except Exception as e:  # noqa: BLE001
        return type(e).__name__, {}


def get(path):
    try:
        with urllib.request.urlopen(f"http://{ALB}{path}", timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:  # noqa: BLE001
        return type(e).__name__


stop = threading.Event()
traffic: list[tuple[float, object]] = []


def user():
    n = 0
    while not stop.is_set():
        n += 1
        status, body = post("/analysis", {"question": "地域別の売上を教えてください", "session_id": f"drill-{n}-{int(time.time())}"})
        code = body.get("error", {}).get("code") if isinstance(status, int) and status >= 400 else None
        traffic.append((time.time() - T0, (status, code)))
        stop.wait(3)


def rollout_state():
    return aws("ecs", "describe-services", "--cluster", CLUSTER, "--services", SERVICE)["services"][0]["deployments"]


def wait_stable(label, limit=420):
    start = time.time()
    while time.time() - start < limit:
        deps = rollout_state()
        if len(deps) == 1 and deps[0]["rolloutState"] in ("COMPLETED", "FAILED"):
            mark(f"{label}: ECS のデプロイ = {deps[0]['rolloutState']}")
            return deps[0]["rolloutState"]
        time.sleep(10)
    mark(f"{label}: 時間切れ")


mark(f"開始。アラームの初期状態: {alarm_states()}")
threading.Thread(target=user, daemon=True).start()
time.sleep(20)
base = [c for _, c in traffic]
mark(f"平常時の利用者の結果: {base}")

# ① 間違った値を入れる(元の値は AWSPREVIOUS として残る)
for s in SECRETS:
    aws("secretsmanager", "put-secret-value", "--secret-id", s, "--secret-string", "wrong-password-by-mistake")
mark("① ro・rw のパスワードを、間違った値に差し替えた(実運用なら、貼り間違いなど)")
aws("ecs", "update-service", "--cluster", CLUSTER, "--service", SERVICE, "--force-new-deployment")
mark("② 再デプロイを開始")
result = wait_stable("②")
first_bad = next((t for t, c in traffic if t > timeline[-3][0] and c[0] != 200), None)
mark(f"/health={get('/health')}  /ready={get('/ready')}  ← ECS・ALB から見て「正常」か")

# ③ 検知: アラームが ALARM になるまで
alarmed: dict[str, float] = {}
deadline = time.time() + 600
while time.time() < deadline and not {"alb-target-5xx", "analysis-failed"} <= set(alarmed):
    for name, state in alarm_states().items():
        if state == "ALARM" and name not in alarmed:
            alarmed[name] = time.time() - T0
            mark(f"アラーム発報: {name}")
    time.sleep(15)

recent = [c for t, c in traffic if t > timeline[1][0] + 60][-5:]
mark(f"障害中の利用者の結果(直近): {recent}")

# ⑤ 元の値に戻す
for s in SECRETS:
    versions = aws("secretsmanager", "list-secret-version-ids", "--secret-id", s)["Versions"]
    current = next(v["VersionId"] for v in versions if "AWSCURRENT" in v["VersionStages"])
    previous = next(v["VersionId"] for v in versions if "AWSPREVIOUS" in v["VersionStages"])
    aws("secretsmanager", "update-secret-version-stage", "--secret-id", s, "--version-stage", "AWSCURRENT",
        "--move-to-version-id", previous, "--remove-from-version-id", current)
mark("⑤ ro・rw を元の値(1 つ前の版)に戻した")
aws("ecs", "update-service", "--cluster", CLUSTER, "--service", SERVICE, "--force-new-deployment")
t_fix = time.time() - T0
wait_stable("⑤")
first_ok = next((t for t, c in traffic if t > t_fix and c[0] == 200), None)
mark(f"復旧後の最初の成功: {first_ok and round(first_ok - t_fix)} 秒後(再デプロイ開始から)")

# ⑥ アラームが OK に戻るまで
recovered: dict[str, float] = {}
deadline = time.time() + 600
while time.time() < deadline and set(alarmed) - set(recovered):
    for name, state in alarm_states().items():
        if name in alarmed and state == "OK" and name not in recovered:
            recovered[name] = time.time() - T0
            mark(f"アラーム復旧: {name}")
    time.sleep(15)
stop.set()

bad = [(t, c) for t, c in traffic if c[0] != 200]
print("\n=== 要約 ===")
print(json.dumps({
    "利用者のリクエスト": len(traffic), "失敗": len(bad),
    "最初の失敗(秒)": round(bad[0][0]) if bad else None, "最後の失敗(秒)": round(bad[-1][0]) if bad else None,
    "失敗の種類": sorted({str(c) for _, c in bad}),
    "ECS のデプロイ結果(障害の注入時)": result,
    "アラーム発報(秒)": {k: round(v) for k, v in alarmed.items()},
    "アラーム復旧(秒)": {k: round(v) for k, v in recovered.items()},
}, ensure_ascii=False, indent=1))
