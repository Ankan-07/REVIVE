# Revenue Rescue Engine — Build Plan

> Companion to [`prd.md`](prd.md). The PRD is the source of truth for *product behavior*; this
> document is the source of truth for *how we build it*, in what order, with which tools.
>
> **Product goal for this build:** Learning / portfolio — optimize for clarity, clean separation
> of concerns, understandable code, tests, and docs. Not a time-boxed hackathon sprint, not a
> production hardening exercise.

---

## 0. Decisions locked

| Decision | Choice | Why |
|---|---|---|
| Backend | **Python + FastAPI** | Matches PRD §57; strong LLM/agent ecosystem |
| Agent orchestration | **LangGraph** | Explicit stateful graph = PRD's "state machine, not free-running agent" (§10–11) |
| LLM provider | **OpenAI API** | `gpt-4o-mini` default per node, `gpt-4o` for diagnosis + planning (§14–15) |
| Observability | **LangSmith** | Traces every agent run / tool call — maps to PRD §42 |
| Frontend | **React** (Vite + TypeScript) | Dashboard-first UI (§33–35); Tailwind + Recharts |
| Database | **SQLite via SQLAlchemy ORM** | Zero-setup, instant reset for seeded runs (§27); Postgres-swappable later |
| Build scope | **Failed-payment slice first → then checkout + invoice** | PRD §61: smallest complete workflow before widening |
| Proof of impact | **Full seeded simulator + naive baseline + comparison** | The north-star (§24, §46, §60) |

---

## 1. Guiding principles (read before writing any node)

These come straight from the PRD and are the whole point of the architecture. Violating them
defeats the product.

1. **The LLM proposes; deterministic code disposes.** (§12, §56)
   - LLM *may*: diagnose, summarize context, generate candidate actions, draft messages, extract
     promise-to-pay, estimate intent.
   - LLM *must never*: set financial limits, decide policy, mutate the DB directly, construct SQL,
     or declare a recovery. Those are hard-coded.
2. **Every financial action passes `PLANNING → POLICY_CHECK → ACTION_EXECUTING`.** No shortcuts. (§11)
3. **Never claim recovery without a verified outcome.** The Outcome Monitor confirms money moved. (§56)
4. **Optimize expected _net_ recovery, not recovery rate.** `recovered − intervention_cost − discount`. (§15, §47)
5. **Every state transition + action emits an audit event.** Auditability is a feature, not logging. (§8.5, §42)
6. **Everything is reproducible.** Same seed → same dataset → baseline and agent run on identical data. (§27)
7. **Every case terminates** in `RECOVERED | EXPIRED | ESCALATED | CLOSED_NO_RECOVERY`. No infinite loops. (§21)

**The one-line litmus test for any code you add:** *"Could the LLM being wrong here cause money to
move incorrectly?"* If yes, that decision must be deterministic.

---

## 2. Tech stack & key libraries

**Backend (`backend/`)**
- `fastapi`, `uvicorn` — API + ASGI server
- `sqlalchemy`, `alembic` — ORM + migrations (SQLite now, Postgres later, no code change)
- `pydantic`, `pydantic-settings` — DTOs, enums, env config
- `langgraph` + `langgraph-checkpoint-sqlite` — the agent state machine + durable checkpoints
- `langchain-openai`, `openai` — model calls with native structured outputs
- `langsmith` — tracing (set `LANGCHAIN_TRACING_V2=true`)
- `pytest` — tests

**Frontend (`frontend/`)**
- `vite` + `react` + `typescript`
- `@tanstack/react-query` — data fetching + polling for "real-time" state transitions
- `react-router-dom` — routing
- `tailwindcss` — styling
- `recharts` — charts (risk breakdown, funnel, intervention performance)

**Config / secrets** (§40): `.env` (gitignored) → `OPENAI_API_KEY`, `LANGCHAIN_API_KEY`,
`LANGCHAIN_PROJECT`, `SIMULATION_SEED=42`. Never send secrets into prompts.

---

## 3. Repo structure

