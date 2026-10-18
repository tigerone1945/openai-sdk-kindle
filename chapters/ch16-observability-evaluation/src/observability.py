"""構造化ログ(1行1件の JSON)と、HTTP リクエストの記録。

標準出力に出す。コンテナでは CloudWatch Logs が集める(第15章)。
方針: ID・種類・件数・時間は出す。**質問の文章・回答・Tool の引数や結果・資格情報は、出さない。**
(質問には顧客名などが入りうる。Tracing 側の同じ方針は、OPENAI_AGENTS_TRACE_INCLUDE_SENSITIVE_DATA=false。)
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

from agents import Agent, ModelSettings
from fastapi import FastAPI, Request

# これらの名前の項目は、値を見ずに捨てる(うっかり出さないための、最後の網)
FORBIDDEN_FIELDS = frozenset({
    "question", "answer", "result_summary", "key_findings", "next_action",
    "arguments", "tool_output", "password", "api_key", "secret", "token", "authorization",
})


def log_event(event: str, level: str = "info", **fields) -> None:
    dropped = sorted(k for k in fields if k.lower() in FORBIDDEN_FIELDS)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "level": level,
        "event": event,
        **{k: v for k, v in fields.items() if k.lower() not in FORBIDDEN_FIELDS},
    }
    if dropped:
        record["dropped_fields"] = dropped  # 何を捨てたかだけを残す(値は残さない)
    sys.stdout.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def install(app: FastAPI) -> None:
    """すべての HTTP リクエストを、request_completed として 1 行記録する(ヘルスチェックを除く)。"""

    @app.middleware("http")
    async def record_request(request: Request, call_next):
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            # ALB のヘルスチェックは 15 秒ごと × 台数。ログを埋めて、費用と検索の邪魔になるので記録しない
            if request.url.path != "/health":
                route = request.scope.get("route")
                log_event(
                    "request_completed",
                    level="error" if status >= 500 else "info",
                    method=request.method,
                    path=getattr(route, "path", request.url.path),  # /approvals/{approval_id}。ID の値は入れない
                    status=status,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    request_id=getattr(request.state, "request_id", None),
                )


def apply_privacy_policy(module) -> list[str]:
    """module 内のすべての Agent に、store=False を適用する(質問・回答を OpenAI 側に保存させない)。

    Responses API は、既定で、入力と出力を OpenAI 側に保存し、ID で取り出せる(実測: 第16章)。
    これは trace_include_sensitive_data とは別の設定。入れ子の専門 Agent(as_tool)は、自分の model_settings で
    動くので、Manager だけでなく、すべての Agent に付ける。
    OPENAI_STORE_RESPONSES=true なら、何もしない(デバッグで OpenAI のダッシュボードに中身を残したいとき)。
    """
    if os.environ.get("OPENAI_STORE_RESPONSES", "false").lower() == "true":
        return []
    applied = []
    for name, value in vars(module).items():
        if isinstance(value, Agent):
            value.model_settings = value.model_settings.resolve(ModelSettings(store=False))
            applied.append(name)
    return applied
