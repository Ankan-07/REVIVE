"""ARQ WorkerSettings stub (Phase A3).

The worker container needs a valid ARQ entrypoint to start without crashing.
Job function bodies are implemented in Phase A4. Add each job to `functions`
and `cron_jobs` as it lands.

Redis URL is sourced from the REDIS_URL environment variable.
"""
from arq.connections import RedisSettings
from app.config import settings


class WorkerSettings:
    """ARQ worker configuration.

    ARQ discovers this class via:  python -m arq app.jobs.worker.WorkerSettings
    """

    # Populated incrementally in A4:
    # functions = [run_agent_job, verify_promises_job, ...]
    functions: list = []

    # Cron jobs populated in A4:
    # cron_jobs = [cron(reconcile_job, hour=3, minute=0)]
    cron_jobs: list = []

    # How long to keep job result in Redis after completion (seconds).
    keep_result = 3600  # 1 hour

    # Max retries before a job is marked FAILED (A4 hardens this with DLQ row).
    max_tries = 3

    @classmethod
    def redis_settings(cls) -> RedisSettings:  # type: ignore[override]
        redis_url: str = getattr(settings, "redis_url", "redis://redis:6379")
        return RedisSettings.from_dsn(redis_url)