```text
revenue-rescue-engine/
├── prd.md
├── BUILDPLAN.md
├── README.md                      # run instructions
├── .env.example
├── backend/
│   ├── pyproject.toml
│   ├── alembic/                    # migrations
│   └── app/
│       ├── main.py                 # FastAPI app + routers
│       ├── config.py               # pydantic-settings
│       ├── db.py                    # engine/session (SQLite → Postgres)
│       ├── models/                  # SQLAlchemy ORM entities (§29–30)
│       ├── schemas/                 # Pydantic DTOs + enums (states, types)
│       ├── domain/                  # pure business logic (risk score, EV calc, ledger)
│       ├── policies/                # Policy engine + policy.yaml (§16)
│       ├── tools/                   # typed, validated, idempotent tools (§17–18)
│       ├── agent/                   # LangGraph graph, nodes, prompts, output schemas
│       │   ├── graph.py             # graph wiring + checkpointer
│       │   ├── nodes/               # one file per node (context, diagnose, plan, ...)
│       │   ├── prompts/             # prompt templates
│       │   └── contracts.py         # Pydantic schemas for LLM structured output (§31)
│       ├── simulation/              # seeded generators + payment sim (§26–28)
│       ├── analytics/               # ledger rollups, baseline comparison (§23, §46)
│       ├── audit/                   # audit event writer (§8.5)
│       ├── services/                # orchestrator entrypoints, case service
│       └── api/                     # route modules (events, cases, analytics, sim, escalations)
│   └── tests/                       # decision/policy/stopping/escalation tests (§44)
└── frontend/
    └── src/
        ├── api/                     # typed client + react-query hooks
        ├── pages/                   # Dashboard, Cases, CaseDetail, EscalationQueue, Benchmark
        ├── components/              # metric cards, funnel, tables
        └── charts/                  # Recharts wrappers
```

---

## 4. The agent as a LangGraph graph (the heart of the system)

Nodes map to the PRD state machine (§11). **Deterministic nodes** are plain Python; **LLM nodes**
call OpenAI with a Pydantic-validated structured output (§31) and retry on schema failure.

```text
                    ┌───────────────────────────┐
                    │  build_context   (det.)    │  §13 — concise context object
                    └─────────────┬─────────────┘
                                  ▼
                    ┌───────────────────────────┐
                    │  diagnose        (LLM 4o)  │  §14 — {type, confidence, evidence}
                    └─────────────┬─────────────┘
                                  ▼
                    ┌───────────────────────────┐
                    │  plan            (LLM 4o)  │  §15 — candidate actions + probs
                    └─────────────┬─────────────┘
                                  ▼
                    ┌───────────────────────────┐
                    │  score_ev        (det.)    │  §15/§47 — pick max expected NET recovery
                    └─────────────┬─────────────┘
                                  ▼
                    ┌───────────────────────────┐
                    │  policy_check    (det.)    │  §16 — approve / reject; escalation triggers §22
                    └─────────────┬─────────────┘
             approved │           │ rejected → back to score_ev (next best action)
                      ▼           │ escalate → interrupt()  ← human-in-the-loop
                    ┌───────────────────────────┐
                    │  execute_tool    (det.)    │  §17/§18/§38 — idempotent, simulated
                    └─────────────┬─────────────┘
                                  ▼  (may interrupt() → WAITING_FOR_OUTCOME, §37)
                    ┌───────────────────────────┐
                    │  observe_outcome (det.)    │  §55/§56 — verify, never assume
                    └─────────────┬─────────────┘
                                  ▼
                    ┌───── conditional router (det.) ─────┐
                    ▼            ▼           ▼             ▼
              RECOVERED    CONTINUE     ESCALATED    EXPIRED/CLOSED
                    └────────────┴───────────┴─────────────┘
                                  ▼
                    ┌───────────────────────────┐
                    │  update_ledger   (det.)    │  §23 — net recovery math
                    └───────────────────────────┘
```

**Key LangGraph techniques this teaches:**
- **Conditional edges** for the router (which terminal state / whether to loop).
- **`interrupt()` + SQLite checkpointer** for two things at once:
  - *Async outcome waiting* (§37): pause after `execute_tool`, resume when a payment event arrives.
  - *Human escalation* (§22, §35): pause at `policy_check`/router, resume when a human approves,
    rejects, or triggers an action from the Escalation Queue.
- **Per-node model binding**: `gpt-4o` for `diagnose`/`plan`, `gpt-4o-mini` elsewhere.
- **State channels**: the graph state carries `case_id`, context, diagnosis, chosen action,
  attempt counters, and audit hooks — but reads/writes to the DB go through the service layer.

---

## 5. Data model (build in Phase 1)

