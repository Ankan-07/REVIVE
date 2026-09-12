"""FastAPI authentication, scoped authorization, and session verification (Phase A2.3, A2.4, A2.5).

Supports:
1. API Key authentication via Authorization: Bearer <key> or X-API-Key: <key>.
2. Secure session cookies (revive_session) exchanging raw keys for httpOnly cookies.
3. Role scoping (operator, internal, admin, webhooks:receive).
4. Production protection guard: admin simulation routes strictly blocked in prod.
5. Per-key rate limiting (60 req/min) and daily quotas.
6. Immutable usage auditing in key_usage_events.
"""
import base64
import json
import hmac
import hashlib
import time
from typing import Callable, List, Optional, Set
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.services import api_key_service
from app.services.rate_limiter import rate_limiter

SESSION_COOKIE_NAME = "revive_session"


class AuthContext(BaseModel):
    """Context of the verified caller attached to each authenticated request."""
    key_id: str
    name: str
    scopes: Set[str]
    is_session: bool = False

    def has_scope(self, scope: str) -> bool:
        """Check if caller has a specific scope. 'admin' inherits all scopes."""
        if "admin" in self.scopes:
            return True
        return scope in self.scopes


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Sign payload using HMAC-SHA256."""
    sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode("utf-8")


def create_session_token(key_id: str, name: str, scopes: List[str]) -> str:
    """Create a signed, time-limited session token string."""
    payload = {
        "key_id": key_id,
        "name": name,
        "scopes": scopes,
        "exp": int(time.time()) + settings.session_ttl_seconds,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("utf-8")
    signature_b64 = _sign_payload(payload_bytes, settings.session_secret_key)
    return f"{payload_b64}.{signature_b64}"


def decode_session_token(token: str) -> Optional[dict]:
    """Decode and verify HMAC signature and expiration of a session token."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, signature_b64 = token.split(".", 1)
        payload_bytes = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
        expected_sig = _sign_payload(payload_bytes, settings.session_secret_key)
        if not hmac.compare_digest(signature_b64, expected_sig):
            return None

        payload = json.loads(payload_bytes.decode("utf-8"))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def get_current_auth(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
    revive_session: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
) -> AuthContext:
    """Resolve and verify authentication from headers or session cookie."""
    raw_key: Optional[str] = None

    if authorization and authorization.startswith("Bearer "):
        raw_key = authorization[len("Bearer "):].strip()
    elif x_api_key:
        raw_key = x_api_key.strip()

    # 1. API Key Auth
    if raw_key:
        api_key = api_key_service.verify_key(db, raw_key)
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired API key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        scopes = set(s.strip() for s in api_key.scopes.split(",") if s.strip())
        return AuthContext(
            key_id=str(api_key.id),
            name=str(api_key.name),
            scopes=scopes,
            is_session=False,
        )

    # 2. Session Cookie Auth
    if revive_session:
        session_data = decode_session_token(revive_session)
        if not session_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Verify underlying key was not revoked (instant revocation propagation, A2.6)
        key_record = api_key_service.get_key_by_id(db, session_data["key_id"])
        if not key_record or key_record.revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )

        scopes = set(session_data.get("scopes", []))
        return AuthContext(
            key_id=session_data["key_id"],
            name=session_data.get("name", "Unknown Operator"),
            scopes=scopes,
            is_session=True,
        )

    # No credentials supplied
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_api_key(*required_scopes: str) -> Callable:
    """FastAPI dependency factory enforcing scopes, rate limits, quotas, and production guards."""
    def dependency(
        request: Request,
        auth: AuthContext = Depends(get_current_auth),
        db: Session = Depends(get_db),
    ) -> AuthContext:
        # Check required scopes
        for scope in required_scopes:
            if not auth.has_scope(scope):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient permissions: requires scope '{scope}'",
                )

        # Admin in production guard (Phase A2.3, A3.5)
        # Prevents running simulation benchmarks or admin state mutations on live DB
        if "admin" in required_scopes or ("admin" in auth.scopes and request.url.path.startswith("/simulation")):
            if settings.app_env.lower() == "prod" and not settings.admin_allowed_in_prod:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin actions and simulation benchmarks are disabled in production environment",
                )

        # Per-key rate limit check (60 req/min)
        allowed, retry_after = rate_limiter.check_rate_limit(auth.key_id, limit_per_minute=60)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded: 60 requests per minute per key",
                headers={"Retry-After": str(retry_after)},
            )

        # Daily quota checks on expensive routes
        path = request.url.path
        if "/run-agent" in path:
            allowed, retry_after = rate_limiter.check_daily_quota(auth.key_id, "run_agent", daily_limit=100)
            if not allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Daily quota exceeded for agent execution (100 runs/day)",
                    headers={"Retry-After": str(retry_after)},
                )
        elif "/razorpay/create-order" in path:
            allowed, retry_after = rate_limiter.check_daily_quota(auth.key_id, "create_order", daily_limit=500)
            if not allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Daily quota exceeded for order creation (500 orders/day)",
                    headers={"Retry-After": str(retry_after)},
                )

        # Audit usage event (Phase A2.6)
        client_ip = request.client.host if request.client else None
        api_key_service.record_usage(
            db=db,
            key_id=auth.key_id,
            route=request.url.path,
            method=request.method,
            ip=client_ip,
            status_code=200,
        )

        return auth

    return dependency
