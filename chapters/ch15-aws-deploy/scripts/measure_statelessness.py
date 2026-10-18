"""api が複数台のとき、承認フローが壊れるかを測る。

  承認待ちを作る(POST /analysis)→ その approval_id で承認を送る(POST /approvals/{id}、reject)
を N 回。ALB はリクエストを台に振り分けるので、承認待ちを作った台と、承認を受ける台が違うことがある。
使い方: measure_statelessness.py <ALB のホスト名> [回数]
"""
import collections
import json
import sys
import urllib.error
import urllib.request

HOST = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 10


def post(path: str, body: dict):
    req = urllib.request.Request(
        f"http://{HOST}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


results = collections.Counter()
for i in range(N):
    status, first = post("/analysis", {
        "question": "注文 O0001 のレビュー依頼を作成してください。理由は割引率の確認です。",
        "session_id": f"statelessness-{i}",
    })
    if first.get("status") != "approval_required":
        results["承認待ちが作れなかった"] += 1
        continue
    code, second = post(f"/approvals/{first['approval']['approval_id']}", {"decision": "reject"})
    outcome = "承認が通った" if code == 200 else f"失敗 {code} {second.get('error', {}).get('code')}"
    results[outcome] += 1
    print(f"{i + 1:2d}/{N}: {outcome}", flush=True)

print(dict(results))
