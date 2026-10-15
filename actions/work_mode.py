"""work_mode: "Friday, work mode / meeting mode / gaming mode" and custom modes."""
from __future__ import annotations


def _lst(v) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [s.strip() for s in str(v or "").split(",") if s.strip()]


def work_mode(parameters: dict, player=None) -> str:
    from core import modes
    p = parameters or {}
    act = str(p.get("action") or "start").lower()
    if act == "list":
        ms = modes.load_modes()
        return "Modes: " + "; ".join(f"{k} ({v.get('description', '')})" for k, v in ms.items())
    name = str(p.get("mode") or "").strip()
    if not name:
        return "Which mode - work, meeting, gaming or chill?"
    if act == "save":
        spec = {"description": str(p.get("description") or "Custom mode"),
                "apps": _lst(p.get("apps")), "urls": _lst(p.get("urls")),
                "folders": _lst(p.get("folders")), "close": _lst(p.get("close")),
                "dnd": str(p.get("dnd", "true")).lower() in ("true", "yes", "1")}
        return modes.save_mode(name, spec)
    return modes.apply_mode(name)


TOOL = {
    "name": "work_mode",
    "description": ("Switches the whole PC setup in one go: 'work mode' (VS Code, repo folder, browser tabs, "
                    "Do-Not-Disturb), 'meeting mode', 'gaming mode', 'chill mode', or a custom mode. "
                    "action=start (default), list, or save (to create a custom mode from apps/urls/folders/close lists)."),
    "parameters": {"type": "OBJECT", "properties": {
        "mode": {"type": "STRING", "description": "work, meeting, gaming, chill, or a custom name."},
        "action": {"type": "STRING", "description": "start | list | save"},
        "apps": {"type": "STRING", "description": "save only: comma-separated apps to open."},
        "urls": {"type": "STRING", "description": "save only: comma-separated URLs."},
        "folders": {"type": "STRING", "description": "save only: comma-separated folders (e.g. the repo path)."},
        "close": {"type": "STRING", "description": "save only: apps to close."},
        "dnd": {"type": "STRING", "description": "save only: 'true' to enable Do-Not-Disturb."},
        "description": {"type": "STRING", "description": "save only: short label."}}},
    "handler": work_mode,
}
