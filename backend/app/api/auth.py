"""Authentication and operator session endpoints (Phase A2.3, A2.5).

Provides:
- POST /auth/session (Exchanges raw API key for httpOnly session cookie)
- GET /auth/me (Returns active operator identity and scopes)
- POST /auth/logout (Clears httpOnly session cookie)
- Admin key management: GET /admin/keys, POST /admin/keys, POST /admin/keys/{id}/revoke
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import AuthContext, create_session_token, get_current_auth, require_api_key, SESSION_COOKIE_NAME
from app.config import settings
from app.db import get_db
from app.services import api_key_service

router = APIRouter(tags=["Authentication"])


class SessionLoginRequest(BaseModel):
    api_key: str = Field(..., description="Plaintext service API key")


class SessionResponse(BaseModel):
    authenticated: bool
    name: str
    scopes: List[str]
    expires_in_seconds: int
    token: str


class UserProfileResponse(BaseModel):
    key_id: str
    name: str
    scopes: List[str]
    is_session: bool


class CreateKeyRequest(BaseModel):
    name: str = Field(..., description="Operator or service name (e.g. Alice Vance)")
    scopes: List[str] = Field(default=["operator"], description="List of scopes: operator, internal, admin, webhooks:receive")
    expires_days: Optional[int] = Field(default=90, description="Expiration in days (null for non-expiring)")


class KeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    scopes: List[str]
    revoked: bool
    created_at: Optional[datetime]
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]
    raw_key: Optional[str] = None  # Only returned upon initial creation


@router.post("/auth/session", response_model=SessionResponse)
def login_session(
    body: SessionLoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Exchange a valid operator API key for a secure, short-lived session token and cookie.
    
    Returns the session token for client-side Bearer authorization across domains,
    and also sets an httpOnly session cookie for same-site / cookie-enabled contexts.
    """
    key = api_key_service.verify_key(db, body.api_key)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or revoked API key",
        )

    scopes = [s.strip() for s in key.scopes.split(",") if s.strip()]
    token = create_session_token(key.id, key.name, scopes)

    is_prod = settings.app_env.lower() == "prod"
    # In production/cross-site environments, SameSite must be "none" with secure=True
    # In local development over plain HTTP, SameSite="lax" with secure=False is used
    samesite_val = "none" if is_prod else "lax"
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=is_prod,
        samesite=samesite_val,
    )

    return SessionResponse(
        authenticated=True,
        name=key.name,
        scopes=scopes,
        expires_in_seconds=settings.session_ttl_seconds,
        token=token,
    )


@router.get("/auth/me", response_model=UserProfileResponse)
def get_current_user_profile(
    auth: AuthContext = Depends(get_current_auth),
):
    """Retrieve the currently authenticated operator profile."""
    return UserProfileResponse(
        key_id=auth.key_id,
        name=auth.name,
        scopes=sorted(list(auth.scopes)),
        is_session=auth.is_session,
    )


@router.post("/auth/logout")
def logout_session(response: Response):
    """Clear the session cookie."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
    )
    return {"status": "logged_out"}


# Admin Key Management endpoints
@router.get("/admin/keys", response_model=List[KeyResponse])
def list_api_keys(
    include_revoked: bool = False,
    auth: AuthContext = Depends(require_api_key("admin")),
    db: Session = Depends(get_db),
):
    """List all API keys (admin scope required)."""
    keys = api_key_service.list_keys(db, include_revoked=include_revoked)
    return [
        KeyResponse(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            scopes=[s.strip() for s in k.scopes.split(",") if s.strip()],
            revoked=k.revoked,
            created_at=k.created_at,
            expires_at=k.expires_at,
            last_used_at=k.last_used_at,
        )
        for k in keys
    ]


@router.post("/admin/keys", response_model=KeyResponse, status_code=status.HTTP_201_CREATED)
def create_api_key_endpoint(
    body: CreateKeyRequest,
    auth: AuthContext = Depends(require_api_key("admin")),
    db: Session = Depends(get_db),
):
    """Create a new service API key and print plaintext key once (admin scope required)."""
    try:
        key_record, raw_key = api_key_service.create_key(
            db=db,
            name=body.name,
            scopes=body.scopes,
            expires_days=body.expires_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return KeyResponse(
        id=key_record.id,
        name=key_record.name,
        key_prefix=key_record.key_prefix,
        scopes=[s.strip() for s in key_record.scopes.split(",") if s.strip()],
        revoked=key_record.revoked,
        created_at=key_record.created_at,
        expires_at=key_record.expires_at,
        last_used_at=key_record.last_used_at,
        raw_key=raw_key,
    )


@router.post("/admin/keys/{key_id}/revoke")
def revoke_api_key_endpoint(
    key_id: str,
    auth: AuthContext = Depends(require_api_key("admin")),
    db: Session = Depends(get_db),
):
    """Revoke an API key immediately (admin scope required)."""
    success = api_key_service.revoke_key(db, key_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    return {"status": "revoked", "key_id": key_id}
