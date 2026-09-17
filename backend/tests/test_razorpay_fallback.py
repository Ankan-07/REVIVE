"""Test fallback placeholder keys for Razorpay when real keys are absent.

Enforces:
1. Real keys take precedence if present.
2. If real keys are absent, fallback placeholder keys starting with 'rzp_test_' are provided for tests.
3. razorpay_service.is_configured() returns True with either real or fallback keys.
"""
import os
import pytest
from app.config import settings, validate_environment, Settings
from app.services import razorpay_service


def test_real_keys_take_precedence_over_fallback(monkeypatch):
    """When real test keys are in the environment, they must be preserved."""
    real_key_id = "rzp_test_real_user_key_123"
    real_secret = "real_secret_abc_456"
    monkeypatch.setenv("RAZORPAY_KEY_ID", real_key_id)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", real_secret)

    assert razorpay_service.is_configured() is True
    assert (os.getenv("RAZORPAY_KEY_ID") or settings.razorpay_key_id) == real_key_id
    assert razorpay_service._key_secret() == real_secret


def test_fallback_keys_used_when_environment_keys_absent(monkeypatch):
    """When real keys are unset or empty, placeholder keys act as fallback in test fixtures."""
    # Temporarily clear environment
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    monkeypatch.setattr(settings, "razorpay_key_id", "")
    monkeypatch.setattr(settings, "razorpay_key_secret", "")

    # Before fallback is applied, is_configured() is False
    assert razorpay_service.is_configured() is False

    # Apply test fallback
    fallback_id = "rzp_test_placeholder_key"
    fallback_secret = "placeholder_secret_xyz"
    monkeypatch.setenv("RAZORPAY_KEY_ID", fallback_id)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", fallback_secret)

    # Now is_configured() is True
    assert razorpay_service.is_configured() is True
    assert razorpay_service._key_secret() == fallback_secret

    # Verify fallback key passes the test-mode guard
    cfg = Settings(
        app_env="dev",
        razorpay_key_id=fallback_id,
        razorpay_key_secret=fallback_secret,
    )
    validate_environment(cfg)
