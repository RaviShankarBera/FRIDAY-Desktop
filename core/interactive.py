"""Read-back gate: actions with side effects are repeated back and only run after a spoken yes.

First call  -> returns "[CONFIRM] ..." and remembers exactly what was read back.
Second call -> runs only if the user said yes (confirmed=true) AND it matches what was read back,
               within TTL seconds. The model cannot skip the read-back by passing confirmed=true up front.
"""
from __future__ import annotations

import re
import time

TTL = 120.0
_PENDING: dict[str, float] = {}


def _key(tool: str, summary: str) -> str:
    return tool + "|" + re.sub(r"\s+", " ", summary.strip().lower())


def is_true(v) -> bool:
    return str(v).strip().lower() in ("true", "yes", "1", "y")


def gate(tool: str, summary: str, confirmed, now: float | None = None) -> str | None:
    """None = go ahead. Otherwise the text to return to the model instead of acting."""
    now = time.monotonic() if now is None else now
    for k in [k for k, t in _PENDING.items() if now - t > TTL]:
        _PENDING.pop(k, None)
    k = _key(tool, summary)
    if is_true(confirmed) and k in _PENDING:
        _PENDING.pop(k, None)
        return None
    _PENDING[k] = now
    return (f"[CONFIRM] I have NOT done this yet. Read it back to the user in one short sentence: "
            f"\"{summary}. Shall I go ahead?\" Then wait for their answer. If they say yes, call {tool} again with "
            f"exactly the same details plus confirmed='true'. If they say no or change anything, do not run it.")


def reset() -> None:
    _PENDING.clear()
