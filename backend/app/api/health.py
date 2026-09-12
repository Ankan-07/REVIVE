from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
def get_health():
    return {"status": "ok"}


@router.get("/healthz")
def get_healthz():
    return {"status": "ok"}


@router.get("/readyz")
def get_readyz():
    return {"status": "ok"}