Entities from PRD §29–30, as SQLAlchemy models. Core spine for the failed-payment slice in **bold**:

**`customers`**, **`payments`**, `orders`, `checkouts`, `invoices`, **`revenue_risk_cases`**,
**`interventions`**, **`agent_decisions`**, `policies`, `communications`, `promises_to_pay`,
**`escalations`**, **`audit_events`**, **`gateway_metrics`**, **`recovery_outcomes`**,
**`simulation_runs`**.

> Note: PRD §29 lists `Escalation` as an entity but §30 omits its table — we add an
> `escalations` table (see Phase 6) so a handoff carries its own reason/priority/owner/resolution.

Enums live in `schemas/`: case status (§11), event types (§8.1), intervention types (§8.3),
outcome types (§8.4), escalation reasons/priority (§22, §35).

---

## 6. Build phases

Each phase is a coherent, testable increment. "Done when" is how you know to move on.

### Phase 0 — Scaffolding & runbook
- FastAPI skeleton + `/health`; React app via Vite; `.env.example`; README run steps.
- SQLAlchemy engine/session against SQLite; Alembic initialized.
- Wire OpenAI key + LangSmith tracing (verify a trace appears in LangSmith).
- **Done when:** backend and frontend both start locally; a hello trace shows in LangSmith.

### Phase 1 — Domain model & persistence
- All SQLAlchemy models + Pydantic schemas + enums; first migration.
- Repository/service layer (the *only* thing that touches the DB — enforces §18).
- **Done when:** you can create + read a `Customer` and a `RevenueRiskCase` via a service, with a test.

### Phase 2 — Seeded simulator (payments focus)  · §26–28
- Deterministic generator (seed=42): customers, orders, payments; inject failure mixes
  (insufficient funds, gateway timeout, expired card) + gateway health metrics.
- **Payment simulation mode**: `retry`/`switch_gateway` outcomes computed from
  `customer_intent × gateway_health × method_health` — deterministic under seed (§28).
- `SimulationRun` row records seed + counts + ground-truth outcomes.
- **Done when:** same seed reproduces identical data twice (assert in a test).

### Phase 3 — Risk detection & case creation (failed payment)  · §5, §8
- `POST /events` ingests `PAYMENT_FAILED`; detector creates a `RevenueRiskCase` in `DETECTED`.
- Deterministic risk score + initial recovery probability; audit event on creation.
- **Done when:** posting a failed-payment event produces a case + an audit trail entry.

### Phase 4 — The agent loop (LangGraph)  · §10–16, §31, §56  ← biggest phase
- Build the graph in §4 for failed payment: `build_context → diagnose → plan → score_ev →
  policy_check → execute_tool → observe_outcome → router → update_ledger`.
- LLM nodes return Pydantic-validated structured output; retry on invalid JSON.
- Minimal tool set for the slice: `check_payment_status`, `retry_payment`, `switch_gateway`,
  `create_payment_link` — all simulated, idempotent (`case_id:action:attempt`, §38).
- Policy engine v1 from `policy.yaml`: retry limits, amount threshold, time windows (§16).
- SQLite checkpointer enabled; `interrupt()` used for `WAITING_FOR_OUTCOME` (§37).
- `POST /cases/{id}/run-agent` drives one case through the graph.
- **Done when:** a gateway-degradation case runs end-to-end and reaches `RECOVERED` with a verified
  outcome and a full audit timeline — matching the §43 log example.

### Phase 5 — Tools & policy hardening  · §17–18, §39
- Formalize the typed tool interface: validation, auth stub, idempotency, audit, explicit failure
  statuses (`retryable` vs not, §39).
- Policy tests: over-limit discount rejected, retries exhausted → no retry (§44).
- **Done when:** policy + idempotency + failure-handling tests pass.

### Phase 6 — Escalation & human queue  · §22, §35  ← the part you asked about
- `escalations` table + deterministic `check_escalation()` (forced triggers) **and**
  agent-proposed `ESCALATE_TO_HUMAN` (still policy-validated).
- Escalation = LangGraph `interrupt()`; case → `ESCALATED`; automation halts (§21).
- `EscalationQueue` API + React page (§35): columns Case/Customer/Amount/Reason/Priority/
  Recommended Action/Age/Owner. Actions: approve / reject / assign / note / trigger — **each audited**.
