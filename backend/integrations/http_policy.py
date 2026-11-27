"""How every outbound call retries, waits, gives up, and is logged.

One policy for Graph, Consensus and Brightcove, because the three clients had
grown three copies of the same loop with the same three faults (audit
2026-11-26, optimisation plan workstream WS-B):

1. **Non-idempotent calls were retried blind.** Any transport error -- a read
   timeout *after* the request was sent included -- and any 5xx was retried
   for every method. A POST that SharePoint or Consensus had already acted on
   then ran twice: two Demo Requests, two DemoBoards. Now a non-idempotent
   call is retried only when it provably did not run: the connection never
   opened (`ConnectError`, `ConnectTimeout`, `PoolTimeout`), the service
   throttled it (429), or it said "unavailable, come back later" (503 with
   Retry-After).
2. **Retry-After as an HTTP date raised ValueError.** RFC 9110 allows either
   form. Both are parsed now, and the wait is capped.
3. **No budget.** Four attempts with 30-second timeouts and 30-second waits
   is up to ~3-4 minutes for a single call -- right for an overnight sync, and
   a frozen page when a person is waiting. A request path enters
   `interactive()` and gets two attempts inside ten seconds instead.

A small circuit breaker sits on top: after `BREAKER_THRESHOLD` consecutive
calls to one service fail outright, *interactive* calls to it fail at once
for `BREAKER_SECONDS`, so a SharePoint outage costs each page view nothing
rather than ten seconds of a worker thread. Background calls (syncs) still
go through; their first success closes it again.
"""
from __future__ import annotations

import contextvars
import logging
import random
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.parse import urlsplit

import httpx


@dataclass(frozen=True)
class Budget:
    """How hard one logical call may try.

    `deadline` bounds the whole call, waits included; None means the attempts
    alone bound it (background jobs). `connect` overrides the connect timeout
    per attempt. `max_wait` caps one backoff wait.
    """
    name: str
    attempts: int
    max_wait: float
    deadline: float | None = None
    connect: float | None = None


#: For a person waiting on a page: two tries, ten seconds overall.
INTERACTIVE = Budget("interactive", attempts=2, max_wait=3.0, deadline=10.0, connect=5.0)

#: Each client's own default for background work; these are the budgets the
#: clients always had, kept so a sync rides out a throttling burst.
GRAPH_BACKGROUND = Budget("background", attempts=4, max_wait=30.0)
CONSENSUS_BACKGROUND = Budget("background", attempts=3, max_wait=10.0)
BRIGHTCOVE_BACKGROUND = Budget("background", attempts=4, max_wait=30.0)

_override: contextvars.ContextVar[Budget | None] = contextvars.ContextVar(
    "tmh_http_budget", default=None)


def budget(default: Budget) -> Budget:
    """The budget in force: `interactive()` if a request path entered it, else
    the client's own default. A thread the app starts itself begins with an
    empty context, so a background job never inherits a request's budget."""
    return _override.get() or default


@contextmanager
def interactive():
    """Run the calls inside with the short, request-path budget."""
    token = _override.set(INTERACTIVE)
    try:
        yield
    finally:
        _override.reset(token)


def is_interactive() -> bool:
    return _override.get() is INTERACTIVE


# ─────────────────────────────────────────────────────────── idempotency
#: Methods that may be repeated without changing the outcome. PATCH is here
#: because every PATCH this app sends sets fields to values (doing it twice
#: lands in the same state); a caller with a PATCH that is not like that
#: passes `idempotent=False`. A PUT with `conflictBehavior=rename` is the
#: other exception, and its caller says so.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE", "PATCH"})

#: The request never reached the server, so even a POST can be resent.
NEVER_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def retryable_error(exc: BaseException, idempotent: bool) -> bool:
    if isinstance(exc, NEVER_SENT):
        return True
    return idempotent and isinstance(exc, httpx.TransportError)


def retryable_status(response: httpx.Response, idempotent: bool) -> bool:
    status = response.status_code
    if status == 429:
        return True          # throttled: Graph and Consensus did not act on it
    if idempotent:
        return status >= 500
    return status == 503 and "Retry-After" in response.headers


