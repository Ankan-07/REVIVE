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

## Architecture Principles
1. **The LLM proposes; deterministic code disposes.** LLMs diagnose and suggest candidate actions; policy engine and hard-coded rules enforce boundaries.
2. **Service layer is the sole DB boundary.** Agent, tools, and API handlers never interact with SQLAlchemy sessions directly.
3. **Idempotency & Auditability.** Every financial action is strictly idempotent and records an audit event.
