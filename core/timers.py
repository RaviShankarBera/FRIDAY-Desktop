"""Voice timers. A timer fires a callback (speak/notify) when it ends; list and cancel work by label."""
from __future__ import annotations

import re
import threading
import time
from typing import Callable

_lock = threading.Lock()
_timers: dict[int, dict] = {}
_next = 1
notify: Callable[[str], None] = lambda m: print(f"[Timer] {m}")

_UNITS = {"s": 1, "sec": 1, "second": 1, "m": 60, "min": 60, "minute": 60, "h": 3600, "hr": 3600, "hour": 3600}


def parse_duration(text: str) -> int | None:
    """'25 minutes', '1h 30m', '90s', '1.5 hours' -> seconds. None if unparseable or <= 0."""
    t = str(text or "").lower()
    total = 0.0
    found = False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b", t):
        total += float(num) * _UNITS[unit.rstrip("s") if unit.rstrip("s") in _UNITS else unit]
        found = True
    if not found and re.fullmatch(r"\s*\d+\s*", t):
        total, found = float(t) * 60, True          # bare number = minutes
    return int(total) if found and total > 0 else None


def start(seconds: int, label: str = "Timer") -> int:
    global _next
    with _lock:
        tid = _next; _next += 1
        th = threading.Timer(seconds, _fire, args=(tid,))
        th.daemon = True
        _timers[tid] = {"label": label, "ends": time.time() + seconds, "thread": th}
    th.start()
    return tid


def _fire(tid: int) -> None:
    with _lock:
        t = _timers.pop(tid, None)
    if t:
        try:
            notify(f"{t['label']} is done.")
        except Exception:
            pass


def active() -> list[tuple[int, str, int]]:
    now = time.time()
    with _lock:
        return [(i, t["label"], max(0, int(t["ends"] - now))) for i, t in _timers.items()]


def cancel(label: str = "") -> int:
    n = 0
    with _lock:
        for i in list(_timers):
            if not label or label.lower() in _timers[i]["label"].lower():
                _timers.pop(i)["thread"].cancel(); n += 1
    return n
