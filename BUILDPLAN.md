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

### Phase 5 — Tools & policy hardening  · §17–18, §39, §44

Four explicit tasks, each with a narrow scope. Nothing here touches the agent graph wiring
(that is Phase 4); this phase makes the *existing* graph provably correct by closing the gaps
between the PRD's safety requirements and the Phase 4 implementation.

#### Task 5.1 — Tool safety layer  · §17, §18, §39
Harden every simulated action tool so that bad inputs, wrong callers, and infrastructure
failures are caught before any side-effect occurs.

- **Auth stub**: Add a lightweight `require_system_context(caller: str)` check in
  `tools/base.py`. Tools must be called as `caller="system"` (the graph) or
  `caller="operator"` (human escalation). Any other value raises `AuthorizationError` and
  the tool returns a terminal `ToolResult` with `error_code="AUTH_FAILURE"`.
- **Parameter validation**: Validate inputs at the top of every tool before touching the DB:
  - `case_id` matches `RR-\d{5}` pattern.
  - `payment_id` matches `PAY-\d{5}` pattern.
  - `attempt` is a positive integer.
  - `amount_at_risk` (when applicable) is `> 0`.
  Violations return `ToolResult(success=False, error_code="PARAM_VALIDATION_FAILURE", retryable=False)`.
- **Failure classification**: Extend `ToolResult` with a `failure_category` field drawn from a
  new `FailureCategory` enum (lives in `tools/base.py`):

  | Category | Retryable | Example |
  |---|---|---|
  | `AUTHENTICATION_FAILURE` | No | Wrong caller context |
  | `PARAM_VALIDATION_FAILURE` | No | Bad ID format |
  | `RETRYABLE_SYSTEM_FAILURE` | Yes | Gateway timeout, `error_code="timeout"` |
  | `NON_RETRYABLE_USER_FAILURE` | No | Expired card, `error_code="card_expired"` |
  | `CUSTOMER_SIDE_FAILURE` | No | Customer dispute, `error_code="dispute"` |
  | `POLICY_FAILURE` | No | Rejected before execution (set by policy_check node) |

  The `simulate_payment` oracle already returns an `error_code`; map it to the correct
  `FailureCategory` in `_run_action` before constructing `ToolResult`.
- **Pre-execution audit record**: Write a `TOOL_VALIDATION_PASSED` audit event after
  validation succeeds and before the simulation call, so the audit trail proves the check ran.

#### Task 5.2 — Policy node integration  · §16
The Phase 4 `policy_check` node calls `policy_engine.evaluate` with only `amount_at_risk`
and `attempt_count`, leaving the messaging, time-window, and discount rules unreachable.
Close that gap:

- **Case age**: In `policy_check`, calculate `hours_since_creation` from
  `case.created_at` to `datetime.now(UTC)` and pass it to `evaluate`.
- **Message count & spacing**: Query `audit_events` for `TOOL_EXECUTED` rows with
  `action IN (SEND_DISCOUNT_MESSAGE, SEND_REMINDER)` to derive `message_count` and
  `hours_since_last_message`. Pass both to `evaluate`.
- **Discount amount**: The `chosen_action` in the graph state may carry a `discount_amount`
  inside `ev` (EV scoring breakdown). Extract it and pass it to `evaluate` so the engine
  can reject over-limit discounts.
- No changes to `policy_engine.evaluate` itself — the logic is already correct; only the
  *caller* was missing arguments.

#### Task 5.3 — Dedicated unit test suite  · §44
Create two new test files. All tests must be hermetic (in-memory SQLite, no OpenAI).

**`tests/test_policies.py`** — direct unit tests against `policy_engine.evaluate`:

| Test | Given | Expected |
|---|---|---|
| `test_discount_over_absolute_limit_rejected` | `discount_amount=1500`, cap=₹1000 | `REJECTED`, reason `POLICY_REJECTION` |
| `test_discount_at_limit_approved` | `discount_amount=1000`, cap=₹1000 | `APPROVED` |
| `test_message_cap_rejected` | `message_count=3`, max=3 | `REJECTED` |
| `test_message_spacing_rejected` | `hours_since_last_message=12`, min=24 | `REJECTED` |
| `test_retry_window_expired_rejected` | `hours_since_creation=80`, window=72 | `REJECTED` |
| `test_amount_threshold_escalates` | `amount_at_risk=150_000` | `ESCALATE` |
| `test_retries_exhausted_rejected` | `attempt_count=3`, max=3 | `REJECTED` |
| `test_min_amount_payment_link_rejected` | action=`CREATE_PAYMENT_LINK`, `amount=0.5` | `REJECTED` |

