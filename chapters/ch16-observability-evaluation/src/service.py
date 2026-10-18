"""Agent Service:APIとAgentの間の層。HTTPを知らず、Agentの内部も外へ出さない。

APIは、ここが返す結果(AnalysisOutcome)と例外だけを知る。

第16章の変更: 実行の結果(成功・失敗・拒否)と所要時間を、構造化ログに残す。質問・回答の中身は残さない。
第15章の変更: 状態(承認待ち・会話履歴)の保存先を、DB_BACKEND で選ぶ。
  postgres: RDS(タスクが入れ替わっても、何台あっても、同じ状態が見える)
  sqlite  : 手元のファイル(第11章までと同じ)
"""
import json
import logging
import os
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from agents import Runner, RunState, SQLiteSession, trace
from agents.exceptions import InputGuardrailTripwireTriggered
from psycopg import InterfaceError as PgInterfaceError
from psycopg import OperationalError as PgOperationalError
from sqlalchemy import Engine, text
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import agent_service as core
import db
from repository import StorageUnavailableError, is_unavailable
from observability import apply_privacy_policy, log_event
from agent_service import SalesAnalysisResult

logger = logging.getLogger("sales_agent.service")

# 質問・回答を OpenAI 側に保存させない(import 時に、すべての Agent へ)
PRIVATE_AGENTS = apply_privacy_policy(core)

APPROVALS_DB_PATH = Path("data/approvals.db")
APPROVAL_TTL_SECONDS = 3600


class OutOfScopeError(Exception):
    """Guardrailが、範囲外の質問として止めた。"""


class ApprovalNotFoundError(Exception):
    """承認待ちが、存在しない・期限切れ・解決済みのいずれか(区別しない)。"""


@dataclass(frozen=True)
class PendingItem:
    tool: str
    arguments: dict


@dataclass(frozen=True)
class PendingApproval:
    approval_id: str
    items: list[PendingItem]


@dataclass(frozen=True)
class AnalysisOutcome:
    """completed なら result、approval_required なら pending が入る。"""

    result: SalesAnalysisResult | None
    pending: PendingApproval | None


# --- 状態の保管 -------------------------------------------------
# RunState(Agent の一時停止した状態)は、サーバー側にだけ置く。クライアントには ID しか渡さない。


def _storage_failure(error: BaseException | None) -> bool:
    """例外か、その原因のどれかが、保存先に繋がらない障害か(再試行で直りうるもの)。

    第13章の Repository は、Tool が使う DB の障害を StorageUnavailableError に翻訳した。
    第15章で足した「状態の保存先」(承認待ち・会話履歴)には、その翻訳が無かった。
    DB が使えないと、API は 503 ではなく 500 を返した(第16章の障害演習で発見)。
    """
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, (PgOperationalError, PgInterfaceError, PoolTimeoutError, InterfaceError)):
            return True
        if isinstance(error, OperationalError) and is_unavailable(error, "postgresql"):
            return True
        error = error.__cause__ or error.__context__
    return False


@contextmanager
def storage_failures_as_unavailable():
    try:
        yield
    except StorageUnavailableError:
        raise
    except Exception as e:
        if _storage_failure(e):
            raise StorageUnavailableError("保存先を利用できません。") from e
        raise


def use_database() -> bool:
    return os.environ.get("DB_BACKEND", "sqlite") == "postgres"


@lru_cache(maxsize=1)
def _state_engine() -> Engine:
    """状態の読み書き用の接続。書き込み用の役割(agent_rw)を使う。DDL ができる資格情報は持たない。"""
    return db.make_postgres_engine(db.postgres_url("rw"))


@lru_cache(maxsize=1)
def _state_async_engine() -> AsyncEngine:
    """会話履歴(SDK の SQLAlchemySession)用の、非同期の接続。同じ役割・同じ設定。"""
    return create_async_engine(
        db.postgres_url("rw"), connect_args={"connect_timeout": 5}, **db.POOL_SETTINGS
    )