- **Re-entry:** human action resumes the graph via checkpointer (approve → `ACTION_EXECUTING`;
  close → terminal). Human overrides go through the same policy + outcome verification.
- **Done when:** a >₹1,00,000 case auto-escalates, sits in the queue, and a human "approve" resumes
  it to a verified outcome — all in the audit trail.

### Phase 7 — Revenue ledger & analytics  · §23, §36
- Deterministic ledger: `net_recovered = recovered − intervention_cost − discount`.
- `/analytics/recovery`, `/analytics/interventions` endpoints.
- **Done when:** ledger totals reconcile against individual case outcomes in a test.

### Phase 8 — Baseline + benchmark  · §24, §45–46  ← north-star
- Naive baseline strategy (retry once / one generic message / one reminder), no context.
- Run baseline and REVIVE on the **same seed**; store both as `SimulationRun`s.
- `/analytics/baseline` + a comparison view (§46 table).
- **Done when:** the app shows Baseline vs REVIVE (gross, net, rate, escalations) computed from
  actual runs, not hardcoded.

### Phase 9 — Dashboard UI  · §33–34, §53
- Home metrics, risk breakdown charts, recovery funnel, intervention performance table.
- Case Detail (§34): summary, AI diagnosis + evidence, recommended action + policy status,
  timeline, financial outcome, raw audit trail.
- "Run Revenue Rescue" control; polling for live-ish state transitions.
- **UX rule (§54):** operations dashboard, *not* a chat window.
- **Done when:** the §53 demo flow is clickable end-to-end for failed payments.

### Phase 10 — Widen: checkout + invoice  · §9 (MVP2/3), §20
- Extend simulator to inject checkout abandonment + overdue invoices.
- Checkout slice: purchase-intent estimate, channel choice, **discount-vs-message economic
  decision** (§15) — reuses the same graph with new tools/prompts.
- Invoice slice: reminder strategy + **promise-to-pay extraction** (§20) + scheduled promise
  verification job (broken promise → escalate).
- **Done when:** all three leak types flow through the same graph and appear on the dashboard.

### Phase 11 — Evaluation, tests & polish  · §44, §55, §59
- Structured eval suite (§44): decision, policy, stopping, escalation cases.
- Optional: LangSmith eval datasets over diagnosis/decision quality.
- Error + loading states (§55); `docs/architecture.md`, `docs/agent.md`, `docs/api.md`.
- Walk the §59 Definition of Done checklist.
- **Done when:** the §59 checklist is fully green.

---

## 7. Cross-cutting concerns (apply throughout, don't bolt on later)

- **Idempotency** (§38): every financial tool keyed by `case_id:action_type:attempt_number`;
  a duplicate returns the prior result instead of re-charging.
- **Audit** (§8.5, §42): a tiny `audit.record(case_id, event, details)` helper called on every
  state transition, decision, tool call, and human override.
- **Observability** (§42): LangSmith on from Phase 0; log `request_id, case_id, agent_run_id,
  tool_call_id, state, action, result, latency`.
- **Structured outputs** (§31, §56): LLM → Pydantic schema → policy → tool → execution → verify.
  Never LLM → financial action.
- **Testing focus** (§58): the deterministic core — policy, EV/ledger math, state transitions,
  idempotency, stopping rules — is where tests earn their keep.

---

## 8. Definition of Done (from PRD §59, mapped to phases)

| DoD item | Lands in |
|---|---|
| Synthetic customers + leaks generated, reproducible | P2 |
| Events detected → cases created automatically | P3 |
| Context retrieved; agent diagnoses + proposes | P4 |
| Policy validates; tools execute; outcomes verified | P4–P5 |
| Cases transition + stop per policy | P4 |
| Cases escalate; audit trail generated | P6 |
| Revenue recovery measured; baseline comparison | P7–P8 |
| Dashboard financial metrics + case decisions | P9 |
| No financial action without policy validation | P4 (enforced), tested P5/P11 |

---

## 9. Suggested first move

Start at **Phase 0** and get one LangSmith trace flowing before touching the domain model — it
makes every later phase debuggable. Then Phases 1→4 are the critical path to the first "wow"
(a case going `DETECTED → RECOVERED` with a full audit timeline).

> Reminder from PRD §61: build the smallest complete end-to-end path first. Resist adding
> checkout/invoice or Phase-2 features until the failed-payment loop genuinely works.
