"""ARQ client for enqueuing background tasks to Redis (Phase A4)."""
import logging
from typing import Any, Optional
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import settings

logger = logging.getLogger("revive.jobs.client")

_redis_pool: Optional[ArqRedis] = None


async def get_redis_pool() -> ArqRedis:
    """Get or create the shared ARQ Redis connection pool."""
    global _redis_pool
    if _redis_pool is None:
        redis_settings = RedisSettings.from_dsn(settings.redis_url)
        _redis_pool = await create_pool(redis_settings)
    return _redis_pool


async def close_redis_pool() -> None:
    """Close the shared ARQ Redis connection pool on app shutdown."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.close()
        _redis_pool = None


async def enqueue_job(
    function_name: str,
    *args: Any,
    job_id: Optional[str] = None,
    **kwargs: Any,
) -> Optional[str]:
    """Enqueue a job to Redis for the ARQ worker to process.

    Returns the ARQ job ID on success.
    """
    pool = await get_redis_pool()
    job = await pool.enqueue_job(function_name, *args, _job_id=job_id, **kwargs)
    if job:
        return job.job_id
    return None
