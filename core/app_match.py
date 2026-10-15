"""Match a spoken app name to apps that are actually installed.

Speech-to-text mishears product names ("Claude" -> "Cloud"). Instead of typing whatever it heard
into the Start menu, we look at the installed apps and decide:
  launch   - exact or near-certain match
  confirm  - plausible match, ask the user first ("Do you mean Claude?")
  none     - nothing close: say so, do not guess
Pure functions, so they are unit-tested without Windows.
"""
from __future__ import annotations

import difflib
import re

# Things speech recognition often gets wrong for app names: heard -> intended.
SOUNDALIKE = {
    "cloud": "claude", "clawed": "claude", "clod": "claude", "claud": "claude", "clode": "claude",
    "chat gpt": "chatgpt", "chat g p t": "chatgpt", "jarvis": "jarvis",
    "vs code": "visual studio code", "vscode": "visual studio code", "v s code": "visual studio code",
    "whats app": "whatsapp", "what's app": "whatsapp", "you tube": "youtube", "spotifai": "spotify",
    "notepad plus plus": "notepad++", "power point": "powerpoint", "ms word": "word",
}
FILLER = re.compile(r"\b(the|app|application|desktop|please|program|software|open|launch|start)\b", re.I)


def _norm(s: str) -> str:
    s = FILLER.sub(" ", (s or "").lower().replace("&", " and "))
    return re.sub(r"[^a-z0-9+ ]+", " ", s).split() and " ".join(re.sub(r"[^a-z0-9+ ]+", " ", s).split())


def resolve(query: str, installed: list[str], launch_at: float = 0.88, confirm_at: float = 0.62) -> tuple[str, str | None, float]:
    """Returns (status, installed_name, score); status in launch | confirm | none."""
    q = _norm(query) or ""
    if not q or not installed:
        return "none", None, 0.0
    fixed = SOUNDALIKE.get(q, q)
    names = {n: _norm(n) or "" for n in installed}
    best: tuple[float, str] = (0.0, "")
    for orig, n in names.items():
        if not n:
            continue
        for cand, bonus in ((q, 0.0), (fixed, 0.0)):
            if n == cand:
                sc = 1.0
            elif n.startswith(cand + " ") or n.split()[0] == cand.split()[0] == cand:
                sc = 0.93                             # "claude" matches "Claude Desktop"
            else:
                sc = difflib.SequenceMatcher(None, cand, n).ratio()
                if set(cand.split()) <= set(n.split()):
                    sc = max(sc, 0.9)                 # "chrome" -> "Google Chrome"
                if cand in n and len(cand) >= 4:
                    sc = max(sc, 0.8)
            if sc > best[0]:
                best = (sc, orig)
    sc, name = best
    heard_via_soundalike = fixed != q
    if sc >= launch_at and not (heard_via_soundalike and sc < 0.95):
        return "launch", name, sc
    if sc >= confirm_at or (heard_via_soundalike and sc >= 0.8):
        return "confirm", name, sc
    return "none", None, sc
