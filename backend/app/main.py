import app.observability  # Ensure observability env vars set on startup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api import health

app = FastAPI(
    title="Revenue Rescue Engine API",
    description="Autonomous AI Revenue Recovery Engine",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)


@app.get("/")
def root():
    return {
        "name": "Revenue Rescue Engine API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }
