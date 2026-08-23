# Observability — LangSmith tracing

Maps to PRD §42 (Observability) and BUILDPLAN Phase 0 ("wire LangSmith tracing;
done when a hello trace shows in LangSmith").

## How tracing is wired

All tracing config lives in one module: [`backend/app/observability.py`](../backend/app/observability.py).

- **Call `configure_tracing()` once** at process start (FastAPI startup, the
  agent entrypoint, scripts, test fixtures). It reads `.env`, and if a
  `LANGSMITH_API_KEY` is present it sets `LANGSMITH_TRACING=true` and a default
  `LANGSMITH_PROJECT`. With no key it returns `False` and the app runs untraced
  — it never raises.
- **LangChain / LangGraph is traced automatically.** Once the env vars are set,
  the `diagnose` / `plan` LLM nodes and the graph itself emit traces with no
  extra code. This is why the module only needs to set environment variables.
- **Plain-Python / direct-OpenAI paths** use `traceable` (a decorator) and
  `traced_openai_client()` (wraps the OpenAI client via `wrap_openai`) so the
  deterministic nodes show up in the same trace tree as the LLM calls.

Tracing only *records*; it never makes a financial decision. That keeps it on
the safe side of the PRD's "LLM proposes, deterministic code disposes" rule.

## Environment variables

See [`.env.example`](../.env.example). The essentials:

| Variable | Purpose |
|---|---|
| `LANGSMITH_API_KEY` | Required to send traces. |
| `LANGSMITH_TRACING` | Master on/off (`true`/`false`). |
| `LANGSMITH_PROJECT` | Groups traces in the UI (`revenue-rescue-engine`). |
| `LANGSMITH_ENDPOINT` | Data-region API URL — **must match your workspace region** (US default, EU, or AU/APAC). |
| `OPENAI_API_KEY` | Needed for real LLM calls (optional for the smoke test). |

## Verify it works (Phase 0 smoke test)

From `backend/`:

```bash
python verify_tracing.py
```

This emits a small nested trace (`hello_revive → estimate_risk → draft_message`)
and then polls LangSmith to confirm it landed, printing a direct URL. It needs
only `LANGSMITH_API_KEY`; if `OPENAI_API_KEY` is set it also makes a real,
traced LLM call.

## Querying traces later

The installed `langsmith-trace` skill (plus the `langsmith` CLI) can list,
inspect, and export traces — useful when debugging agent runs:

```bash
langsmith trace list --limit 10 --project revenue-rescue-engine --api-key $LANGSMITH_API_KEY
```

## Troubleshooting

- **`403 Forbidden` when sending traces** — almost always a *region* mismatch, not
  a bad key. LangSmith is region-partitioned and a key only authenticates against
  its own region's endpoint. Set `LANGSMITH_ENDPOINT` to match your workspace:
  - US (default): `https://api.smith.langchain.com`
  - EU: `https://eu.api.smith.langchain.com`
  - AU/APAC: `https://apac.api.smith.langchain.com`

  This project's workspace is in the **AU region**, so `.env` sets
  `LANGSMITH_ENDPOINT=https://apac.api.smith.langchain.com`. (A revoked key also
  returns 403 — if the region is correct, regenerate the key in LangSmith →
  Settings → API Keys.)
- **Traces never show up from a short-lived script** — set
  `LANGCHAIN_CALLBACKS_BACKGROUND=false` so pending traces flush before the
  process exits. `verify_tracing.py` does this automatically.
- **Smoke test appears to hang on the LLM step** — the OpenAI-compatible provider
  is slow or unreachable. The call is bounded (30s timeout) and falls back to a
  deterministic message, so tracing is still verified; check `OPENAI_BASE_URL` and
  that `DEFAULT_LLM_MODEL` is a model the provider actually serves.
