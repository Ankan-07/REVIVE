from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["Health"])


@router.get("/health")
def get_health():
    return {"status": "ok"}


@router.get("/healthz")
def get_healthz():
    return {"status": "ok"}


@router.get("/readyz")
def get_readyz():
    """Readiness probe — verifies DB connectivity before reporting healthy.

    Docker HEALTHCHECK and load balancers should use this endpoint.
    Returns 200 when the app is ready to serve requests, 503 when degraded.
    """
    try:
        from sqlalchemy import text
        from app.db import SessionLocal
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        return {"status": "ok"}
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "detail": str(exc)},
        )
