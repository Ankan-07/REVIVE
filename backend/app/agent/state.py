"""The agent's graph state (BUILDPLAN Phase 4).

``AgentState`` is the single object that flows through every LangGraph node. It carries **only
JSON-serializable data** — plain dicts, lists, strings, numbers — because the SQLite checkpointer
must be able to persist it between super-steps (and, in Phase 6, across an ``interrupt()``). In
particular there is **no SQLAlchemy Session in the state**: nodes open their own session from the
``session_factory`` injected via ``config["configurable"]`` (see :mod:`app.agent.nodes.common`).

Each node returns a *partial* dict; LangGraph merges it into the running state (last write wins per
key). List fields (``rejected_actions``) are always returned whole by the node that owns them, so no
custom reducer is needed.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict, total=False):
    case_id: str                       # the RevenueRiskCase being worked (also the checkpoint thread_id)
    context: Dict[str, Any]            # payment/customer/gateway snapshot built by build_context
    diagnosis: Dict[str, Any]          # Diagnosis contract (LLM or deterministic fallback)
    candidates: List[Dict[str, Any]]   # CandidateAction list proposed by the planner
    reasoning_summary: str             # planner's natural-language justification (audit only)
    scored: List[Dict[str, Any]]       # each candidate with simulator-recomputed p, cost, expected_net
    chosen_action: Optional[str]       # argmax expected_net over not-yet-rejected candidates
    ev: Optional[Dict[str, Any]]       # the chosen action's EV breakdown (the money math, for audit)
    policy: Optional[Dict[str, Any]]   # PolicyDecision for chosen_action (APPROVED/REJECTED/ESCALATE)
    attempt: int                       # payment attempts already executed on the case
    rejected_actions: List[str]        # actions ruled out by policy or already tried-and-failed
    tool_result: Optional[Dict[str, Any]]  # result of the executed tool (incl. intervention_id)
    outcome: Optional[Dict[str, Any]]  # verified outcome read back from the DB by observe_outcome
    iterations: int                    # loop counter — hard backstop against non-termination (§21)
    terminal_status: Optional[str]     # set by the node that decides the run is over; read by update_ledger


def initial_state(case_id: str) -> AgentState:
    """A fresh state for ``case_id`` with every field at its empty/zero default."""
    return {
        "case_id": case_id,
        "context": {},
        "diagnosis": {},
        "candidates": [],
        "reasoning_summary": "",
        "scored": [],
        "chosen_action": None,
        "ev": None,
        "policy": None,
        "attempt": 0,
        "rejected_actions": [],
        "tool_result": None,
        "outcome": None,
        "iterations": 0,
        "terminal_status": None,
    }
