"""Agent Service:APIとAgentの間の層。HTTPを知らず、Agentの内部も外へ出さない。

APIは、ここが返す結果(AnalysisOutcome)と例外だけを知る。
"""
import json
import logging
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from agents import Runner, RunState, SQLiteSession, trace
from agents.exceptions import InputGuardrailTripwireTriggered

import agent_service as core
from agent_service import SalesAnalysisResult

logger = logging.getLogger("sales_agent.service")

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


# --- 承認待ちの保管:RunStateはサーバー側にだけ置く -----------------


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

    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO pending_approvals VALUES (?, ?, ?, ?)",
            (approval_id, session_id, state, time.time()),
        )

    return approval_id


def take_pending(approval_id: str) -> tuple[str, str]:
    """取り出すと同時に削除する。同じ承認は、一度しか使えない。"""
    oldest_allowed = time.time() - APPROVAL_TTL_SECONDS

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
    session = SQLiteSession(session_id, str(core.SESSION_DB_PATH))

    try:
        with trace(workflow_name="sales_analysis_api", group_id=session_id):
            result = await Runner.run(
                core.manager_agent, question, session=session
            )
    except InputGuardrailTripwireTriggered as e:
        # 判定理由はLLMの出力なので、外へは返さずログにだけ残す。
        logger.info("out_of_scope: %s", e.guardrail_result.output.output_info)
        raise OutOfScopeError from e

    return _to_outcome(result, session_id)


async def resolve_approval(approval_id: str, approve: bool) -> AnalysisOutcome:
    session_id, state_text = take_pending(approval_id)

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

    session = SQLiteSession(session_id, str(core.SESSION_DB_PATH))

    with trace(workflow_name="sales_analysis_api", group_id=session_id):
        result = await Runner.run(core.manager_agent, state, session=session)

    return _to_outcome(result, session_id)
