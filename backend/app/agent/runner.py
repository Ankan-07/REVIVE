"""Agent entrypoint (BUILDPLAN Phase 4).

``run_agent(case_id)`` drives one case from ``DETECTED`` to a terminal status synchronously (the
deterministic simulator resolves the payment within the run). Tracing is configured first so the
whole run — the graph, the LLM calls, and every ``@traceable`` node/service/tool — lands in one
LangSmith trace tree.

Injection points keep it testable:
* ``session_factory`` — where nodes get their DB sessions (prod: ``SessionLocal``; tests: in-memory).
* ``checkpointer``    — durable state store. Defaults to a SQLite saver at ``checkpoint_db_path``
  (thread_id = case_id, so a case is resumable); tests pass ``MemorySaver`` for hermetic runs. This
  is the seam Phase 6 uses for real ``interrupt()``/resume.
* ``llm_client``      — an injected (fake) OpenAI client for tests; ``None`` uses the real/absent one.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.agent.graph import build_graph
from app.agent.state import initial_state
from app.config import settings
from app.db import SessionLocal
from app.observability import configure_tracing
from app.services import case_run_lock_service

# Ample headroom over the worst-case node count; real termination is enforced by the router/policy.
_RECURSION_LIMIT = 60


def _default_checkpointer():
    """Durable checkpointer: PostgresSaver when Postgres is configured (A1.6), otherwise SqliteSaver."""
    direct_pg_url = settings.supabase_db_url or (
        settings.database_url if settings.database_url.startswith("postgresql") else None
    )

    if direct_pg_url:
        try:
            import psycopg
            from langgraph.checkpoint.postgres import PostgresSaver

            conn_str = direct_pg_url
            if conn_str.startswith("postgresql+psycopg://"):
                conn_str = "postgresql://" + conn_str[len("postgresql+psycopg://"):]
            
            conn = psycopg.connect(conn_str, autocommit=True)
            saver = PostgresSaver(conn)
            saver.setup()
            return saver
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to initialize PostgresSaver (%s); falling back to local SQLite checkpointer.", exc
            )

    # Local fallback for hermetic tests or local dev without Postgres
    import sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect(settings.checkpoint_db_path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def run_agent(
    case_id: str,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
    checkpointer: Optional[object] = None,
    llm_client: Any = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the recovery graph for ``case_id`` and return the final graph state."""
    configure_tracing()

    db = session_factory()
    try:
        acquired, reason, _ = case_run_lock_service.acquire_lock(db, case_id, job_id=job_id)
        if not acquired:
            return {"status": "already_running", "case_id": case_id, "reason": reason}
    finally:
        db.close()

    if checkpointer is None:
        checkpointer = _default_checkpointer()

    graph = build_graph(checkpointer)
    config = {
        "recursion_limit": _RECURSION_LIMIT,
        "configurable": {
            "thread_id": case_id,  # one checkpoint thread per case (resumable in Phase 6)
            "session_factory": session_factory,
            "llm_client": llm_client,
            "diagnose_model": settings.diagnosis_llm_model,
            "plan_model": settings.diagnosis_llm_model,
        },
    }

    result: Dict[str, Any] = {}
    try:
        result = graph.invoke(initial_state(case_id), config)
        return result
    finally:
        is_terminal = bool(result.get("terminal_status"))
        db = session_factory()
        try:
            case_run_lock_service.release_lock(db, case_id, terminal=is_terminal)
        finally:
            db.close()


def resume_agent(
    case_id: str,
    resolution: str,
    *,
    caller: str = "operator",
    session_factory: Callable[[], Session] = SessionLocal,
    checkpointer: Optional[object] = None,
    llm_client: Any = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Resume an escalated/paused recovery graph execution for ``case_id``."""
    configure_tracing()

    db = session_factory()
    try:
        acquired, reason, _ = case_run_lock_service.acquire_lock(db, case_id, job_id=job_id)
        if not acquired:
            return {"status": "already_resumed", "case_id": case_id, "reason": reason}
    finally:
        db.close()

    if checkpointer is None:
        checkpointer = _default_checkpointer()

    graph = build_graph(checkpointer)
    config = {
        "recursion_limit": _RECURSION_LIMIT,
        "configurable": {
            "thread_id": case_id,
            "session_factory": session_factory,
            "llm_client": llm_client,
            "caller": caller,
            "diagnose_model": settings.diagnosis_llm_model,
            "plan_model": settings.diagnosis_llm_model,
        },
    }

    result: Dict[str, Any] = {}
    try:
        graph.update_state(
            config,
            {
                "policy": {"result": resolution, "detail": f"{resolution} by human operator"},
                "terminal_status": None,
                "caller": caller,
            },
            as_node="policy_check",
        )
        result = graph.invoke(None, config)
        return result
    finally:
        is_terminal = bool(result.get("terminal_status"))
        db = session_factory()
        try:
            case_run_lock_service.release_lock(db, case_id, terminal=is_terminal)
        finally:
            db.close()


def resume_agent_outcome(
    case_id: str,
    outcome_data: Dict[str, Any],
    *,
    caller: str = "webhook",
    session_factory: Callable[[], Session] = SessionLocal,
    checkpointer: Optional[object] = None,
    llm_client: Any = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Resume a parked recovery graph execution at ``outcome_pause`` with observed outcome (Phase B4)."""
    configure_tracing()

    db = session_factory()
    try:
        acquired, reason, _ = case_run_lock_service.acquire_lock(db, case_id, job_id=job_id)
        if not acquired:
            return {"status": "already_resumed", "case_id": case_id, "reason": reason}
    finally:
        db.close()

    if checkpointer is None:
        checkpointer = _default_checkpointer()

    graph = build_graph(checkpointer)
    config = {
        "recursion_limit": _RECURSION_LIMIT,
        "configurable": {
            "thread_id": case_id,
            "session_factory": session_factory,
            "llm_client": llm_client,
            "caller": caller,
            "diagnose_model": settings.diagnosis_llm_model,
            "plan_model": settings.diagnosis_llm_model,
        },
    }

    result: Dict[str, Any] = {}
    try:
        graph.update_state(
            config,
            {
                "outcome": outcome_data,
                "await_outcome": False,
                "terminal_status": None,
                "caller": caller,
            },
            as_node="outcome_pause",
        )
        result = graph.invoke(None, config)
        return result
    finally:
        is_terminal = bool(result.get("terminal_status"))
        db = session_factory()
        try:
            case_run_lock_service.release_lock(db, case_id, terminal=is_terminal)
        finally:
            db.close()

