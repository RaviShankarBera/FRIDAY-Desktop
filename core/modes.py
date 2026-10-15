"""Work modes: one phrase sets up a whole working context.

"Friday, work mode" -> open the apps and pages, set focus/Do-Not-Disturb, optionally close
distractions. Modes live in config/modes.json (gitignored: it can name your own repo paths).
Built-in defaults carry no personal data. All OS effects go through small functions that tests
replace, so the logic is testable without a desktop.
"""
from __future__ import annotations

import json
import platform
import subprocess
import webbrowser
from pathlib import Path
from typing import Callable

BASE = Path(__file__).resolve().parent.parent
MODES_PATH = BASE / "config" / "modes.json"

DEFAULT_MODES: dict[str, dict] = {
    "work": {
        "description": "Coding focus",
        "apps": ["code"],
        "urls": ["https://github.com", "https://chat.google.com"],
        "folders": [],
        "close": ["spotify", "discord"],
        "dnd": True,
    },
    "meeting": {
        "description": "Calls and notes",
        "apps": ["teams"],
        "urls": ["https://calendar.google.com"],
        "folders": [],
        "close": ["spotify"],
        "dnd": True,
        "mute_volume": True,
    },
    "gaming": {
        "description": "Play time",
        "apps": ["steam"],
        "urls": [],
        "folders": [],
        "close": ["code"],
        "dnd": True,
    },
    "chill": {
        "description": "Relax",
        "apps": ["spotify"],
        "urls": ["https://www.youtube.com"],
        "folders": [],
        "close": [],
        "dnd": False,
    },
}

ALIASES = {"coding": "work", "focus": "work", "office": "work", "meet": "meeting", "call": "meeting",
           "game": "gaming", "games": "gaming", "relax": "chill", "break": "chill", "normal": "chill"}


def load_modes(path: Path | None = None) -> dict[str, dict]:
    modes = {k: dict(v) for k, v in DEFAULT_MODES.items()}
    try:
        user = json.loads((path or MODES_PATH).read_text(encoding="utf-8"))
        for k, v in user.items():
            if isinstance(v, dict):
                modes[str(k).lower()] = {**modes.get(str(k).lower(), {}), **v}
    except Exception:
        pass
    return modes


def resolve(name: str, modes: dict[str, dict]) -> str | None:
    n = (name or "").strip().lower().replace(" mode", "").strip()
    n = ALIASES.get(n, n)
    return n if n in modes else None


# ---- OS effects (replaceable in tests) ----
def open_app(name: str) -> str:
    from actions.open_app import open_app as _o
    return _o({"app_name": name})


def open_url(url: str) -> None:
    webbrowser.open(url)


def open_folder(path: str) -> None:
    p = str(Path(path).expanduser())
    s = platform.system()
    if s == "Windows":
        import os; os.startfile(p)               # noqa: S606
    elif s == "Darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


def close_app(name: str) -> bool:
    try:
        import psutil
    except ImportError:
        return False
    n = name.lower().replace(".exe", "")
    hit = False
    for pr in psutil.process_iter(["name"]):
        pn = (pr.info.get("name") or "").lower().replace(".exe", "")
        if pn and (pn == n or pn.startswith(n)):
            try:
                pr.terminate(); hit = True
            except Exception:
                pass
    return hit


def set_dnd(on: bool) -> bool:
    """Windows: Focus Assist via registry-backed toast toggle. Returns True if applied."""
    s = platform.system()
    try:
        if s == "Windows":
            val = "1" if on else "0"
            cmd = ("New-Item -Path HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\PushNotifications -Force | Out-Null;"
                   f"Set-ItemProperty -Path HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\PushNotifications "
                   f"-Name ToastEnabled -Value {0 if on else 1} -Type DWord")
            r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, timeout=15)
            return r.returncode == 0
        if s == "Darwin":
            subprocess.run(["shortcuts", "run", "Focus On" if on else "Focus Off"], capture_output=True, timeout=15)
            return True
        subprocess.run(["gsettings", "set", "org.gnome.desktop.notifications", "show-banners",
                        "false" if on else "true"], capture_output=True, timeout=15)
        return True
    except Exception:
        return False


def mute(on: bool) -> None:
    from actions.computer_settings import computer_settings
    computer_settings({"action": "volume_mute" if on else "volume_up"})


def apply_mode(name: str, modes: dict[str, dict] | None = None,
               fx: dict[str, Callable] | None = None) -> str:
    modes = modes or load_modes()
    key = resolve(name, modes)
    if key is None:
        return f"Sorry, I don't have a mode called '{name}'. I have: {', '.join(sorted(modes))}."
    m = modes[key]
    f = {"open_app": open_app, "open_url": open_url, "open_folder": open_folder,
         "close_app": close_app, "set_dnd": set_dnd, "mute": mute, **(fx or {})}
    done, failed = [], []

    def step(label, fn, *a):
        try:
            r = fn(*a)
            if r is False:
                failed.append(label)
            else:
                done.append(label)
        except Exception:
            failed.append(label)

    for a in m.get("close", []):
        step(f"closed {a}", f["close_app"], a)
    for a in m.get("apps", []):
        step(f"opened {a}", f["open_app"], a)
    for u in m.get("urls", []):
        step(f"opened {u}", f["open_url"], u)
    for d in m.get("folders", []):
        step(f"opened {d}", f["open_folder"], d)
    if "dnd" in m:
        step("do-not-disturb " + ("on" if m["dnd"] else "off"), f["set_dnd"], bool(m["dnd"]))
    if m.get("mute_volume"):
        step("muted", f["mute"], True)
    out = f"{key.capitalize()} mode on."
    if failed:
        out += " Could not do: " + ", ".join(failed) + "."
    return out


def save_mode(name: str, spec: dict, path: Path | None = None) -> str:
    p = path or MODES_PATH
    try:
        cur = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        cur = {}
    clean = {k: spec[k] for k in ("description", "apps", "urls", "folders", "close", "dnd", "mute_volume") if k in spec}
    cur[name.strip().lower()] = clean
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    return f"Saved mode '{name}'."
