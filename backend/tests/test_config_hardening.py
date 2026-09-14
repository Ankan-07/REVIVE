"""Unit and integration tests for Phase A5: Config Hardening (PRD/Production Plan §A5).

Covers:
- [A5.1] Production boot validation (requires Postgres, Redis, Razorpay, Resend, Twilio, hardened session secret)
- [A5.2] Razorpay test-mode guard (strictly refuses rzp_live_ or any non-rzp_test_ keys)
- Fast execution guard (<5s boot refusal check)
"""
import time
import pytest

from app.config import Settings, validate_environment


def _make_valid_prod_settings() -> Settings:
    """Return a Settings instance fully populated for production."""
    return Settings(
        app_env="prod",
        database_url="postgresql+psycopg://user:pass@ep-prod-db.supabase.co:6543/postgres?sslmode=require",
        supabase_db_url="postgresql+psycopg://user:pass@ep-prod-db.supabase.co:5432/postgres?sslmode=require",
        redis_url="redis://redis:6379",
        session_secret_key="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        cors_origins=["https://revive.mycompany.com"],
        razorpay_key_id="rzp_test_validkey12345",
        razorpay_key_secret="test_secret_xyz987",
        razorpay_webhook_secret="test_webhook_sec_abc",
        resend_api_key="re_prod_test_key_12345",
        resend_sender="recovery@mycompany.com",
        twilio_account_sid="AC1234567890abcdef1234567890abcdef",
        twilio_auth_token="auth_token_secret_12345",
        twilio_from_number="+15551234567",
    )


def test_dev_environment_default_valid():
    """In development mode, default development settings validate cleanly."""
    dev_settings = Settings(
        app_env="dev",
        database_url="sqlite:///./revive.db",
        razorpay_key_id="",
    )
    # Should not raise
    validate_environment(dev_settings)


def test_test_mode_guard_blocks_live_razorpay_key():
    """[A5.2] Any Razorpay key starting with rzp_live_ or non-rzp_test_ is strictly blocked."""
    live_settings = Settings(
        app_env="dev",
        razorpay_key_id="rzp_live_realmoney12345678",
    )
    with pytest.raises(RuntimeError) as exc_info:
        validate_environment(live_settings)

    err = str(exc_info.value)
    assert "[A5.2]" in err
    assert "Test-mode guard failed" in err
    assert "rzp_live_" in err
    assert "locked to Razorpay test mode only" in err


def test_test_mode_guard_blocks_malformed_key_prefix():
    """[A5.2] Key without 'rzp_test_' prefix is blocked even in dev."""
    bad_prefix = Settings(
        app_env="dev",
        razorpay_key_id="sk_test_someotherprovider",
    )
    with pytest.raises(RuntimeError) as exc_info:
        validate_environment(bad_prefix)

    assert "[A5.2]" in str(exc_info.value)


def test_test_mode_guard_allows_rzp_test_prefix():
    """[A5.2] Key starting with rzp_test_ passes the test-mode guard."""
    valid_test_settings = Settings(
        app_env="dev",
        razorpay_key_id="rzp_test_okkey9876",
    )
    validate_environment(valid_test_settings)


def test_prod_validator_passes_when_all_variables_configured():
    """[A5.1] When all production variables are provided and valid, validation succeeds."""
    prod_settings = _make_valid_prod_settings()
    validate_environment(prod_settings)


def test_prod_validator_blocks_sqlite():
    """[A5.1] Production mode must reject SQLite database URLs."""
    cfg = _make_valid_prod_settings()
    cfg.database_url = "sqlite:///./revive.db"

    with pytest.raises(RuntimeError) as exc_info:
        validate_environment(cfg)

    err = str(exc_info.value)
    assert "[A5.1]" in err
    assert "DATABASE_URL must be a PostgreSQL connection string" in err


def test_prod_validator_blocks_missing_redis():
    """[A5.1] Production mode requires a valid redis:// or rediss:// REDIS_URL."""
    cfg = _make_valid_prod_settings()
    cfg.redis_url = ""

    with pytest.raises(RuntimeError) as exc_info:
        validate_environment(cfg)

    err = str(exc_info.value)
    assert "[A5.1]" in err
    assert "REDIS_URL must be set" in err


def test_prod_validator_blocks_missing_razorpay_credentials():
    """[A5.1] Missing Razorpay secret or webhook secret in prod is rejected."""
    cfg = _make_valid_prod_settings()
    cfg.razorpay_key_secret = ""
    cfg.razorpay_webhook_secret = ""

    with pytest.raises(RuntimeError) as exc_info:
        validate_environment(cfg)

    err = str(exc_info.value)
    assert "RAZORPAY_KEY_SECRET is required in production" in err
    assert "RAZORPAY_WEBHOOK_SECRET is required in production" in err


def test_prod_validator_blocks_missing_resend_and_twilio_credentials():
    """[A5.1] Missing email or SMS credentials in prod are rejected."""
    cfg = _make_valid_prod_settings()
    cfg.resend_api_key = ""
    cfg.twilio_auth_token = ""

    with pytest.raises(RuntimeError) as exc_info:
        validate_environment(cfg)

    err = str(exc_info.value)
    assert "RESEND_API_KEY is required in production" in err
    assert "TWILIO_AUTH_TOKEN is required in production" in err


def test_prod_validator_blocks_insecure_default_session_secret():
    """[A5.1] Using the development default SESSION_SECRET_KEY in prod is blocked."""
    cfg = _make_valid_prod_settings()
    cfg.session_secret_key = "revive-insecure-dev-secret-key-change-in-production"

    with pytest.raises(RuntimeError) as exc_info:
        validate_environment(cfg)

    err = str(exc_info.value)
    assert "SESSION_SECRET_KEY must be changed from the insecure default" in err


def test_prod_validator_collects_all_missing_variables():
    """[A5.1] An empty prod config lists all missing requirements in a single actionable error."""
    empty_prod = Settings(
        app_env="prod",
        database_url="sqlite:///./revive.db",
        redis_url="",
        session_secret_key="revive-insecure-dev-secret-key-change-in-production",
        razorpay_key_id="",
        razorpay_key_secret="",
        razorpay_webhook_secret="",
        resend_api_key="",
        twilio_account_sid="",
        twilio_auth_token="",
        twilio_from_number="",
    )

    with pytest.raises(RuntimeError) as exc_info:
        validate_environment(empty_prod)

    err = str(exc_info.value)
    assert "DATABASE_URL" in err
    assert "REDIS_URL" in err
    assert "RAZORPAY_KEY_ID" in err
    assert "RAZORPAY_KEY_SECRET" in err
    assert "RAZORPAY_WEBHOOK_SECRET" in err
    assert "RESEND_API_KEY" in err
    assert "TWILIO_ACCOUNT_SID" in err
    assert "TWILIO_AUTH_TOKEN" in err
    assert "TWILIO_FROM_NUMBER" in err
    assert "SESSION_SECRET_KEY" in err


def test_prod_validation_speed_under_five_seconds():
    """DoD: Incomplete prod env fails in <5s (actually <10ms) with actionable message."""
    empty_prod = Settings(
        app_env="prod",
        database_url="sqlite:///./revive.db",
    )
    start = time.perf_counter()
    with pytest.raises(RuntimeError):
        validate_environment(empty_prod)
    elapsed = time.perf_counter() - start

    # Should fail almost instantaneously (< 0.1 seconds)
    assert elapsed < 0.1, f"Validation took too long: {elapsed}s"
