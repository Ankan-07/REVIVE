import app.observability  # Ensure observability env vars set on startup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from contextlib import asynccontextmanager
from app.api import health, simulation, events, cases, escalations, analytics, jobs, checkout, auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.db import SessionLocal
    from app.services import api_key_service
    db = SessionLocal()
    try:
        api_key_service.bootstrap_initial_key(db)
    except Exception:
        pass
    finally:
        db.close()
    yield


app = FastAPI(
    title="Revenue Rescue Engine API",
    description="Autonomous AI Revenue Recovery Engine",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(simulation.router)
app.include_router(events.router)
app.include_router(cases.router)
app.include_router(escalations.router)
app.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
app.include_router(jobs.router)
app.include_router(checkout.router)


@app.get("/")
def root():
    return {
        "name": "Revenue Rescue Engine API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }
