"""In-memory abuse and cost protection for ``POST /api/chat``.

Two limits, both process-local (the app runs as a single worker on a single
replica, see CLAUDE.md):

- a per-IP rolling window of ``RATE_LIMIT_PER_MINUTE`` requests per 60 seconds;
- a global ``DAILY_REQUEST_CAP`` on accepted requests per UTC day.

``check_and_record`` is synchronous and never awaits, so under asyncio each
call is atomic: concurrent requests cannot both take the last slot.
"""

import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Request

WINDOW_SECONDS = 60.0
SECONDS_PER_DAY = 86400

Clock = Callable[[], float]


@dataclass(frozen=True)
class Rejection:
    code: str  # "rate_limited" | "daily_limit"
    retry_after: int  # whole seconds, always >= 1


class RateLimiter:
    def __init__(self) -> None:
        # IP -> timestamps of accepted requests still inside the window, oldest
        # first. Ordered by each IP's most recent accepted request so stale IPs
        # can be pruned from the front.
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._day: int | None = None
        self._day_count = 0

    def tracked_ips(self) -> int:
        return len(self._hits)

    def check_and_record(
        self, ip: str, now: float, per_minute: int, daily_cap: int
    ) -> Rejection | None:
        """Reject, or count the request against both limits and return None.

        A rejected request is never counted against either limit.
        """
        self._prune(now)

        hits = self._hits.get(ip)
        if hits is not None:
            while hits and hits[0] <= now - WINDOW_SECONDS:
                hits.popleft()
        if hits and len(hits) >= per_minute:
            # The hit whose expiry frees a slot (the oldest, unless the limit
            # was lowered while more hits than the new limit are in the window).
            wait = hits[len(hits) - per_minute] + WINDOW_SECONDS - now
            return Rejection("rate_limited", max(1, math.ceil(wait)))

        day = int(now // SECONDS_PER_DAY)
        if day != self._day:
            self._day, self._day_count = day, 0
        if self._day_count >= daily_cap:
            wait = (day + 1) * SECONDS_PER_DAY - now
            return Rejection("daily_limit", max(1, math.ceil(wait)))

        if hits is None:
            hits = self._hits[ip] = deque()
        hits.append(now)
        self._hits.move_to_end(ip)
        self._day_count += 1
        return None

    def _prune(self, now: float) -> None:
        cutoff = now - WINDOW_SECONDS
        for ip in list(self._hits):
            hits = self._hits[ip]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if hits:
                # Ordered by latest hit, so every IP after this one is fresh too.
                break
            del self._hits[ip]


@lru_cache
def get_limiter() -> RateLimiter:
    return RateLimiter()


def get_clock() -> Clock:
    """Dependency returning the current UTC epoch seconds; tests override it."""
    return time.time


def client_ip(request: Request) -> str:
    """Right-most ``X-Forwarded-For`` entry, else the socket peer.

    Railway's edge appends the real client address to the right, so the
    left-most entries are client-controlled and must not be trusted.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    entries = [part.strip() for part in forwarded.split(",") if part.strip()]
    if entries:
        return entries[-1]
    return request.client.host if request.client else "unknown"
