"""HTTP API:契約(Request / Response / Error)を定義し、Agent Serviceを呼ぶ。"""
import asyncio
import logging
import os
import uuid
from typing import Literal

import openai
from agents.exceptions import AgentsException
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import service
from agent_service import AnalysisType

logger = logging.getLogger("sales_agent.api")

ANALYSIS_TIMEOUT_SECONDS = float(os.getenv("ANALYSIS_TIMEOUT_SECONDS", "120"))

OUT_OF_SCOPE_MESSAGE = (
    "この Application は、売上・受注データの分析に関する質問だけに答えます。"
)

app = FastAPI(title="AI Sales Analysis API", version="1.0.0")


# --- Contract ---------------------------------------------------


class AnalysisRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # session_id は DB のキーになる。使える文字と長さを契約で制限する。
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")


class AnalysisResult(BaseModel):
    analysis_type: AnalysisType
    result_summary: str
    key_findings: list[str]
    next_action: str


class ApprovalItem(BaseModel):
    tool: str
    arguments: dict[str, str | int | float | bool | None]


class ApprovalRequest(BaseModel):
    approval_id: str
    items: list[ApprovalItem]


class AnalysisResponse(BaseModel):
    # request_id は後から足した項目。古いクライアントは知らない項目を
    # 無視するので、既存の項目が変わらない限り、壊れない(追加は互換)。
    request_id: str
    status: Literal["completed", "approval_required"]
    result: AnalysisResult | None = None
    approval: ApprovalRequest | None = None


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody


ERROR_RESPONSES = {
    422: {"model": ErrorResponse, "description": "入力が不正、または範囲外の質問"},
    404: {"model": ErrorResponse, "description": "承認待ちが見つからない"},
    502: {"model": ErrorResponse, "description": "Agent の実行に失敗"},
    503: {"model": ErrorResponse, "description": "モデルを利用できない(再試行可)"},
    504: {"model": ErrorResponse, "description": "時間内に完了しなかった"},
}


# --- Error Model ------------------------------------------------


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(request: Request, status_code: int, code: str, message: str):
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
    )


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(ApiError)
async def handle_api_error(request: Request, exc: ApiError):
    return error_response(request, exc.status_code, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    # どの項目が不正かだけを返す。入力値そのものは返さない。
    fields = ", ".join(sorted({".".join(map(str, e["loc"][1:])) for e in exc.errors()}))
    return error_response(request, 422, "validation_error", f"不正な項目: {fields}")


@app.exception_handler(Exception)
async def handle_unexpected(request: Request, exc: Exception):
    # 内部の例外は返さない。詳細はログに残し、request_id で突き合わせる。
    logger.exception("unexpected error request_id=%s", request.state.request_id)
    return error_response(request, 500, "internal_error", "内部エラーが発生しました。")


async def run_guarded(coro) -> service.AnalysisOutcome:
    """Serviceの呼び出しを、時間制限と例外の対応づけで包む。"""
    try:
        async with asyncio.timeout(ANALYSIS_TIMEOUT_SECONDS):
            return await coro
    except service.OutOfScopeError:
        raise ApiError(422, "out_of_scope", OUT_OF_SCOPE_MESSAGE)
    except service.ApprovalNotFoundError:
        raise ApiError(404, "approval_not_found", "承認待ちが見つかりません。")
    except TimeoutError:
        raise ApiError(504, "timeout", "時間内に完了しませんでした。")
    except openai.APIError:
        raise ApiError(503, "model_unavailable", "モデルを利用できません。時間をおいて再試行してください。")
    except AgentsException:
        raise ApiError(502, "agent_failed", "分析を完了できませんでした。")


def to_response(request: Request, outcome: service.AnalysisOutcome) -> AnalysisResponse:
    request_id = request.state.request_id

    if outcome.pending is not None:
        return AnalysisResponse(
            request_id=request_id,
            status="approval_required",
            approval=ApprovalRequest(
                approval_id=outcome.pending.approval_id,
                items=[
                    ApprovalItem(tool=i.tool, arguments=i.arguments)
                    for i in outcome.pending.items
                ],
            ),
        )

    return AnalysisResponse(
        request_id=request_id,
        status="completed",
        result=AnalysisResult(**outcome.result.model_dump()),
    )


# --- Endpoints --------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analysis", response_model=AnalysisResponse, responses=ERROR_RESPONSES)
async def analyze(body: AnalysisRequest, request: Request) -> AnalysisResponse:
    outcome = await run_guarded(service.run_analysis(body.question, body.session_id))
    return to_response(request, outcome)


@app.post(
    "/approvals/{approval_id}",
    response_model=AnalysisResponse,
    responses=ERROR_RESPONSES,
)
async def decide(
    approval_id: str, body: ApprovalDecision, request: Request
) -> AnalysisResponse:
    outcome = await run_guarded(
        service.resolve_approval(approval_id, body.decision == "approve")
    )
    return to_response(request, outcome)