# ─────────────────────────────────────────────────────────── Retry-After
def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Seconds to wait, from either form RFC 9110 allows: delta-seconds
    ("120") or an HTTP date ("Wed, 26 Nov 2026 10:00:00 GMT"). None when
    absent or unreadable; never negative."""
    if not value:
        return None
    text = value.strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return max(0.0, (when - now).total_seconds())


def backoff(attempt: int) -> float:
    """1, 2, 4, 8 s, with a little jitter so parallel callers spread out."""
    return min(2 ** attempt, 8) * (1 + random.random() * 0.1)


# ─────────────────────────────────────────────────────────── circuit breaker
BREAKER_THRESHOLD = 5
BREAKER_SECONDS = 60.0

_breaker_lock = threading.Lock()
_breaker: dict[str, tuple[int, float]] = {}      # service -> (failures, open until)


def _breaker_open(service: str) -> bool:
    with _breaker_lock:
        failures, until = _breaker.get(service, (0, 0.0))
        return failures >= BREAKER_THRESHOLD and time.monotonic() < until


def _record(service: str, ok: bool) -> None:
    with _breaker_lock:
        if ok:
            _breaker.pop(service, None)
            return
        failures = _breaker.get(service, (0, 0.0))[0] + 1
        _breaker[service] = (failures, time.monotonic() + BREAKER_SECONDS)


def reset_breakers() -> None:
    with _breaker_lock:
        _breaker.clear()


# ─────────────────────────────────────────────────────────── the loop
class GaveUp(Exception):
    """Every attempt the budget allowed failed. `cause` is the last
    exception, if the last failure was one; the message says what happened."""

    def __init__(self, message: str, cause: BaseException | None = None):
        super().__init__(message)
        self.cause = cause


#: A call slower than this is logged even when it succeeds.
SLOW_SECONDS = 1.0


def log_path(url: object) -> str:
    """The path alone: queries can carry tokens (pre-authenticated download
    URLs, delta tokens, signed renditions) and never belong in a log."""
    return urlsplit(str(url)).path or "/"


def send(attempt: Callable[[dict], httpx.Response], *, service: str, method: str,
         url: object, idempotent: bool, policy: Budget,
         logger: logging.Logger) -> httpx.Response:
    """Run `attempt` until it gives a final response or the budget runs out.

    `attempt(extra)` performs one HTTP call, passing `extra` (a `timeout`
    when the budget has a deadline) on to httpx. Returns the first response
    that is not worth retrying, whatever its status -- interpreting it is the
    caller's job. Raises `GaveUp` when the attempts or the deadline are spent,
    and when the breaker is open for an interactive call.
    """
    interactive_call = policy.deadline is not None
    path = log_path(url)
    if interactive_call and _breaker_open(service):
        raise GaveUp(f"{service} is failing; not trying again for up to "
                     f"{BREAKER_SECONDS:.0f} s")

    started = time.monotonic()
    last_error: BaseException | None = None
    last_status: int | None = None

    for n in range(policy.attempts):
        extra: dict = {}
        if policy.deadline is not None:
            remaining = policy.deadline - (time.monotonic() - started)
            if remaining <= 0:
                break
            extra["timeout"] = httpx.Timeout(remaining, connect=min(policy.connect or remaining,
                                                                    remaining))
        t0 = time.monotonic()
        wait: float | None = None
        try:
            response = attempt(extra)
        except httpx.HTTPError as exc:
            elapsed = time.monotonic() - t0
            last_error, last_status = exc, None
            logger.warning("%s %s %s failed after %d ms (attempt %d/%d): %s",
                           service, method, path, elapsed * 1000, n + 1,
                           policy.attempts, type(exc).__name__)
            if not retryable_error(exc, idempotent):
                _record(service, ok=False)
                raise GaveUp(f"{type(exc).__name__}: {exc} (not retried: {method} "
                             f"may already have been acted on)", exc) from exc
            wait = backoff(n)
        else:
            elapsed = time.monotonic() - t0
            status = response.status_code
            retry = retryable_status(response, idempotent)
            if retry or (status >= 400 and status != 404) or elapsed > SLOW_SECONDS:
                level = logging.WARNING if status >= 400 and status != 404 else logging.INFO
                logger.log(level, "%s %s %s -> %d in %d ms (attempt %d/%d)",
                           service, method, path, status, elapsed * 1000, n + 1,
                           policy.attempts)
            if not retry:
                _record(service, ok=status < 500)
                return response
            last_error, last_status = None, status
            wait = parse_retry_after(response.headers.get("Retry-After"))
            if wait is None:
                wait = backoff(n)

        if n + 1 >= policy.attempts:
            break
        if policy.deadline is not None:
            # Told to come back later than the budget allows: say so now
            # rather than sleeping through the person's patience.
            if (time.monotonic() - started) + wait >= policy.deadline:
                break
        time.sleep(min(wait, policy.max_wait))

    _record(service, ok=last_status == 429)       # throttling is not an outage
    reason = (f"HTTP {last_status} from {service}" if last_status is not None
              else f"{type(last_error).__name__}: {last_error}")
    logger.warning("%s %s %s gave up after %d ms (%s budget): %s", service, method, path,
                   (time.monotonic() - started) * 1000, policy.name, reason)
    raise GaveUp(reason, last_error)
