"""Streamlit画面を、APIを差し替えて(LLMなしで)確認する。

画面はAgentをimportしない。HTTPの応答だけで動くことが、境界の確認になる。
"""
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parent.parent / "src" / "ui" / "app.py")
REQUEST = httpx.Request("POST", "http://api/analysis")

RESULT = {
    "request_id": "r" * 32,
    "status": "completed",
    "result": {
        "analysis_type": "category_sales",
        "result_summary": "IT機器が最大です。",
        "key_findings": ["発見A", "発見B"],
        "next_action": "商品別を確認",
    },
    "approval": None,
}

APPROVAL = {
    "request_id": "r" * 32,
    "status": "approval_required",
    "result": None,
    "approval": {
        "approval_id": "ap1",
        "items": [{"tool": "create_review_request", "arguments": {"order_id": "O0001", "reason": "確認"}}],
    },
}


def reply(status, body):
    return httpx.Response(status, json=body, request=REQUEST)


class FakeApi:
    """httpx.post の呼び出しを記録し、積んだ応答を順に返す。"""

    def __init__(self):
        self.log = []
        self.queue = []

    def post(self, url, json=None, timeout=None):
        self.log.append((url, json))
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def __getitem__(self, index):
        return self.log[index]


@pytest.fixture
def calls(monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(httpx, "post", api.post)
    return api


def text(at):
    return " ".join(m.value for m in at.markdown)


def test_ui_does_not_import_the_agent():
    source = Path(APP).read_text(encoding="utf-8")
    assert "agent_service" not in source and "from agents" not in source


def test_question_goes_through_the_api(calls):
    calls.queue.append(reply(200, RESULT))
    at = AppTest.from_file(APP).run()
    at.chat_input[0].set_value("カテゴリ別の売上").run()

    url, payload = calls[0]
    assert url.endswith("/analysis")
    assert payload["question"] == "カテゴリ別の売上" and payload["session_id"].startswith("sales_")
    assert "IT機器が最大です" in text(at) and not at.exception


def test_approval_is_shown_and_can_be_approved(calls):
    calls.queue += [reply(200, APPROVAL), reply(200, RESULT)]
    at = AppTest.from_file(APP).run()
    at.chat_input[0].set_value("O0001を登録して").run()

    assert at.warning and "O0001" in str(at.json[0].value)
    assert [b.label for b in at.button if b.label in ("承認する", "却下する")] == ["承認する", "却下する"]

    next(b for b in at.button if b.label == "承認する").click().run()
    assert calls[1][0].endswith("/approvals/ap1") and calls[1][1] == {"decision": "approve"}
    assert not at.warning and "IT機器が最大です" in text(at)


def test_reject_sends_reject(calls):
    calls.queue += [reply(200, APPROVAL), reply(200, RESULT)]
    at = AppTest.from_file(APP).run()
    at.chat_input[0].set_value("O0001を登録して").run()
    next(b for b in at.button if b.label == "却下する").click().run()
    assert calls[1][1] == {"decision": "reject"}


def test_api_error_is_shown_without_traceback(calls):
    error = {"error": {"code": "out_of_scope", "message": "売上の質問だけに答えます。", "request_id": "abcdef1234567890"}}
    calls.queue.append(reply(422, error))
    at = AppTest.from_file(APP).run()
    at.chat_input[0].set_value("天気は？").run()

    assert "売上の質問だけに答えます" in text(at) and "abcdef12" in text(at)
    assert not at.exception


@pytest.mark.parametrize("failure,message", [
    (httpx.ConnectError("refused"), "接続できませんでした"),
    (httpx.ReadTimeout("slow"), "応答がありませんでした"),
])
def test_network_failure_is_shown_without_traceback(calls, failure, message):
    calls.queue.append(failure)
    at = AppTest.from_file(APP).run()
    at.chat_input[0].set_value("売上").run()
    assert message in text(at) and not at.exception


def test_non_json_error_is_handled(calls):
    calls.queue.append(httpx.Response(502, text="<html>Bad Gateway</html>", request=REQUEST))
    at = AppTest.from_file(APP).run()
    at.chat_input[0].set_value("売上").run()
    assert "予期しない応答" in text(at) and "Bad Gateway" not in text(at)
