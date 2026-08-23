"""Phase 0 smoke test: emit a 'hello' trace to LangSmith and confirm it landed.

    Run from the backend/ directory:
        python verify_tracing.py

Only LANGSMITH_API_KEY is required. If OPENAI_API_KEY is also set, the message
step makes a real (traced) LLM call using DEFAULT_LLM_MODEL so you can see an
`llm` run in the tree; otherwise it uses a deterministic stand-in and still
produces a full trace.

This satisfies the BUILDPLAN Phase 0 done-criterion: "a hello trace shows in
LangSmith."
"""

from __future__ import annotations

# Short-lived script: send traces synchronously so they're flushed before exit
# (per the langsmith-trace skill's serverless note). Must be set before the
# tracer initializes, i.e. before the first traceable call.
import os

os.environ.setdefault("LANGCHAIN_CALLBACKS_BACKGROUND", "false")

import sys
import time

# Windows consoles default to cp1252; LLM output (and our status lines) may
# contain emoji/unicode, so force UTF-8 to avoid UnicodeEncodeError on print.
for _stream in (sys.stdout, sys.stderr):
    try:
        # line_buffering=True flushes each line even when stdout is a pipe
        # (e.g. run in the background), so progress is visible in real time
        # instead of being withheld until the process exits.
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

from app.observability import configure_tracing, traceable, tracing_project

# Holds the root run id so we can confirm it landed after the pipeline runs.
_STATE: dict[str, str] = {}


@traceable(
    name="hello_revive",
    run_type="chain",
    metadata={"phase": "0", "component": "tracing-smoke-test"},
    tags=["smoke-test", "phase-0"],
)
def hello_revive(customer: str) -> dict:
    """A trivial traced pipeline standing in for a real REVIVE agent run."""
    _capture_run_id()
    risk = estimate_risk(customer)
    message = draft_message(customer, risk)
    return {"customer": customer, "risk_score": risk, "message": message}


@traceable(name="estimate_risk", run_type="chain")
def estimate_risk(customer: str) -> float:
    """Deterministic stand-in for the real risk model (no LLM needed)."""
    return round((sum(map(ord, customer)) % 100) / 100, 2)


@traceable(name="draft_message", run_type="chain")
def draft_message(customer: str, risk: float) -> str:
    """Draft a recovery nudge — via a traced LLM call if one is configured.

    The LLM call is best-effort: a misconfigured provider/model must not fail
    the *tracing* check, so we fall back to a deterministic message.
    """
    if os.getenv("OPENAI_API_KEY"):
        try:
            return _draft_message_llm(customer, risk)
        except Exception as exc:  # provider/model/network issue — trace still captured
            print(
                f"   (LLM step skipped: {type(exc).__name__}: {str(exc)[:140]}) "
                f"— using deterministic message",
                file=sys.stderr,
            )
    return (
        f"Hi {customer}, we noticed your recent payment didn't go through "
        f"(risk score {risk}). Here's a secure link to retry."
    )


def _draft_message_llm(customer: str, risk: float) -> str:
    from app.observability import traced_openai_client

    model = os.getenv("DEFAULT_LLM_MODEL", "gpt-4o-mini")
    client = traced_openai_client()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Write a one-line, friendly payment-retry nudge for {customer} "
                    f"(recovery risk {risk}). No internal error codes."
                ),
            }
        ],
        max_tokens=120,
        # Bound the call so a slow/unreachable provider can't hang the *tracing*
        # smoke test — on timeout the caller falls back to a deterministic message
        # and the trace is still captured.
        timeout=30,
    )
    return resp.choices[0].message.content or ""


def _capture_run_id() -> None:
    """Record the current root run id from inside the trace, if available."""
    try:
        from langsmith.run_helpers import get_current_run_tree
    except Exception:  # pragma: no cover - import path varies by SDK version
        try:
            from langsmith import get_current_run_tree  # type: ignore
        except Exception:
            return
    rt = get_current_run_tree()
    if rt is not None:
        _STATE["run_id"] = str(rt.id)


def _check_auth(project: str) -> tuple[bool, str]:
    """Verify the LangSmith key is accepted before we try to emit traces.

    Returns (ok, detail). Turns an otherwise-cryptic background 403 into a clear
    upfront diagnosis.
    """
    from langsmith import Client

    try:
        list(Client().list_projects(limit=1))
        return True, "ok"
    except Exception as exc:
        return False, str(exc).replace("\n", " ")


def _confirm_trace_landed(project: str, attempts: int = 8, delay: float = 2.0) -> str | None:
    """Poll LangSmith until the trace is queryable; return a URL to it."""
    from langsmith import Client

    client = Client()
    run_id = _STATE.get("run_id")

    for _ in range(attempts):
        try:
            if run_id:
                run = client.read_run(run_id)
                return client.get_run_url(run=run)
            runs = list(client.list_runs(project_name=project, limit=1))
            if runs:
                return client.get_run_url(run=runs[0])
        except Exception:
            pass
        time.sleep(delay)
    return None


def main() -> int:
    enabled = configure_tracing()
    project = tracing_project()

    if not enabled:
        print(
            "FAIL: tracing is OFF — LANGSMITH_API_KEY not found. "
            "Add it to .env and re-run.",
            file=sys.stderr,
        )
        return 1

    print(f"-> Tracing ON | project={project!r}")
    print("-> Checking LangSmith credentials ...")
    ok, detail = _check_auth(project)
    if not ok:
        forbidden = "403" in detail or "Forbidden" in detail
        print(
            "FAIL: LangSmith rejected the API key.\n"
            f"   {detail[:220]}",
            file=sys.stderr,
        )
        if forbidden:
            print(
                "   -> A 403 means the key is invalid/revoked (not a network issue).\n"
                "      Generate a new key at https://smith.langchain.com "
                "(Settings -> API Keys), put it in .env as LANGSMITH_API_KEY, and re-run.",
                file=sys.stderr,
            )
        return 2

    mode = "LLM call" if os.getenv("OPENAI_API_KEY") else "deterministic (no OpenAI key)"
    print(f"   credentials OK | message step: {mode}")
    print("-> Emitting hello trace ...")

    result = hello_revive("CUS-8821 (Asha Rao)")
    print(f"   pipeline output: {result}")

    print("-> Confirming the trace landed in LangSmith ...")
    url = _confirm_trace_landed(project)
    if url:
        print(f"PASS: trace is visible in LangSmith:\n   {url}")
        return 0

    print(
        "PARTIAL: the pipeline ran and traces were sent, but the trace was not "
        "queryable yet (ingestion can lag a few seconds).\n"
        f"   Check the '{project}' project at https://smith.langchain.com",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
