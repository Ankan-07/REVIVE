# Revenue Rescue Engine (REVIVE)

An autonomous AI agent revenue recovery system designed to identify revenue at risk, diagnose the cause, decide optimal economic recovery interventions within strict policies, execute actions, and verify financial outcomes.

---

## Quickstart & Run Instructions

### 1. Prerequisites
- Python 3.13+
- `uv` (Fast Python package installer)
- Node.js 20+ & `npm`

### 2. Environment Configuration
Copy `.env.example` to `.env` in the repository root and fill in your OpenAI API Key:
```bash
cp .env.example .env
```
Ensure `OPENAI_API_KEY` and `LANGSMITH_API_KEY` are properly set in `.env`.

---

## Backend Setup (`backend/`)

1. **Install Dependencies**:
   ```bash
   cd backend
   uv sync
   ```

2. **Run Migrations**:
   ```bash
   uv run alembic upgrade head
   ```

3. **Run Health & Persistence Tests**:
   ```bash
   uv run pytest -q
   ```

4. **Execute LangSmith Smoke Test**:
   ```bash
   uv run python scripts/smoke_trace.py
   ```

5. **Start Development Server**:
   ```bash
   uv run uvicorn app.main:app --reload --port 8000
   ```
   The backend API will be available at `http://localhost:8000` (`GET /health`).

---

## Frontend Setup (`frontend/`)

1. **Install Dependencies**:
   ```bash
   cd frontend
   npm install
   ```

2. **Start Dev Server**:
   ```bash
   npm run dev
   ```
   The frontend UI will be running at `http://localhost:5173`.

---

## Real Payments (Razorpay Standard Checkout, test mode)

The recovery flow can be exercised with a **real** Razorpay payment instead of the deterministic
simulator: open any `FAILED_PAYMENT` case in the dashboard and click **"Pay … now (test card)"**.

1. `POST /razorpay/create-order` validates the failed payment and creates a real Razorpay order
   (amount in paise, `receipt` = payment id).
2. The frontend opens Razorpay's `checkout.js` modal with the returned `order_id`.
3. On success the modal returns `(razorpay_order_id, razorpay_payment_id, razorpay_signature)`;
   `POST /razorpay/verify-payment` verifies the HMAC-SHA256 signature server-side and — only on a
   match — marks the payment `SUCCEEDED`, closes the case as `RECOVERED`, and writes the net
   ledger through the same deterministic service layer the agent uses.

Test mode: the repo ships `rzp_test_*` keys, so no real money moves. Pay the modal with Razorpay's
success test card `4111 1111 1111 1111` (any future expiry, any CVV); use the cards listed in
[Razorpay's test-cards docs](https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/test-card-details/)
to exercise the `payment.failed` path. When the Razorpay keys are unset the endpoints return `503`
and the engine stays fully simulated (this also keeps the test suite hermetic).

Env vars:

```bash
# root .env (backend only — never expose the SECRET)
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...

# frontend/.env (KEY_ID only — it is public by design)
VITE_RAZORPAY_KEY_ID=rzp_test_...
```

## Architecture Principles
1. **The LLM proposes; deterministic code disposes.** LLMs diagnose and suggest candidate actions; policy engine and hard-coded rules enforce boundaries.
2. **Service layer is the sole DB boundary.** Agent, tools, and API handlers never interact with SQLAlchemy sessions directly.
3. **Idempotency & Auditability.** Every financial action is strictly idempotent and records an audit event.
