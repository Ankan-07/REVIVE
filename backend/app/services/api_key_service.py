"""Service for managing, verifying, and auditing service API keys (Phase A2.1).

Keys are per-person and cryptographically secured using salted PBKDF2-HMAC-SHA256
with 100,000 iterations. Verification uses indexed key prefixes for O(1) database lookup
and constant-time digest comparison to prevent timing side-channels.
"""
from datetime import timedelta, timezone
import hashlib
import hmac
import logging
import secrets
import uuid
from typing import List, Optional, Tuple, Union

from sqlalchemy.orm import Session

from app.config import settings
from app.db import utc_now
from app.models.api_key import ApiKey, KeyUsageEvent

logger = logging.getLogger(__name__)

HASH_ITERATIONS = 100_000
KEY_PREFIX_TAG = "rve"
VALID_SCOPES = {"operator", "internal", "admin", "webhooks:receive"}


def _hash_secret(secret: str, salt: str) -> str:
    """Compute deterministic PBKDF2-HMAC-SHA256 hash of a secret key with salt."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        salt.encode("utf-8"),
        HASH_ITERATIONS,
    ).hex()


def create_key(
    db: Session,
    name: str,
    scopes: Union[List[str], str],
    expires_days: Optional[int] = None,
    custom_raw_key: Optional[str] = None,
) -> Tuple[ApiKey, str]:
    """Create a new service API key.
    
    Returns the persisted ApiKey record and the raw key string (displayed ONCE).
    """
    if not name or not name.strip():
        raise ValueError("API key name cannot be empty")

    if isinstance(scopes, str):
        scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
    else:
        scope_list = [s.strip() for s in scopes if s.strip()]

    if not scope_list:
        raise ValueError("At least one scope must be provided")

    for s in scope_list:
        if s not in VALID_SCOPES:
            raise ValueError(f"Invalid scope '{s}'. Valid scopes are: {', '.join(sorted(VALID_SCOPES))}")

    if custom_raw_key:
        raw_key = custom_raw_key.strip()
        parts = raw_key.split("_", 2)
        if len(parts) == 3 and parts[0] == KEY_PREFIX_TAG:
            prefix_val = f"{KEY_PREFIX_TAG}_{parts[1]}"
            secret_val = parts[2]
        else:
            prefix_val = f"{KEY_PREFIX_TAG}_{secrets.token_hex(4)}"
            secret_val = raw_key
            raw_key = f"{prefix_val}_{secret_val}"
    else:
        prefix_part = secrets.token_hex(4)
        secret_val = secrets.token_urlsafe(32)
        prefix_val = f"{KEY_PREFIX_TAG}_{prefix_part}"
        raw_key = f"{prefix_val}_{secret_val}"

    # Check for prefix collision
    existing = db.query(ApiKey).filter(ApiKey.key_prefix == prefix_val).first()
    if existing:
        # Extremely improbable with random hex, but handle cleanly
        prefix_part = secrets.token_hex(6)
        prefix_val = f"{KEY_PREFIX_TAG}_{prefix_part}"
        raw_key = f"{prefix_val}_{secret_val}"

    salt = secrets.token_hex(16)
    key_hash = _hash_secret(secret_val, salt)

    expires_at = None
    if expires_days is not None and expires_days > 0:
        expires_at = utc_now() + timedelta(days=expires_days)

    key_record = ApiKey(
        id=str(uuid.uuid4()),
        name=name.strip(),
        key_prefix=prefix_val,
        key_hash=key_hash,
        salt=salt,
        scopes=",".join(sorted(set(scope_list))),
        revoked=False,
        created_at=utc_now(),
        expires_at=expires_at,
        last_used_at=None,
    )
    db.add(key_record)
    db.commit()
    db.refresh(key_record)

    logger.info("Created API key '%s' (prefix=%s, id=%s, scopes=%s)", key_record.name, key_record.key_prefix, key_record.id, key_record.scopes)
    return key_record, raw_key


def verify_key(db: Session, raw_key: str) -> Optional[ApiKey]:
    """Verify a raw API key against the database.
    
    Performs constant-time hash comparison and checks expiration/revocation.
    Updates last_used_at on successful verification.
    """
    if not raw_key or not isinstance(raw_key, str):
        return None

    raw_key = raw_key.strip()
    parts = raw_key.split("_", 2)
    if len(parts) != 3 or parts[0] != KEY_PREFIX_TAG:
        return None

    prefix_val = f"{parts[0]}_{parts[1]}"
    secret_val = parts[2]

    key = db.query(ApiKey).filter(ApiKey.key_prefix == prefix_val).first()
    if not key:
        return None

    if key.revoked:
        logger.warning("Attempted use of revoked API key '%s' (id=%s)", key.name, key.id)
        return None

    # Check expiration
    if key.expires_at is not None:
        now = utc_now()
        # Handle timezone-naive DB datetimes cleanly
        exp = key.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < now:
            logger.warning("Attempted use of expired API key '%s' (id=%s, expired_at=%s)", key.name, key.id, exp)
            return None

    computed_hash = _hash_secret(secret_val, key.salt)
    if not hmac.compare_digest(computed_hash, key.key_hash):
        logger.warning("Hash mismatch for API key '%s' (id=%s)", key.name, key.id)
        return None

    # Update last_used_at
    key.last_used_at = utc_now()
    try:
        db.commit()
    except Exception:
        db.rollback()

    return key


def revoke_key(db: Session, key_id: str) -> bool:
    """Revoke an API key by ID. Takes effect immediately."""
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        return False
    key.revoked = True
    db.commit()
    logger.info("Revoked API key '%s' (id=%s)", key.name, key.id)
    return True


def list_keys(db: Session, include_revoked: bool = False) -> List[ApiKey]:
    """List all API keys."""
    query = db.query(ApiKey)
    if not include_revoked:
        query = query.filter(ApiKey.revoked == False)
    return query.order_by(ApiKey.created_at.desc()).all()


def get_key_by_id(db: Session, key_id: str) -> Optional[ApiKey]:
    """Retrieve an API key record by ID."""
    return db.query(ApiKey).filter(ApiKey.id == key_id).first()


def record_usage(
    db: Session,
    key_id: str,
    route: str,
    method: str,
    ip: Optional[str] = None,
    status_code: Optional[int] = None,
) -> KeyUsageEvent:
    """Append a key usage event to the audit log (Phase A2.6)."""
    event = KeyUsageEvent(
        id=str(uuid.uuid4()),
        key_id=key_id,
        route=route,
        method=method.upper(),
        ip=ip,
        status_code=status_code,
        timestamp=utc_now(),
    )
    db.add(event)
    try:
        db.commit()
        db.refresh(event)
    except Exception as exc:
        db.rollback()
        logger.error("Failed to record key usage event: %s", exc)
    return event


def bootstrap_initial_key(db: Session) -> Optional[ApiKey]:
    """Bootstrap an initial operator/admin key from BOOTSTRAP_API_KEY if configured (Phase A2.2)."""
    bootstrap_key = (settings.bootstrap_api_key or "").strip()
    if not bootstrap_key:
        return None

    # Check if a bootstrap key or matching prefix already exists
    existing = db.query(ApiKey).filter(ApiKey.name == "Bootstrap Administrator").first()
    if existing:
        return existing

    logger.info("Bootstrapping initial admin key from environment...")
    key_record, _ = create_key(
        db=db,
        name="Bootstrap Administrator",
        scopes=["admin", "operator", "internal"],
        expires_days=365,
        custom_raw_key=bootstrap_key,
    )
    return key_record
