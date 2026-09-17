"""The recovery graph (BUILDPLAN Phase 4 · PRD §10).

Wires the nodes into the state machine:

    build_context → diagnose → plan → score_ev → policy_check → execute_tool
        → observe_outcome → router → (loop back to score_ev | finalize) → update_ledger → END

Conditional edges:
* score_ev   : an action was chosen → policy_check; nothing eligible left → update_ledger (terminal).
* policy_check: APPROVED → execute_tool; REJECTED → score_ev (next best); ESCALATE → escalation_pause.
* router     : recovered → update_ledger; budget left → score_ev; exhausted → update_ledger.

Termination is guaranteed two ways: ``rejected_actions`` shrinks the candidate pool every loop, and
the router's iteration counter is a hard cap (PRD §21).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from langgraph.graph import END, START, StateGraph

from app.agent.nodes.context import build_context
from app.agent.nodes.diagnose import diagnose
from app.agent.nodes.execute_tool import execute_tool
from app.agent.nodes.observe_outcome import observe_outcome
from app.agent.nodes.plan import plan
from app.agent.nodes.policy_check import policy_check
from app.agent.nodes.router import router
from app.agent.nodes.score_ev import score_ev
from app.agent.nodes.update_ledger import update_ledger
from app.agent.state import AgentState
from app.observability import traceable
from app.policies import engine as policy_engine


def escalation_pause(state: AgentState) -> Dict[str, Any]:
    """A dummy node acting as a checkpointer boundary for escalations.
    Execution halts *before* entering this node, allowing a human operator to resume."""
    return {}


def outcome_pause(state: AgentState) -> Dict[str, Any]:
    """A dummy node acting as a checkpointer boundary for async outcomes (Phase B4).
    Execution halts *before* entering this node, allowing an incoming webhook or
    timeout worker to resume."""
    return {}


@traceable(name="route.after_score", run_type="chain")
def route_after_score(state: AgentState) -> str:
    """An eligible action was chosen -> check policy; otherwise the run is terminal."""
    return "policy_check" if state.get("chosen_action") else "terminal"


@traceable(name="route.after_policy", run_type="chain")
def route_after_policy(state: AgentState) -> str:
    """Branch on the policy engine's verdict for the chosen action."""
    result = (state.get("policy") or {}).get("result")
    if result == policy_engine.APPROVED:
        return "execute"
    if result == policy_engine.ESCALATE:
        return "escalate"
    return "rescore"  # REJECTED (or anything unexpected) -> try the next best action


@traceable(name="route.after_execute", run_type="chain")
def route_after_execute(state: AgentState) -> str:
    """Branch on whether the executed action requires parking for an async outcome (Phase B4)."""
    if state.get("await_outcome"):
        return "wait"
    return "observe"


@traceable(name="route.after_router", run_type="chain")
def route_after_router(state: AgentState) -> str:
    """Recovered/exhausted -> finalize; otherwise loop back to EV scoring."""
    terminal = state.get("terminal_status")
    if terminal == "RECOVERED":
        return "recovered"
    if terminal:  # CLOSED_NO_RECOVERY
        return "stop"
    return "continue"


def build_graph(checkpointer: Optional[object] = None):
    """Assemble and compile the recovery graph. ``checkpointer`` enables durable/resumable runs."""
    graph = StateGraph(AgentState)

    graph.add_node("build_context", build_context)
    graph.add_node("diagnose", diagnose)
    graph.add_node("plan", plan)
    graph.add_node("score_ev", score_ev)
    graph.add_node("policy_check", policy_check)
    graph.add_node("escalation_pause", escalation_pause)
    graph.add_node("execute_tool", execute_tool)
    graph.add_node("outcome_pause", outcome_pause)
    graph.add_node("observe_outcome", observe_outcome)
    graph.add_node("router", router)
    graph.add_node("update_ledger", update_ledger)

    graph.add_edge(START, "build_context")
    graph.add_edge("build_context", "diagnose")
    graph.add_edge("diagnose", "plan")
    graph.add_edge("plan", "score_ev")

    graph.add_conditional_edges(
        "score_ev",
        route_after_score,
        {"policy_check": "policy_check", "terminal": "update_ledger"},
    )
    graph.add_conditional_edges(
        "policy_check",
        route_after_policy,
        {"execute": "execute_tool", "rescore": "score_ev", "escalate": "escalation_pause"},
    )
    # The pause node routes to update_ledger by default, but it's never meant to be traversed.
    # When a human operator approves/rejects, they resume as_node="policy_check", skipping this edge.
    graph.add_edge("escalation_pause", "update_ledger")
    
    graph.add_conditional_edges(
        "execute_tool",
        route_after_execute,
        {"wait": "outcome_pause", "observe": "observe_outcome"},
    )
    graph.add_edge("outcome_pause", "observe_outcome")
    graph.add_edge("observe_outcome", "router")
    graph.add_conditional_edges(
        "router",
        route_after_router,
        {"recovered": "update_ledger", "continue": "score_ev", "stop": "update_ledger"},
    )
    graph.add_edge("update_ledger", END)

    return graph.compile(checkpointer=checkpointer, interrupt_before=["escalation_pause", "outcome_pause"])

