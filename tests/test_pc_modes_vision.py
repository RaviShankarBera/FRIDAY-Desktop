import json, time
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_new_actions_discovered():
    from core.action_loader import discover_actions
    names = discover_actions(ROOT / "actions", set(), lambda m: None).names()
    assert {"screen_vision", "pc_control", "work_mode"} <= names


# ---- screen vision
def test_screen_vision_returns_model_answer(monkeypatch):
    from actions import screen_vision as sv
    from core import gemini_helper as g
    seen = {}
    def fake(prompt, media, system):
        seen.update(prompt=prompt, media=media, system=system); return "ModuleNotFoundError: install requests."
    g.set_backend(fake)
    monkeypatch.setattr(sv, "_grab_screen", lambda: (b"jpegbytes", "image/jpeg"))
    try:
        out = sv.screen_vision({"question": "what is this error?"})
    finally:
        g.set_backend(None)
    assert "ModuleNotFoundError" in out
    assert seen["media"] == [(b"jpegbytes", "image/jpeg")] and "error" in seen["prompt"]
    assert "never guess" in seen["system"]


def test_screen_vision_capture_failure_is_spoken(monkeypatch):
    from actions import screen_vision as sv
    def boom(): raise RuntimeError("no display")
    monkeypatch.setattr(sv, "_grab_screen", boom)
    assert sv.screen_vision({}).startswith("Sorry, I could not capture")


def test_screen_vision_copy(monkeypatch):
    from actions import screen_vision as sv
    from core import gemini_helper as g
    g.set_backend(lambda p, m, s: "fix it")
    monkeypatch.setattr(sv, "_grab_screen", lambda: (b"x", "image/jpeg"))
    copied = []
    monkeypatch.setattr(sv, "_copy", lambda t: copied.append(t) or True)
    try:
        out = sv.screen_vision({"copy_answer": "true"})
    finally:
        g.set_backend(None)
    assert copied == ["fix it"] and "clipboard" in out


# ---- timers / pc control
def test_parse_duration():
    from core.timers import parse_duration as d
    assert d("25 minutes") == 1500 and d("1h 30m") == 5400 and d("90 seconds") == 90
    assert d("1.5 hours") == 5400 and d("10") == 600 and d("soon") is None and d("0 min") is None


def test_timer_fires_and_cancels():
    from core import timers
    got = []
    timers.notify = got.append
    timers.start(1, "tea")
    cid = timers.start(30, "long")
    assert {l for _, l, _ in timers.active()} == {"tea", "long"}
    assert timers.cancel("long") == 1
    time.sleep(1.5)
    assert got == ["tea is done."] and timers.active() == []


def test_find_files(tmp_path):
    from actions.pc_control import find_files
    (tmp_path / "a").mkdir(); (tmp_path / "node_modules").mkdir()
    (tmp_path / "a" / "Resume_2026.pdf").write_text("x")
    (tmp_path / "node_modules" / "resume.js").write_text("x")
    (tmp_path / "notes.txt").write_text("x")
    r = find_files("resume", [tmp_path])
    assert [p.name for p in r] == ["Resume_2026.pdf"]
    assert [p.name for p in find_files("*.txt", [tmp_path])] == ["notes.txt"]
    assert find_files("", [tmp_path]) == []


def test_pc_control_timer_and_unknown():
    from actions.pc_control import pc_control
    from core import timers
    out = pc_control({"action": "timer", "value": "2 minutes", "label": "tea"})
    assert "tea set for 2 minutes" in out
    assert "tea" in pc_control({"action": "list_timers"})
    assert "Cancelled 1" in pc_control({"action": "cancel_timer", "value": "tea"})
    assert pc_control({"action": "timer", "value": "soonish"}).startswith("Sorry")
    assert "Sorry, I can do" in pc_control({"action": "dance"})


def test_close_app_needs_confirmation(monkeypatch):
    from actions import pc_control as pc
    from core import confirm
    called = []
    monkeypatch.setattr(confirm, "request", lambda key, title, detail, run: called.append(title) or "[CONFIRMATION_PENDING]")
    assert "PENDING" in pc.pc_control({"action": "close_app", "value": "chrome"})
    assert called == ["Close chrome"]


def test_shutdown_goes_through_confirm_gate(monkeypatch):
    from actions import computer_settings as cs
    from core import confirm
    monkeypatch.setattr(cs, "_PYAUTOGUI", True)
    ran = []
    monkeypatch.setitem(cs.ACTION_MAP, "shutdown", lambda: ran.append(1))
    asked = []
    monkeypatch.setattr(confirm, "request", lambda key, title, detail, run: asked.append(key) or "[CONFIRMATION_PENDING]")
    monkeypatch.setattr(confirm, "pending_title", lambda: "")
    from actions.pc_control import pc_control
    assert "PENDING" in pc_control({"action": "shutdown"})
    assert asked == ["shutdown"] and ran == []        # nothing happens until the user presses confirm


# ---- work modes
def _fx(log):
    rec = lambda name: (lambda *a: log.append((name, *a)) or True)
    return {k: rec(k) for k in ("open_app", "open_url", "open_folder", "close_app", "set_dnd", "mute")}


def test_work_mode_applies_steps_in_order(tmp_path):
    from core import modes
    log = []
    out = modes.apply_mode("work mode", fx=_fx(log))
    assert out == "Work mode on."
    kinds = [k for k, *_ in log]
    assert kinds.index("close_app") < kinds.index("open_app") < kinds.index("open_url") < kinds.index("set_dnd")
    assert ("set_dnd", True) in log


def test_mode_aliases_and_unknown():
    from core import modes
    assert modes.resolve("coding", modes.load_modes()) == "work"
    assert "don't have a mode" in modes.apply_mode("party")


def test_mode_reports_failures():
    from core import modes
    fx = _fx([]); fx["open_app"] = lambda n: False
    out = modes.apply_mode("meeting", fx=fx)
    assert out.startswith("Meeting mode on.") and "Could not do: opened teams" in out


def test_custom_mode_roundtrip(tmp_path, monkeypatch):
    from core import modes
    p = tmp_path / "modes.json"
    monkeypatch.setattr(modes, "MODES_PATH", p)
    modes.save_mode("Study", {"apps": ["notepad"], "urls": [], "folders": ["~/notes"], "dnd": True, "evil": 1})
    ms = modes.load_modes()
    assert "evil" not in json.loads(p.read_text())["study"]
    log = []
    assert modes.apply_mode("study", ms, _fx(log)) == "Study mode on."
    assert ("open_folder", "~/notes") in log


def test_work_mode_tool_list_and_save(tmp_path, monkeypatch):
    from core import modes
    from actions.work_mode import work_mode
    monkeypatch.setattr(modes, "MODES_PATH", tmp_path / "m.json")
    assert "work" in work_mode({"action": "list"})
    assert "Saved" in work_mode({"action": "save", "mode": "dev", "apps": "code, terminal", "folders": "C:/x"})
    assert "dev" in work_mode({"action": "list"})


def test_modes_file_is_gitignored():
    assert "config/modes.json" in (ROOT / ".gitignore").read_text()
