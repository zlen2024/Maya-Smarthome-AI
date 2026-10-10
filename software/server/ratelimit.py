"""Rate limiting and failure lockout.

Two shapes, because the threats differ:

* ``RateLimit`` counts **every** call in a sliding window. Use it where the cost
  of a request is the problem — a paid model call, an Open API key hammering the
  server.
* ``FailureLock`` counts **only failures** and locks the key out for a while once
  they pile up. Use it on anything guessable: a 6-digit house PIN, a 4-digit
  child PIN, a password, HTTP Basic on ``/admin``. Successes clear the counter,
  so a legitimate user who mistypes twice is never punished.

State lives in this process' RAM. That is a deliberate fit, not an oversight:
Maya runs as a single uvicorn process against one SQLite file
(``wiki/pages/known-gaps.md``), so there is nothing to share it with. Behind
several instances this would need a shared store — the limits would still hold
per instance, just multiplied by the instance count. Counters also reset on
restart, which is why every lockout that matters is *also* written to the house
activity log, which survives.
"""
import threading
import time
from fastapi import HTTPException, Request

# Sweep expired keys once the table gets big, so a flood of spoofed IPs or
# device ids cannot grow this without bound.
_SWEEP_THRESHOLD = 4096


class RateLimit:
    """Sliding window over every call. ``limit`` calls per ``window`` seconds."""

    def __init__(self, limit: int, window: float, name: str):
        self.limit = limit
        self.window = float(window)
        self.name = name
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, now: float | None = None) -> None:
        """Record one call. Raises 429 when the window is full."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if len(self._hits) > _SWEEP_THRESHOLD:
                self._sweep(now)
            stamps = [t for t in self._hits.get(key, ()) if now - t < self.window]
            if len(stamps) >= self.limit:
                retry = max(1, int(self.window - (now - stamps[0])) + 1)
                self._hits[key] = stamps
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many requests ({self.name}). Try again in {retry}s.",
                    headers={"Retry-After": str(retry)},
                )
            stamps.append(now)
            self._hits[key] = stamps

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def clear_all(self) -> None:
        """Forget every counter. For tests, and for an operator who has to lift a
        limit without a restart."""
        with self._lock:
            self._hits.clear()

    def _sweep(self, now: float) -> None:
        for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window]:
            del self._hits[k]


class FailureLock:
    """``limit`` failures inside ``window`` seconds locks the key for ``lockout``.

    ``guard`` is called before doing the work, ``fail`` after a rejection and
    ``clear`` after a success.
    """

    def __init__(self, limit: int, window: float, lockout: float, name: str):
        self.limit = limit
        self.window = float(window)
        self.lockout = float(lockout)
        self.name = name
        self._fails: dict[str, list[float]] = {}
        self._locked: dict[str, float] = {}
        self._lock = threading.Lock()

    def guard(self, key: str, now: float | None = None) -> None:
        """Raises 429 while the key is locked out."""
        now = time.monotonic() if now is None else now
        with self._lock:
            until = self._locked.get(key)
            if until is None:
                return
            if now >= until:
                del self._locked[key]
                self._fails.pop(key, None)
                return
            retry = max(1, int(until - now) + 1)
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts ({self.name}). Locked for {retry}s.",
            headers={"Retry-After": str(retry)},
        )

    def fail(self, key: str, now: float | None = None) -> bool:
        """Record a failure. Returns True if this failure triggered the lockout."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if len(self._fails) > _SWEEP_THRESHOLD:
                self._sweep(now)
            stamps = [t for t in self._fails.get(key, ()) if now - t < self.window]
            stamps.append(now)
            self._fails[key] = stamps
            if len(stamps) >= self.limit:
                self._locked[key] = now + self.lockout
                del self._fails[key]
                return True
            return False

    def clear(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
            self._locked.pop(key, None)

    def clear_all(self) -> None:
        """Forget every failure and lockout. For tests, and for an operator who
        has to let a locked-out household back in without a restart."""
        with self._lock:
            self._fails.clear()
            self._locked.clear()

    def _sweep(self, now: float) -> None:
        for k in [k for k, v in self._fails.items() if not v or now - v[-1] >= self.window]:
            del self._fails[k]
        for k in [k for k, t in self._locked.items() if now >= t]:
            del self._locked[k]


def client_ip(request: Request) -> str:
    """Caller's IP as seen through Fly's proxy.

    ``request.client.host`` is the proxy itself in production, which would put
    every user in one bucket, so prefer the headers Fly sets. ``X-Forwarded-For``
    is client-controlled in general; here only Fly can reach the app port, so its
    left-most entry is the real peer.
    """
    fly = request.headers.get("fly-client-ip")
    if fly:
        return fly.strip()
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        first = fwd.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"
