from collections import defaultdict, deque
from time import monotonic

from fastapi import HTTPException, status


class InMemoryRateLimiter:
    """Single-process sliding-window limiter for authentication endpoints."""

    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int = 10, window_seconds: int = 60) -> None:
        now = monotonic()
        attempts = self._attempts[key]
        while attempts and attempts[0] <= now - window_seconds:
            attempts.popleft()
        if len(attempts) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Try again later.",
            )
        attempts.append(now)


auth_rate_limiter = InMemoryRateLimiter()