**`tests/test_tools.py`** — direct unit tests for the hardened tool layer:

| Test | Scenario | Expected |
|---|---|---|
| `test_auth_failure_wrong_caller` | `caller="untrusted"` | `ToolResult(success=False, error_code="AUTH_FAILURE")` |
| `test_param_validation_bad_case_id` | `case_id="bad"` | `ToolResult(error_code="PARAM_VALIDATION_FAILURE")` |
| `test_retryable_error_category` | sim returns `error_code="timeout"` | `failure_category=RETRYABLE_SYSTEM_FAILURE` |
| `test_non_retryable_error_category` | sim returns `error_code="card_expired"` | `failure_category=NON_RETRYABLE_USER_FAILURE`, `retryable=False` |
| `test_idempotency_replay` | same `case_id:action:attempt` called twice | second call returns prior result, 1 DB row only |
| `test_pre_execution_audit_event_written` | valid tool call | `TOOL_VALIDATION_PASSED` appears in audit trail |

**Done when:** All 14 new tests above pass alongside the existing 25-test suite (total ≥ 39 green); `policy_check` node passes `hours_since_creation`, `message_count`, `hours_since_last_message`, and `discount_amount` to `evaluate`; every tool validates auth and parameters before touching the DB.

### Phase 6 — Escalation & human queue  · §22, §35
This phase implements the "Human-in-the-loop" mechanism. When policy dictates (e.g., > ₹1,00,000) or the agent gets stuck, the autonomous loop must halt and hand over to a human operator, who can review and resume the process.

#### Task 6.1 — Escalation Data Model & Service
- **Files to create/touch:** `backend/app/models/escalation.py` (NEW), `backend/app/models/__init__.py`, `backend/app/services/escalation_service.py` (NEW).
- **Goal:** Create the `Escalation` SQLAlchemy model (fields: `id`, `case_id`, `reason`, `priority`, `owner_id`, `status`, `recommended_action`). Create the service layer to list pending escalations and update their status (assign/resolve). Generate and apply the Alembic migration.

#### Task 6.2 — API Endpoints
- **Files to create/touch:** `backend/app/api/escalations.py` (NEW), `backend/app/main.py`.
- **Goal:** Expose endpoints for the frontend queue: `GET /escalations` (list pending), `POST /escalations/{id}/assign` (claim a ticket), and `POST /escalations/{id}/resolve` (approve or reject the action).

#### Task 6.3 — LangGraph Interruption & Re-entry
- **Files to create/touch:** `backend/app/agent/graph.py`, `backend/app/agent/runner.py`.
- **Goal:** When `policy_check` returns `ESCALATE`, the graph should explicitly pause (using LangGraph's `interrupt()` or checkpointer pause). The `POST /escalations/{id}/resolve` endpoint must then use the checkpointer to resume the graph execution, passing in the human's decision so it can proceed to `execute_tool` (with `caller="operator"`) or close the case.

#### Task 6.4 — Frontend Escalation Queue UI
- **Files to create/touch:** `frontend/src/api/escalations.ts` (NEW), `frontend/src/pages/EscalationQueue.tsx` (NEW), `frontend/src/App.tsx`.
- **Goal:** Build the React page (PRD §35) with columns for Case, Customer, Amount, Reason, Priority, and Recommended Action. Add action buttons for the operator to Assign to themselves, Approve, or Reject.

#### Task 6.5 — Integration Tests
- **Files to create/touch:** `backend/tests/test_escalations.py` (NEW).
- **Goal:** Write an end-to-end test proving that a >₹1,00,000 case auto-escalates, sits in the queue, and a simulated human "approve" API call resumes it to a verified outcome, completely logged in the audit trail.
- **Done when:** The E2E test passes and the Escalation Queue UI successfully displays and resolves a paused case.

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
