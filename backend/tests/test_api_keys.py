"""Unit tests for ApiKey model, hashing, and api_key_service (Phase A2.1)."""
from datetime import timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, utc_now
from app.models.api_key import KeyUsageEvent
from app.services import api_key_service


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_create_key_format_and_hashing(db_session):
    key, raw_key = api_key_service.create_key(
        db=db_session,
        name="Alice Vance",
        scopes=["operator", "internal"],
        expires_days=30,
    )

    assert key.id is not None
    assert key.name == "Alice Vance"
    assert key.scopes == "internal,operator"
    assert key.revoked is False
    assert key.key_prefix.startswith("rve_")
    assert raw_key.startswith(key.key_prefix + "_")

    # DB does not store plaintext raw key
    assert raw_key != key.key_hash
    assert len(key.key_hash) == 64  # hex SHA-256
    assert key.salt is not None


def test_verify_valid_key(db_session):
    key, raw_key = api_key_service.create_key(
        db=db_session,
        name="Bob Smith",
        scopes=["operator"],
    )

    verified = api_key_service.verify_key(db_session, raw_key)
    assert verified is not None
    assert verified.id == key.id
    assert verified.name == "Bob Smith"
    assert verified.last_used_at is not None


def test_verify_invalid_key_fails(db_session):
    _, raw_key = api_key_service.create_key(db=db_session, name="Charlie", scopes=["operator"])

    # Tampered secret
    tampered = raw_key[:-4] + "xxxx"
    assert api_key_service.verify_key(db_session, tampered) is None

    # Invalid format
    assert api_key_service.verify_key(db_session, "not_a_valid_key") is None
    assert api_key_service.verify_key(db_session, "") is None

    # Unknown prefix
    assert api_key_service.verify_key(db_session, "rve_00000000_secretsecret") is None


def test_revoked_key_rejected(db_session):
    key, raw_key = api_key_service.create_key(db=db_session, name="David", scopes=["operator"])
    assert api_key_service.verify_key(db_session, raw_key) is not None

    # Revoke key
    success = api_key_service.revoke_key(db_session, key.id)
    assert success is True

    # Immediate rejection
    assert api_key_service.verify_key(db_session, raw_key) is None


def test_expired_key_rejected(db_session):
    key, raw_key = api_key_service.create_key(
        db=db_session,
        name="Eve",
        scopes=["operator"],
    )
    # Force expiration in past
    key.expires_at = utc_now() - timedelta(minutes=10)
    db_session.commit()

    assert api_key_service.verify_key(db_session, raw_key) is None


def test_list_keys_and_revocation_filter(db_session):
    k1, _ = api_key_service.create_key(db=db_session, name="Key 1", scopes=["operator"])
    k2, _ = api_key_service.create_key(db=db_session, name="Key 2", scopes=["internal"])

    api_key_service.revoke_key(db_session, k1.id)

    active_keys = api_key_service.list_keys(db_session, include_revoked=False)
    assert len(active_keys) == 1
    assert active_keys[0].id == k2.id

    all_keys = api_key_service.list_keys(db_session, include_revoked=True)
    assert len(all_keys) == 2


def test_record_usage(db_session):
    key, _ = api_key_service.create_key(db=db_session, name="Worker", scopes=["internal"])

    event = api_key_service.record_usage(
        db=db_session,
        key_id=key.id,
        route="/events/",
        method="POST",
        ip="127.0.0.1",
        status_code=200,
    )
    assert event.id is not None
    assert event.key_id == key.id
    assert event.route == "/events/"
    assert event.status_code == 200

    stored = db_session.query(KeyUsageEvent).filter(KeyUsageEvent.key_id == key.id).all()
    assert len(stored) == 1
