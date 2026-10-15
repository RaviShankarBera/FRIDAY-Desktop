"""Rule-based commands that work with NO model at all (Gemini out of quota, Ollama not installed).

voice_fallback calls match() only when every model has failed, so basic control never stops.
Returns {"name": tool, "args": {...}} or None. Deliberately small and strict: a wrong guess is
worse than saying "I can't do that offline".
"""
from __future__ import annotations

import re

_APP = re.compile(r"^(?:please\s+)?(?:open|launch|start)\s+(.+)$", re.I)
_CLOSE = re.compile(r"^(?:please\s+)?(?:close|quit|kill)\s+(.+)$", re.I)
_TIMER = re.compile(r"^(?:set\s+(?:a\s+)?)?timer(?:\s+(?:for|of))?\s+(.+)$", re.I)
_MODE = re.compile(r"^(?:start\s+|switch to\s+|turn on\s+)?(work|meeting|gaming|chill|coding|focus|relax)\s+mode$", re.I)
_VOL = re.compile(r"^(?:set\s+)?volume(?:\s+to)?\s+(\d{1,3})(?:\s*%| percent)?$", re.I)
_BRI = re.compile(r"^(?:set\s+)?brightness(?:\s+to)?\s+(\d{1,3})(?:\s*%| percent)?$", re.I)
_FIND = re.compile(r"^(?:find|search for)\s+(?:the\s+)?(?:file\s+)?(.+?)(?:\s+file)?$", re.I)


def match(cmd: str) -> dict | None:
    t = re.sub(r"[.!?]+$", "", (cmd or "").strip())
    if not t:
        return None
    low = t.lower()
    if m := _MODE.match(t):
        return {"name": "work_mode", "args": {"mode": m.group(1).lower()}}
    if m := _TIMER.match(t):
        return {"name": "pc_control", "args": {"action": "timer", "value": m.group(1)}}
    if m := _VOL.match(t):
        return {"name": "pc_control", "args": {"action": "volume", "value": m.group(1)}}
    if m := _BRI.match(t):
        return {"name": "pc_control", "args": {"action": "brightness", "value": m.group(1)}}
    if low in ("volume up", "louder", "turn it up"):
        return {"name": "pc_control", "args": {"action": "volume", "value": "up"}}
    if low in ("volume down", "quieter", "turn it down"):
        return {"name": "pc_control", "args": {"action": "volume", "value": "down"}}
    if low in ("mute", "unmute", "mute volume"):
        return {"name": "computer_settings", "args": {"action": "toggle_mute"}}
    if low in ("take a screenshot", "screenshot", "take screenshot"):
        return {"name": "pc_control", "args": {"action": "screenshot"}}
    if low in ("lock the screen", "lock screen", "lock the pc", "lock"):
        return {"name": "pc_control", "args": {"action": "lock"}}
    if low in ("shutdown", "shut down", "shut down the pc", "restart", "restart the pc"):
        return {"name": "pc_control", "args": {"action": "restart" if "restart" in low else "shutdown"}}
    if m := _CLOSE.match(t):
        return {"name": "pc_control", "args": {"action": "close_app", "value": m.group(1)}}
    if m := _APP.match(t):
        return {"name": "open_app", "args": {"app_name": m.group(1)}}
    if m := _FIND.match(t):
        return {"name": "pc_control", "args": {"action": "find_file", "value": m.group(1)}}
    return None
