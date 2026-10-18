"""評価の部品そのものの検査: 正解データ・判定・実行・集計。

「評価が通る」ことは、評価が正しいことの証明にならない。判定が、間違った出力を落とせるかを、ここで確かめる。
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from conftest import SRC
from evaluation import checks, runner
from evaluation.ground_truth import allowed_amounts, truth

T = truth()


def result(summary="", findings=(), type_="region_sales", next_action="次へ"):
    return {"analysis_type": type_, "result_summary": summary, "key_findings": list(findings), "next_action": next_action}


# --- 正解データ ------------------------------------------------------------


def test_ground_truth_matches_the_values_seen_in_earlier_chapters():
    assert T["total"] == 28_298_695 and T["cancelled_count"] == 14 and T["order_count"] == 300
    assert T["region"]["東北"] == 8_439_765 and T["region"]["中部"] == 3_236_170
    assert sum(T["region"].values()) == sum(T["category"].values()) == sum(T["customer_type"].values()) == T["total"]


def test_allowed_amounts_include_values_total_differences_and_sums():
    ok = allowed_amounts(T["region"], T["total"])
    assert 8_439_765 in ok and 28_298_695 in ok and (8_439_765 - 8_373_825) in ok and (8_439_765 + 8_373_825) in ok
    assert 8_439_766 not in ok


# --- 判定: 正しい出力は通り、間違った出力は落とす ----------------------------------


GOOD = result("地域別売上は東北が最大です。", ["東北は8,439,765円", "関西は8,373,825円で、東北との差は65,940円です。",
                                         "九州は4,980,410円、関東は3,268,525円、中部は3,236,170円です。"])
EXPECT_REGION = {"analysis_type": "region_sales", "facts": ["region:東北", "region:中部"], "consistent_with": ["region"]}


def test_correct_answer_passes():
    v = checks.check_analysis(GOOD, EXPECT_REGION, T)
    assert v.passed, v.failures


@pytest.mark.parametrize("mutation,reason", [
    (lambda r: r.update(analysis_type="category_sales"), "種類が違う"),
    (lambda r: r.update(key_findings=["東北は8,439,000円"]), "東北の金額が違う(値が無い)"),
    (lambda r: r.update(result_summary="東北は9,999,999円で最大", key_findings=["中部は3,236,170円", "東北は8,439,765円"]), "同じ項目に、正解にない金額"),
])
def test_wrong_answers_are_caught(mutation, reason):
    bad = json.loads(json.dumps(GOOD))
    mutation(bad)
    assert not checks.check_analysis(bad, EXPECT_REGION, T).passed, reason


def test_a_legitimate_difference_between_two_regions_is_not_flagged():
    text = "関西は8,373,825円で、東北との差は65,940円です"
    allowed = allowed_amounts(T["region"], T["total"])
    assert checks.inconsistent_amounts(text, T["region"], allowed) == []


def test_a_wrong_difference_is_flagged():
    text = "東北との差は65,941円です"
    assert checks.inconsistent_amounts(text, T["region"], allowed_amounts(T["region"], T["total"]))


def test_unknown_amounts_are_recorded_as_warnings_not_failures():
    v = checks.check_analysis(result("東北は8,439,765円。平均は94,329円", []), {"facts": ["region:東北"]}, T)
    assert v.passed and any("94,329" in w for w in v.warnings)


def test_regex_fact_requires_the_cancel_count():
    expect = {"fact_regex": [r"14\s*件"]}
    assert checks.check_analysis(result("キャンセルは14件です"), expect, T).passed
    assert not checks.check_analysis(result("キャンセル件数は集計できません。"), expect, T).passed  # 実機で見た誤答


def test_blocked_and_approval_checks():
    assert checks.check_blocked(422, {"error": {"code": "out_of_scope"}}).passed
    assert not checks.check_blocked(200, {"status": "completed"}).passed
    assert not checks.check_blocked(422, {"error": {"code": "validation_error"}}).passed
    body = {"status": "approval_required", "approval": {"approval_id": "a", "items": [{"tool": "create_review_request", "arguments": {"order_id": "O0001"}}]}}
    ok = {"tool": "create_review_request", "arguments": {"order_id": "O0001"}}
    assert checks.check_approval(200, body, ok).passed
    assert not checks.check_approval(200, body, {**ok, "arguments": {"order_id": "O0002"}}).passed
    assert not checks.check_approval(200, {"status": "completed"}, ok).passed


# --- ケース定義 ---------------------------------------------------------------


def test_every_case_is_well_formed():
    cases = json.loads((SRC / "evaluation/cases.json").read_text(encoding="utf-8"))
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    for c in cases:
        assert c["kind"] in {"analysis", "conversation", "blocked", "approval"}
        if c["kind"] != "conversation":
            assert c["question"]
        for key in (c.get("expect", {}).get("facts", []) + [f for t in c.get("turns", []) for f in t.get("expect", {}).get("facts", [])]):
            group, name = key.split(":")
            assert group == "total" or name in T[group], key  # 正解データに無い項目を、期待していない


def test_cases_cover_every_kind_the_chapter_cares_about():
    kinds = {c["kind"] for c in json.loads((SRC / "evaluation/cases.json").read_text(encoding="utf-8"))}
    assert kinds == {"analysis", "conversation", "blocked", "approval"}


# --- 実行・集計(偽の API サーバーに対して) --------------------------------------


class FakeApi(BaseHTTPRequestHandler):
    behaviour = "good"

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        q = body.get("question", "")
        if self.path.startswith("/approvals/"):
            code, payload = 200, {"request_id": "r", "status": "completed", "result": result("却下しました")}
        elif "天気" in q or "無視" in q or "レストラン" in q:
            code, payload = (422, {"error": {"code": "out_of_scope", "request_id": "r"}}) if FakeApi.behaviour == "good" else (200, {"status": "completed", "request_id": "r", "result": result("晴れです")})
        elif "レビュー" in q:
            order = "O0001" if "O0001" in q else "O0002"
            code, payload = 200, {"request_id": "r", "status": "approval_required", "approval": {"approval_id": "x", "items": [{"tool": "create_review_request", "arguments": {"order_id": order}}]}}
        else:
            text = "東北は8,439,765円" if FakeApi.behaviour == "good" else "集計できません"
            code, payload = 200, {"request_id": "r", "status": "completed", "result": result("売上", [text, "関西は8,373,825円", "九州は4,980,410円", "関東は3,268,525円", "中部は3,236,170円",
                                                                                       "総売上は28,298,695円、キャンセルは14件", "法人は24,256,195円", "個人は4,042,500円",
                                                                                       "IT機器は11,651,680円", "オフィス家具は11,329,340円", "ストレージは2,437,680円", "周辺機器は2,879,995円"], type_="region_sales")}
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def fake_api():
    server = HTTPServer(("127.0.0.1", 0), FakeApi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    FakeApi.behaviour = "good"
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_runner_reports_blocked_and_approval_cases_against_a_well_behaved_api(fake_api, tmp_path):
    report = tmp_path / "r.json"
    code = runner.main(["--url", fake_api, "--runs", "2", "--cases", "blocked-001,blocked-002,blocked-003,approval-001,approval-002", "--report", str(report)])
    data = json.loads(report.read_text())
    assert code == 0 and data["summary"]["overall_pass_rate"] == 1.0 and data["summary"]["total_runs"] == 10


def test_runner_fails_when_the_api_answers_out_of_scope_questions(fake_api, tmp_path):
    FakeApi.behaviour = "bad"
    code = runner.main(["--url", fake_api, "--runs", "1", "--cases", "blocked-001", "--report", str(tmp_path / "r.json")])
    assert code == 1


def test_threshold_decides_the_exit_code(fake_api, tmp_path):
    args = ["--url", fake_api, "--runs", "1", "--cases", "blocked-001", "--report", str(tmp_path / "r.json")]
    FakeApi.behaviour = "bad"
    assert runner.main(args + ["--threshold", "0"]) == 0


def test_summary_marks_flaky_and_always_failing_cases():
    rs = [{"case": "a", "passed": True}, {"case": "a", "passed": False}, {"case": "b", "passed": False}, {"case": "b", "passed": False}, {"case": "c", "passed": True}]
    s = runner.summarize(rs)
    assert s["flaky"] == ["a"] and s["always_failing"] == ["b"] and s["cases"]["c"]["pass_rate"] == 1.0 and s["overall_pass_rate"] == 0.4


def test_failed_runs_keep_the_raw_response_for_failure_analysis(fake_api):
    FakeApi.behaviour = "bad"
    r = runner.run_case(fake_api, {"id": "x", "kind": "blocked", "question": "今日の天気"}, 1, T)
    assert not r["passed"] and r["raw"][0]["status"] == "completed"


def test_a_client_timeout_is_counted_as_a_failure_not_a_crash():
    """実測(第17章): ALB 越しの 1 件が時間切れになり、評価全体が例外で落ちた。1 件の失敗として数える。"""
    import socket
    with socket.socket() as s:  # 受け付けるだけで返事をしないサーバー
        s.bind(("127.0.0.1", 0)); s.listen(1)
        status, body = runner.post(f"http://127.0.0.1:{s.getsockname()[1]}", "/analysis", {"question": "q", "session_id": "s"}, timeout=0.3)
    assert status == 0 and body["error"]["code"] == "client_unreachable"