def _connect() -> sqlite3.Connection:
    APPROVALS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(APPROVALS_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_approvals (
            approval_id  TEXT PRIMARY KEY,
            session_id   TEXT NOT NULL,
            state        TEXT NOT NULL,
            created_at   REAL NOT NULL
        )
        """
    )
    return conn


def save_pending(session_id: str, state: str) -> str:
    approval_id = uuid.uuid4().hex

    if use_database():
        with storage_failures_as_unavailable(), _state_engine().begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO pending_approvals (approval_id, session_id, state, created_at) "
                    "VALUES (:a, :s, :st, :t)"
                ),
                {"a": approval_id, "s": session_id, "st": state, "t": time.time()},
            )
        return approval_id

    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO pending_approvals VALUES (?, ?, ?, ?)",
            (approval_id, session_id, state, time.time()),
        )

    return approval_id


def take_pending(approval_id: str) -> tuple[str, str]:
    """取り出すと同時に削除する。同じ承認は、一度しか使えない(台が何台あっても)。"""
    oldest_allowed = time.time() - APPROVAL_TTL_SECONDS

    if use_database():
        with storage_failures_as_unavailable(), _state_engine().begin() as conn:
            # 期限切れは、残さずに掃除する。
            conn.execute(
                text("DELETE FROM pending_approvals WHERE created_at < :oldest"),
                {"oldest": oldest_allowed},
            )
            # DELETE ... RETURNING は 1 文で完結する。2 台が同時に同じ承認を取りに来ても、片方だけが行を得る。
            row = conn.execute(
                text(
                    "DELETE FROM pending_approvals WHERE approval_id = :a "
                    "RETURNING session_id, state"
                ),
                {"a": approval_id},
            ).first()
        if row is None:
            raise ApprovalNotFoundError(approval_id)
        return row[0], row[1]

    with closing(_connect()) as conn, conn:
        # 期限切れは、残さずに掃除する。
        conn.execute(
            "DELETE FROM pending_approvals WHERE created_at < ?",
            (oldest_allowed,),
        )
        row = conn.execute(
            "DELETE FROM pending_approvals WHERE approval_id = ? "
            "RETURNING session_id, state",
            (approval_id,),
        ).fetchone()

    if row is None:
        raise ApprovalNotFoundError(approval_id)

    return row


def open_session(session_id: str):
    """会話履歴。DB なら全タスクで共有され、タスクが入れ替わっても残る。"""
    if use_database():
        from agents.extensions.memory import SQLAlchemySession

        return SQLAlchemySession(session_id, engine=_state_async_engine())
    return SQLiteSession(session_id, str(core.SESSION_DB_PATH))


# --- 実行 -----------------------------------------------------


def _to_outcome(result, session_id: str) -> AnalysisOutcome:
    if not result.interruptions:
        return AnalysisOutcome(result=result.final_output, pending=None)

    items = [
        PendingItem(tool=i.name, arguments=json.loads(i.arguments))
        for i in result.interruptions
    ]
    approval_id = save_pending(session_id, result.to_state().to_string())

    for item in items:
        core.write_audit_log(
            "approval_requested",
            approval_id=approval_id,
            tool=item.tool,
            arguments=item.arguments,
        )

    return AnalysisOutcome(
        result=None,
        pending=PendingApproval(approval_id=approval_id, items=items),
    )


async def run_analysis(question: str, session_id: str) -> AnalysisOutcome:
    session = open_session(session_id)
    started = time.perf_counter()

    try:
        with trace(workflow_name="sales_analysis_api", group_id=session_id):
            result = await Runner.run(
                core.manager_agent, question, session=session
            )
    except InputGuardrailTripwireTriggered as e:
        # 判定理由はLLMの出力なので、外へは返さずログにだけ残す。
        logger.info("out_of_scope: %s", e.guardrail_result.output.output_info)
        log_event("analysis_rejected", reason="out_of_scope", session_id=session_id, duration_ms=_ms(started))
        raise OutOfScopeError from e
    except Exception as e:
        # 原因の「種類」だけを残す(メッセージには、データの断片が入りうる)
        log_event("analysis_failed", level="error", session_id=session_id,
                  error_type=type(e).__name__, duration_ms=_ms(started),
                  storage_unavailable=_storage_failure(e))
        if _storage_failure(e):
            raise StorageUnavailableError("保存先を利用できません。") from e
        raise

    with storage_failures_as_unavailable():
        outcome = _to_outcome(result, session_id)
    _log_outcome(outcome, session_id, started)
    return outcome


async def resolve_approval(approval_id: str, approve: bool) -> AnalysisOutcome:
    started = time.perf_counter()
    try:
        session_id, state_text = take_pending(approval_id)
    except ApprovalNotFoundError:
        log_event("approval_not_found", level="warning", duration_ms=_ms(started))
        raise

    state = await RunState.from_string(core.manager_agent, state_text)

    for interruption in state.get_interruptions():
        if approve:
            state.approve(interruption)
        else:
            state.reject(interruption)

        core.write_audit_log(
            "approved" if approve else "rejected",
            approval_id=approval_id,
            tool=interruption.name,
        )

    session = open_session(session_id)

    try:
        with trace(workflow_name="sales_analysis_api", group_id=session_id):
            result = await Runner.run(core.manager_agent, state, session=session)
    except Exception as e:
        log_event("analysis_failed", level="error", session_id=session_id,
                  error_type=type(e).__name__, duration_ms=_ms(started), resumed_from_approval=True,
                  storage_unavailable=_storage_failure(e))
        if _storage_failure(e):
            raise StorageUnavailableError("保存先を利用できません。") from e
        raise

    with storage_failures_as_unavailable():
        outcome = _to_outcome(result, session_id)
    _log_outcome(outcome, session_id, started, resumed_from_approval=True)
    return outcome


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _log_outcome(outcome: AnalysisOutcome, session_id: str, started: float, **extra) -> None:
    if outcome.pending is not None:
        log_event("approval_required", session_id=session_id, tools=[i.tool for i in outcome.pending.items],
                  duration_ms=_ms(started), **extra)
    else:
        log_event("analysis_completed", session_id=session_id, analysis_type=outcome.result.analysis_type,
                  duration_ms=_ms(started), **extra)
