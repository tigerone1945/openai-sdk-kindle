"""評価の実行: 稼働中の API(手元の Compose でも、AWS の ALB でも)に、HTTP で質問を送って判定する。

  python -m evaluation.runner --url http://127.0.0.1:8000 --runs 3 --report report.json

同じケースを --runs 回ずつ実行する。LLM の出力は毎回少し違うので、「1 回通った」では足りない。
通る割合(pass rate)が 100% でないケースは flaky(不安定)として報告する。
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import checks
from .ground_truth import truth

CASES = Path(__file__).with_name("cases.json")


def post(base: str, path: str, body: dict, timeout: float = 150):
    req = urllib.request.Request(f"{base}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)
    except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
        # 1 件の時間切れで、評価全体を落とさない。「届かなかった」という失敗として数える(状態 0)
        return 0, {"error": {"code": "client_unreachable", "message": type(e).__name__}}


def run_case(base: str, case: dict, run_no: int, facts: dict) -> dict:
    session = f"eval-{case['id']}-{run_no}-{uuid.uuid4().hex[:6]}"
    started = time.perf_counter()
    kind = case["kind"]
    request_ids = []
    raw: list = []  # 失敗の分析用に、返ってきた本体を残す(失敗した実行だけレポートに出す)

    if kind == "analysis":
        status, body = post(base, "/analysis", {"question": case["question"], "session_id": session})
        request_ids.append(body.get("request_id") or body.get("error", {}).get("request_id"))
        raw.append(body)
        verdict = (checks.check_analysis(body["result"], case["expect"], facts) if status == 200 and body.get("status") == "completed"
                   else checks.Verdict(False, [f"分析が完了しなかった: HTTP {status} {body.get('error', {}).get('code') or body.get('status')}"]))

    elif kind == "conversation":
        verdict = checks.Verdict(True)
        for turn in case["turns"]:
            status, body = post(base, "/analysis", {"question": turn["question"], "session_id": session})
            request_ids.append(body.get("request_id") or body.get("error", {}).get("request_id"))
            raw.append(body)
            if status != 200 or body.get("status") != "completed":
                verdict = checks.Verdict(False, [f"会話の途中で失敗: HTTP {status}"])
                break
            if "expect" in turn:
                v = checks.check_analysis(body["result"], {**turn["expect"]}, facts)
                verdict.failures += v.failures
                verdict.warnings += v.warnings
                verdict.passed = verdict.passed and v.passed

    elif kind == "blocked":
        status, body = post(base, "/analysis", {"question": case["question"], "session_id": session})
        request_ids.append(body.get("error", {}).get("request_id") or body.get("request_id"))
        raw.append(body)
        verdict = checks.check_blocked(status, body)

    elif kind == "approval":
        status, body = post(base, "/analysis", {"question": case["question"], "session_id": session})
        request_ids.append(body.get("request_id"))
        raw.append(body)
        verdict = checks.check_approval(status, body, case["expect"])
        if verdict.passed:  # 到達したら、却下して再開できることまで確かめる(実際の登録は行わない)
            status, resumed = post(base, f"/approvals/{body['approval']['approval_id']}", {"decision": "reject"})
            if status != 200 or resumed.get("status") != "completed":
                verdict = checks.Verdict(False, [f"却下後の再開に失敗: HTTP {status}"])
    else:
        raise ValueError(f"未知の kind: {kind}")

    return {"case": case["id"], "run": run_no, "passed": verdict.passed, "failures": verdict.failures,
            "warnings": verdict.warnings, "seconds": round(time.perf_counter() - started, 1), "request_ids": request_ids,
            **({} if verdict.passed else {"raw": raw})}


def summarize(results: list[dict]) -> dict:
    by_case: dict[str, list[bool]] = {}
    for r in results:
        by_case.setdefault(r["case"], []).append(r["passed"])
    per_case = {c: {"pass_rate": sum(v) / len(v), "runs": len(v)} for c, v in by_case.items()}
    return {
        "overall_pass_rate": sum(r["passed"] for r in results) / len(results),
        "cases": per_case,
        "flaky": sorted(c for c, s in per_case.items() if 0 < s["pass_rate"] < 1),
        "always_failing": sorted(c for c, s in per_case.items() if s["pass_rate"] == 0),
        "total_runs": len(results),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--cases", help="カンマ区切りの case id(省略で全部)")
    ap.add_argument("--smoke", action="store_true", help="smoke 印のケースだけ(デプロイ直後の確認用。データ・承認・拒否の 3 経路)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--threshold", type=float, default=1.0, help="全体の pass rate がこれ未満なら、終了コード 1")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args(argv)

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    if args.smoke:
        cases = [c for c in cases if c.get("smoke")]
    facts = truth()
    jobs = [(c, n) for c in cases for n in range(1, args.runs + 1)]

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda j: run_case(args.url.rstrip("/"), j[0], j[1], facts), jobs))

    summary = summarize(results)
    for case_id, s in summary["cases"].items():
        print(f"{'OK  ' if s['pass_rate'] == 1 else 'FAIL'} {case_id:20s} {s['pass_rate']:.0%} ({s['runs']} 回)")
    for r in results:
        for f in r["failures"]:
            print(f"   - {r['case']}#{r['run']}: {f}")
    print(f"\n全体: {summary['overall_pass_rate']:.1%} / flaky: {summary['flaky']} / 常に失敗: {summary['always_failing']}")

    if args.report:
        args.report.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if summary["overall_pass_rate"] >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
