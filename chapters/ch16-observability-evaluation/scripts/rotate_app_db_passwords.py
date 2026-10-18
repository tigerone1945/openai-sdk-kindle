"""アプリ用 DB パスワード(ro・rw)のローテーションを、手順どおりに実行し、その間の利用者の失敗を数える。

  python rotate_app_db_passwords.py <ALB のホスト名>

手順(PostgreSQL の役割は、パスワードを 1 つしか持てない):
  ① 新しい値を作る(人は見ない)  ② Secrets Manager に新しい値を入れる
  ③ マイグレーション用のタスクを実行する(起動時に、新しい値を受け取り、migrate.py が ALTER ROLE で DB に反映する)
  ④ api を再デプロイ(新しいタスクが、新しい値を受け取る)
新しい値を、コマンドラインにも、タスクの command にも、画面にも出さない(ECS の API や CloudTrail に残らない)。
③〜④ の間、まだ古い値を持つタスクは、「新しく張る接続」に失敗しうる(すでに張った接続は使い続けられる)。
その窓の大きさを、利用者のふりをして測る。RDS の管理者のパスワードは、RDS 自身が自動でローテーションする(別)。
"""
import json
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT = "ai-agent-practice"
CLUSTER, SERVICE = f"{PROJECT}-cluster", f"{PROJECT}-api"
ALB = sys.argv[1]
T0 = time.time()
HERE = Path(__file__).parent


def mark(msg):
    print(f"[{time.time() - T0:6.0f}s] {msg}", flush=True)


def aws(*args):
    r = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[:300])
    return json.loads(r.stdout) if r.stdout.strip() else None


def ask(i):
    body = json.dumps({"question": "地域別の売上を教えてください", "session_id": f"rot-{i}-{int(time.time())}"}).encode()
    req = urllib.request.Request(f"http://{ALB}/analysis", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, None
    except urllib.error.HTTPError as e:
        return e.code, json.load(e).get("error", {}).get("code")
    except Exception as e:  # noqa: BLE001
        return type(e).__name__, None


stop, results = threading.Event(), []


def user(worker):
    n = 0
    while not stop.is_set():
        n += 1
        results.append((time.time() - T0, ask(f"{worker}-{n}")))
        stop.wait(1)


def wait_stable(limit=420):
    start = time.time()
    while time.time() - start < limit:
        deps = aws("ecs", "describe-services", "--cluster", CLUSTER, "--services", SERVICE)["services"][0]["deployments"]
        if len(deps) == 1 and deps[0]["rolloutState"] in ("COMPLETED", "FAILED"):
            return deps[0]["rolloutState"]
        time.sleep(10)


# 利用者を 2 人(同時に 2 本)走らせる
for w in ("a", "b"):
    threading.Thread(target=user, args=(w,), daemon=True).start()
time.sleep(15)
mark(f"平常時: {[r for _, r in results]}")

# ① 新しい値(画面にも、コマンドラインにも出さない)
new = {"ro": secrets.token_hex(24), "rw": secrets.token_hex(24)}

# ② Secrets Manager(この時点では、DB もタスクも古い値のまま)
aws("secretsmanager", "put-secret-value", "--secret-id", f"{PROJECT}/db-ro-password", "--secret-string", new["ro"])
aws("secretsmanager", "put-secret-value", "--secret-id", f"{PROJECT}/db-rw-password", "--secret-string", new["rw"])
mark("② Secrets Manager に新しい値を入れた(DB・稼働中のタスクは、まだ古い値)")

# ③ DB の役割を、新しい値に合わせる(migrate タスクが、起動時に新しい値を受け取る)
t_migrate_start = time.time() - T0
out = subprocess.run([str(HERE / "run_migrate.sh")], capture_output=True, text=True)
mark(f"③ マイグレーションのタスク: {'終了コード 0' if '終了コード: 0' in out.stdout else out.stdout[-200:] + out.stderr[-200:]}")
t_migrate_end = time.time() - T0

# ④ 再デプロイ
aws("ecs", "update-service", "--cluster", CLUSTER, "--service", SERVICE, "--force-new-deployment")
mark("④ 再デプロイを開始")
state = wait_stable()
mark(f"④ ECS のデプロイ = {state}")
t_done = time.time() - T0
time.sleep(20)
stop.set()

bad = [(round(t), r) for t, r in results if r[0] != 200]


def window(lo, hi):
    return sum(1 for t, r in results if lo <= t < hi), sum(1 for t, r in results if lo <= t < hi and r[0] != 200)


phases = {
    "①〜②(Secrets 更新後、DB はまだ古い値)": window(0, t_migrate_start),
    "③ マイグレーションのタスクの実行中(この間に ALTER ROLE が走る)": window(t_migrate_start, t_migrate_end),
    "④ 再デプロイの間(古いタスクと新しいタスクが混在)": window(t_migrate_end, t_done),
}
print(json.dumps({
    "利用者のリクエスト合計": len(results),
    "失敗": len(bad), "失敗の内訳": sorted({str(r) for _, r in bad}), "失敗した時刻(秒)": [t for t, _ in bad],
    "局面ごとの(リクエスト数, 失敗数)": {k: list(v) for k, v in phases.items()},
}, ensure_ascii=False, indent=1))
