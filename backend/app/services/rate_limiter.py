"""In-memory thread-safe rate limiter and daily quota tracker (Phase A2.6).

Enforces:
1. Per-key minute sliding window (e.g. 60 req/min).
2. Per-key daily quota on expensive/money-touching routes (e.g. run-agent, create-order).
"""
from collections import defaultdict
import threading
import time
from typing import Dict, List, Tuple


class RateLimiter:
    """Sliding-window rate limiter and daily quota tracker."""

    def __init__(self):
        self._lock = threading.Lock()
        # key_id -> list of float timestamps within current window
        self._minute_buckets: Dict[str, List[float]] = defaultdict(list)
        # key_id:route_category -> list of float timestamps within 24 hours
        self._daily_buckets: Dict[str, List[float]] = defaultdict(list)

    def check_rate_limit(self, key_id: str, limit_per_minute: int = 60) -> Tuple[bool, int]:
        """Check if request is within per-minute limit.
        
        Returns (allowed: bool, retry_after_seconds: int).
        """
        now = time.time()
        window_start = now - 60.0

        with self._lock:
            timestamps = self._minute_buckets[key_id]
            # Prune older than 60s
            valid_timestamps = [t for t in timestamps if t > window_start]
            if len(valid_timestamps) >= limit_per_minute:
                # Oldest timestamp in window determines retry-after
                oldest = valid_timestamps[0]
                retry_after = max(1, int(oldest + 60.0 - now))
                self._minute_buckets[key_id] = valid_timestamps
                return False, retry_after

            valid_timestamps.append(now)
            self._minute_buckets[key_id] = valid_timestamps
            return True, 0

    def check_daily_quota(self, key_id: str, route_tag: str, daily_limit: int) -> Tuple[bool, int]:
        """Check if request is within daily quota for a route category.
        
        Returns (allowed: bool, retry_after_seconds: int).
        """
        now = time.time()
        window_start = now - 86400.0  # 24 hours
        bucket_key = f"{key_id}:{route_tag}"

        with self._lock:
            timestamps = self._daily_buckets[bucket_key]
            valid_timestamps = [t for t in timestamps if t > window_start]
            if len(valid_timestamps) >= daily_limit:
                oldest = valid_timestamps[0]
                retry_after = max(1, int(oldest + 86400.0 - now))
                self._daily_buckets[bucket_key] = valid_timestamps
                return False, retry_after

            valid_timestamps.append(now)
            self._daily_buckets[bucket_key] = valid_timestamps
            return True, 0

    def reset(self):
        """Clear all rate limit state (useful in tests)."""
        with self._lock:
            self._minute_buckets.clear()
            self._daily_buckets.clear()


# Global rate limiter instance
rate_limiter = RateLimiter()
