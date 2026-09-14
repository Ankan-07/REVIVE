import app.observability  # Ensure observability env vars set on startup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings, validate_environment
from contextlib import asynccontextmanager
from app.api import health, simulation, events, cases, escalations, analytics, jobs, checkout, auth, webhooks


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A5.1 & A5.2: Environment validation & test-mode guard
    validate_environment(settings)

    # A3.5: Production CORS guard — refuse to boot with localhost origins in prod.
    # This prevents accidentally exposing the live API to dev browser sessions.
    if settings.app_env.lower() == "prod":
        bad_origins = [
            o for o in settings.cors_origins
            if "localhost" in o or "127.0.0.1" in o
        ]
        if bad_origins:
            raise RuntimeError(
                f"[A3.5] APP_ENV=prod but CORS_ORIGINS still contains local origins: "
                f"{bad_origins}. "
                "Set CORS_ORIGINS to your production domain(s) before starting."
            )

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

# A3.5: Simulation and admin routes are hard-disabled in prod at registration time.
# The routes simply don't exist in the prod process, so a stray admin key can't reach them.
if settings.app_env.lower() != "prod":
    app.include_router(simulation.router)

app.include_router(events.router)
app.include_router(cases.router)
app.include_router(escalations.router)
app.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
app.include_router(jobs.router)
app.include_router(checkout.router)
app.include_router(webhooks.router)


@app.get("/")
def root():
    return {
        "name": "Revenue Rescue Engine API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }
