"""Limits for the hosted demo, so a public link can't run up a bill. Off unless EMERALD_PUBLIC=1.

Everyone shares one demo world. It clears itself after a quiet spell, so each visitor tends to find a fresh one.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

# kind: (per visitor, per this many seconds, for everyone per day)
# Worst case a day is about $1 of Bedrock for cases and $3 for voice.
LIMITS = {"case": (15, 3600, 300), "voice": (4, 3600, 40), "sync": (6, 3600, 60)}
VOICE_SECONDS = 240
VOICE_AT_ONCE = 3
QUIET_RESET_SECONDS = 20 * 60
OFFLINE_NOTE = "The no-signal mode runs on a field worker's laptop with a local model, so it isn't part of this hosted demo. The video shows it."

_lock = threading.Lock()
_mine: dict[tuple[str, str], deque] = defaultdict(deque)
_everyone: dict[str, deque] = defaultdict(deque)
_last_activity = time.time()
voice_calls = 0


def enabled() -> bool:
    return os.environ.get("EMERALD_PUBLIC") == "1"


def visitor(headers, client_host: str | None) -> str:
    """CloudFront appends the address it saw to X-Forwarded-For, so the last entry is the one a visitor can't fake."""
    forwarded = [part.strip() for part in headers.get("x-forwarded-for", "").split(",") if part.strip()]
    return forwarded[-1] if forwarded else (client_host or "unknown")


def allow(kind: str, who: str, now: float | None = None) -> str | None:
    """None if this may go ahead, otherwise the reason to show."""
    if not enabled():
        return None
    per_visitor, window, per_day = LIMITS[kind]
    now = time.time() if now is None else now
    with _lock:
        mine, everyone = _mine[(kind, who)], _everyone[kind]
        while mine and now - mine[0] > window:
            mine.popleft()
        while everyone and now - everyone[0] > 86400:
            everyone.popleft()
        if len(mine) >= per_visitor:
            return "You've reached the demo's limit for now. Please try again in an hour."
        if len(everyone) >= per_day:
            return "The public demo has reached today's limit. Please try again tomorrow."
        mine.append(now)
        everyone.append(now)
    return None


def touch(now: float | None = None) -> None:
    global _last_activity
    _last_activity = time.time() if now is None else now


def quiet_too_long(now: float | None = None) -> bool:
    now = time.time() if now is None else now
    return enabled() and voice_calls == 0 and now - _last_activity > QUIET_RESET_SECONDS
