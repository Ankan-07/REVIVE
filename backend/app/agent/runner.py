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
from app.observability import configure_tracing, traceable

# Ample headroom over the worst-case node count; real termination is enforced by the router/policy.
_RECURSION_LIMIT = 60


def _default_checkpointer():
    """A durable SQLite checkpointer at the configured path (created/migrated on first use)."""
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect(settings.checkpoint_db_path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


@traceable(name="agent.run_agent", run_type="chain")
def run_agent(
    case_id: str,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
    checkpointer: Optional[object] = None,
    llm_client: Any = None,
) -> Dict[str, Any]:
    """Run the recovery graph for ``case_id`` and return the final graph state."""
    configure_tracing()

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
    return graph.invoke(initial_state(case_id), config)
