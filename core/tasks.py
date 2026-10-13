"""
Task dashboard for FRIDAY: a small thread-safe board that records every task
(tool call) with a status - RUNNING, DONE or FAILED - and tells the UI when it
changes.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

MAX_TASKS = 50


class TaskBoard:
    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: list[dict] = []
        self._next = 1
        self.on_change: Callable[[], None] | None = None

    def _notify(self) -> None:
        cb = self.on_change
        if cb:
            try:
                cb()
            except Exception:
                pass

    def start(self, name: str, detail: str = "") -> int:
        with self._lock:
            tid = self._next
            self._next += 1
            self._tasks.append({"id": tid, "name": name, "detail": detail[:60],
                                "status": "RUNNING", "started": time.time(), "ended": None,
                                "note": ""})
            del self._tasks[:-MAX_TASKS]
        self._notify()
        return tid

    def finish(self, tid: int, ok: bool, note: str = "") -> None:
        with self._lock:
            for t in self._tasks:
                if t["id"] == tid:
                    t["status"] = "DONE" if ok else "FAILED"
                    t["ended"] = time.time()
                    t["note"] = note[:120]
                    break
        self._notify()

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [dict(t) for t in self._tasks]

    def counts(self) -> dict:
        s = self.snapshot()
        return {k: sum(1 for t in s if t["status"] == k) for k in ("RUNNING", "DONE", "FAILED")}


def looks_failed(result: str) -> bool:
    """Heuristic for tool results that report failure as text instead of raising."""
    r = (result or "").strip().lower()
    return r.startswith(("search failed", "unknown tool", "no results", "error", "failed",
                         "could not", "couldn't", "unable to", "please provide", "specify "))


TASKS = TaskBoard()
