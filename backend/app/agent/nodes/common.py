"""Shared helpers for the LangGraph nodes (BUILDPLAN Phase 4).

Two concerns every node has in common:

* **Sessions.** The graph state must stay JSON-serializable for the checkpointer, so a live
  ``Session`` can never live in it. Instead each node pulls a ``session_factory`` from
  ``config["configurable"]`` and opens its own short-lived session. Production injects
  ``SessionLocal``; tests inject a factory bound to an in-memory engine.
* **Decision logging.** Every node records an :class:`~app.models.decision.AgentDecision` row so the
  reasoning trail is queryable in the DB (PRD §8, §42) — complementary to the LangSmith trace.

``open_session`` is a context manager; ``log_decision`` is ``@traceable`` like everything else.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, Optional

from langchain_core.runnables import RunnableConfig  # re-exported: the type nodes annotate `config` with
from sqlalchemy.orm import Session

from app.domain.ids import generate_id
from app.models.decision import AgentDecision
from app.observability import traceable


def session_factory_from(config: Optional[RunnableConfig]) -> Callable[[], Session]:
    """Extract the injected session factory, or fail loudly if the graph was misconfigured."""
    configurable = (config or {}).get("configurable", {})
    factory = configurable.get("session_factory")
    if factory is None:
        raise RuntimeError(
            "session_factory missing from config['configurable']; run_agent must inject it"
        )
    return factory


def configurable(config: Optional[RunnableConfig], key: str, default: Any = None) -> Any:
    """Read a value from ``config['configurable']`` with a default."""
    return (config or {}).get("configurable", {}).get(key, default)


@contextmanager
def open_session(config: Optional[RunnableConfig]) -> Iterator[Session]:
    """Open (and always close) a short-lived session from the injected factory."""
    db = session_factory_from(config)()
    try:
        yield db
    finally:
        db.close()


@traceable(name="agent.log_decision", run_type="tool")
def log_decision(
    db: Session,
    *,
    case_id: str,
    node_name: str,
    output: Dict[str, Any],
    reasoning: str = "",
) -> AgentDecision:
    """Persist one node's decision for the auditable reasoning trail (PRD §8)."""
    decision = AgentDecision(
        id=generate_id("DEC", db),
        case_id=case_id,
        node_name=node_name,
        output_decision_json=output,
        reasoning=reasoning,
    )
    db.add(decision)
    db.commit()
    return decision
