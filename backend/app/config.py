from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH) if ENV_FILE_PATH.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    openai_base_url: str = ""
    default_llm_model: str = "gpt-4o-mini"
    diagnosis_llm_model: str = "gpt-4o"
    langsmith_api_key: str = ""
    langsmith_project: str = "revenue-rescue-engine"
    langsmith_tracing: bool = True
    database_url: str = "sqlite:///./revive.db"
    # Direct Supabase PostgreSQL URL (port 5432) for Alembic migrations and LangGraph checkpointer
    supabase_db_url: str = ""
    # LangGraph checkpointer lives in its own SQLite file, separate from the domain DB, so agent
    # run state never collides with business data (BUILDPLAN Phase 4).
    checkpoint_db_path: str = "./revive_checkpoints.sqlite"
    # Hard cap on graph loops per case -> guarantees termination (PRD §21; principle §7.7).
    max_agent_iterations: int = 6
    simulation_seed: int = 42
    # Base URL the detector uses to POST events back to this same API over real HTTP.
    internal_api_base_url: str = "http://127.0.0.1:8000"
    # Environment & Production Guards (Phase A2, A3)
    app_env: str = "dev"
    admin_allowed_in_prod: bool = False
    bootstrap_api_key: str = ""
    session_secret_key: str = "revive-insecure-dev-secret-key-change-in-production"
    session_ttl_seconds: int = 28800  # 8 hours

    # Payments / Razorpay (Phase A5 / B1 / B2)
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    live_recovery_enabled: bool = True
    enable_native_reminders: bool = False

    # Messaging / Email - Resend (Phase A5 / C1)
    resend_api_key: str = ""
    resend_sender: str = "onboarding@resend.dev"

    # Messaging / SMS - Twilio (Phase A5 / C1)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    # Alerting (Phase A3.5 — used by B1 webhook HMAC spike detection)
    admin_alert_email: str = ""  # e.g. ops@yourdomain.com
    hmac_failure_alert_threshold: int = 10  # alert if > N failures in 5 min

    # Worker / Redis (Phase A4)
    redis_url: str = "redis://redis:6379"
    # When True, POST /cases/{id}/run-agent runs synchronously (dev/test convenience).
    # When False (production background mode), it enqueues to ARQ and returns 202 Accepted.
    sync_run_agent: bool = True

    # Vite dev server hops to the next free port (5173 -> 5174 -> ...) when one is taken, so allow
    # the common local dev ports for both hostnames rather than pinning a single one.
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
        "http://localhost",
        "http://127.0.0.1",
    ]


settings = Settings()


def validate_environment(cfg: Settings) -> None:
    """Validate environment settings at startup.

    Enforces:
    - [A5.2] Test-mode guard: Any configured Razorpay key MUST start with 'rzp_test_'.
      Live keys ('rzp_live_...') are strictly forbidden by architectural locked decision.
    - [A5.1] Production boot validator: When APP_ENV=prod, requires PostgreSQL DATABASE_URL,
      valid REDIS_URL, Razorpay keys & webhook secret, Resend email credentials,
      Twilio SMS credentials, and non-default SESSION_SECRET_KEY.
    """
    # A5.2 Test-mode guard (applies across all environments if key is provided)
    if cfg.razorpay_key_id and not cfg.razorpay_key_id.startswith("rzp_test_"):
        prefix = cfg.razorpay_key_id[:12] if len(cfg.razorpay_key_id) >= 12 else cfg.razorpay_key_id
        raise RuntimeError(
            f"[A5.2] Test-mode guard failed: RAZORPAY_KEY_ID='{prefix}...' does not start with 'rzp_test_'. "
            "Production-grade REVIVE is locked to Razorpay test mode only. Live keys are strictly forbidden."
        )

    # A5.1 Production boot requirements
    if cfg.app_env.lower() == "prod":
        errors: List[str] = []

        # 1. Database check (must be Postgres)
        db_url = cfg.database_url.lower()
        if not (db_url.startswith("postgresql://") or db_url.startswith("postgresql+psycopg://")):
            errors.append(
                f"DATABASE_URL must be a PostgreSQL connection string in production (got '{cfg.database_url}'). "
                "SQLite is strictly prohibited in prod."
            )

        # 2. Redis check
        if not cfg.redis_url or not (cfg.redis_url.startswith("redis://") or cfg.redis_url.startswith("rediss://")):
            errors.append("REDIS_URL must be set to a valid redis:// or rediss:// connection string in production.")

        # 3. Razorpay credentials
        if not cfg.razorpay_key_id:
            errors.append("RAZORPAY_KEY_ID is required in production (must start with 'rzp_test_').")
        elif not cfg.razorpay_key_id.startswith("rzp_test_"):
            errors.append(f"RAZORPAY_KEY_ID must start with 'rzp_test_' (got '{cfg.razorpay_key_id[:12]}...').")
        if not cfg.razorpay_key_secret:
            errors.append("RAZORPAY_KEY_SECRET is required in production.")
        if not cfg.razorpay_webhook_secret:
            errors.append("RAZORPAY_WEBHOOK_SECRET is required in production for HMAC verification.")

        # 4. Resend credentials
        if not cfg.resend_api_key:
            errors.append("RESEND_API_KEY is required in production for recovery email dispatch.")
        if not cfg.resend_sender:
            errors.append("RESEND_SENDER is required in production.")

        # 5. Twilio credentials
        if not cfg.twilio_account_sid:
            errors.append("TWILIO_ACCOUNT_SID is required in production for recovery SMS dispatch.")
        if not cfg.twilio_auth_token:
            errors.append("TWILIO_AUTH_TOKEN is required in production.")
        if not cfg.twilio_from_number:
            errors.append("TWILIO_FROM_NUMBER is required in production.")

        # 6. Session secret hardening
        if cfg.session_secret_key == "revive-insecure-dev-secret-key-change-in-production":
            errors.append("SESSION_SECRET_KEY must be changed from the insecure default in production.")

        if errors:
            formatted_errors = "\n".join(f"  - {err}" for err in errors)
            raise RuntimeError(
                f"[A5.1] Production configuration validation failed with {len(errors)} error(s):\n{formatted_errors}\n"
                "Refusing to boot. Please check your environment variables or secret store."
            )

