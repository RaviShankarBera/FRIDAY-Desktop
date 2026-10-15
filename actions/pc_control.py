"""pc_control: the PC-control extras on top of computer_settings/open_app.

Voice-driven: timers, file search, saving screenshots, listing/closing running apps.
Volume, brightness, shutdown and opening apps already live in computer_settings/open_app;
this tool delegates to them for 'volume', 'brightness', 'shutdown', 'restart', 'sleep', 'open'
so the model has one obvious place to go, and the irreversible ones still go through the
on-screen confirmation (core/confirm.py).
"""
from __future__ import annotations

import fnmatch
import os
import platform
import time
from pathlib import Path

from core import timers

_SKIP_DIRS = {"node_modules", ".git", "__pycache__", "AppData", "$Recycle.Bin", "Windows", "Program Files",
              "Program Files (x86)", ".cache", ".venv", "venv", "site-packages"}


def find_files(query: str, roots: list[Path] | None = None, limit: int = 8, max_seconds: float = 8.0) -> list[Path]:
    """Case-insensitive name search (substring, or glob when it has * or ?). Newest first."""
    q = query.strip().lower()
    if not q:
        return []
    glob = any(c in q for c in "*?")
    roots = roots or [Path.home() / d for d in ("Desktop", "Documents", "Downloads", "Pictures")]
    hits: list[Path] = []
    deadline = time.monotonic() + max_seconds
    for root in roots:
        if not root.exists():
            continue
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in _SKIP_DIRS and not d.startswith(".")]
            for f in fn:
                n = f.lower()
                if (fnmatch.fnmatch(n, q) if glob else q in n):
                    hits.append(Path(dp) / f)
            if time.monotonic() > deadline:
                break
        if time.monotonic() > deadline:
            break
    hits.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return hits[:limit]


def save_screenshot() -> str:
    from actions.screen_processor import _capture_screen
    data, mime = _capture_screen()
    d = Path.home() / "Pictures" / "FRIDAY"
    d.mkdir(parents=True, exist_ok=True)
    p = d / time.strftime("screenshot-%Y%m%d-%H%M%S.jpg")
    p.write_bytes(data)
    return str(p)


def list_apps(limit: int = 12) -> list[str]:
    import psutil
    agg: dict[str, float] = {}
    for pr in psutil.process_iter(["name", "memory_info"]):
        try:
            n = (pr.info["name"] or "").replace(".exe", "")
            agg[n] = agg.get(n, 0) + pr.info["memory_info"].rss
        except Exception:
            continue
    return [n for n, _ in sorted(agg.items(), key=lambda kv: -kv[1])[:limit]]


def _delegate(action: str, value=None) -> str:
    from actions.computer_settings import computer_settings
    return computer_settings({"action": action, "value": value})


def pc_control(parameters: dict, player=None, speak=None) -> str:
    p = parameters or {}
    act = str(p.get("action") or "").strip().lower()
    val = str(p.get("value") or "").strip()
    try:
        if act in ("timer", "set_timer"):
            secs = timers.parse_duration(val)
            if not secs:
                return "Sorry, I did not catch the timer length. Say for example '25 minutes'."
            label = str(p.get("label") or "Timer")
            timers.notify = (lambda m: (player.write_log(f"FRIDAY: {m}") if player else None,
                                        speak(f"Tell the user out loud in one short sentence: {m}") if speak else None)[0])
            timers.start(secs, label)
            return f"{label} set for {secs // 60} min {secs % 60} sec." if secs % 60 else f"{label} set for {secs // 60} minutes."
        if act == "list_timers":
            a = timers.active()
            return "; ".join(f"{l}: {s // 60}m {s % 60}s left" for _, l, s in a) or "No timers running."
        if act == "cancel_timer":
            n = timers.cancel(val)
            return f"Cancelled {n} timer(s)." if n else "No matching timer."
        if act in ("find_file", "file_search", "search_files"):
            r = find_files(val)
            if not r:
                return f"Sorry, I found no file matching '{val}' in Desktop, Documents, Downloads or Pictures."
            return "Found: " + "; ".join(str(x) for x in r)
        if act == "open_file":
            r = find_files(val, limit=1)
            if not r:
                return f"Sorry, no file matching '{val}'."
            if platform.system() == "Windows":
                os.startfile(str(r[0]))              # noqa: S606
            else:
                import subprocess
                subprocess.Popen(["open" if platform.system() == "Darwin" else "xdg-open", str(r[0])])
            return f"Opened {r[0].name}."
        if act == "screenshot":
            return f"Screenshot saved to {save_screenshot()}."
        if act == "list_apps":
            return "Running (by memory): " + ", ".join(list_apps())
        if act == "close_app":
            from core import confirm
            from core.modes import close_app
            if not val:
                return "Which app should I close?"
            return confirm.request(f"close_app:{val}", f"Close {val}", "Unsaved work in it may be lost.",
                                   lambda: f"Closed {val}." if close_app(val) else f"{val} was not running.")
        if act in ("volume", "brightness"):
            if val.lstrip("-").isdigit():
                n = max(0, min(100, int(val)))
                if act == "brightness":
                    from actions.computer_settings import brightness_set
                    brightness_set(n)
                    return f"Brightness set to {n}."
                return _delegate("volume_set", n)
            return _delegate(f"{act}_down" if val == "down" else f"{act}_up")
        if act in ("shutdown", "restart", "sleep", "lock"):
            return _delegate({"sleep": "sleep_display", "lock": "lock_screen"}.get(act, act))
        if act == "open":
            from actions.open_app import open_app
            return open_app({"app_name": val})
    except Exception as e:                           # noqa: BLE001
        return f"Sorry, {act} failed: {e}"
    return ("Sorry, I can do: timer, list_timers, cancel_timer, find_file, open_file, screenshot, list_apps, "
            "close_app, volume, brightness, shutdown, restart, sleep, lock, open.")


TOOL = {
    "name": "pc_control",
    "description": ("One tool for common PC commands by voice: set/list/cancel a timer ('timer 25 minutes'), "
                    "find or open a file by name, save a screenshot to Pictures/FRIDAY, list running apps, "
                    "close an app (asks for on-screen confirmation), set volume/brightness (value 0-100, or up/down), "
                    "open an app, and shutdown/restart/sleep/lock (shutdown and restart need on-screen confirmation, "
                    "never claim they happened until confirmed)."),
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "description": "timer | list_timers | cancel_timer | find_file | open_file | screenshot | list_apps | close_app | volume | brightness | open | shutdown | restart | sleep | lock"},
        "value": {"type": "STRING", "description": "Duration for timer ('25 minutes'), file name or pattern, app name, or number 0-100 for volume/brightness."},
        "label": {"type": "STRING", "description": "Timer label, e.g. 'tea'."}},
        "required": ["action"]},
    "handler": pc_control,
}
