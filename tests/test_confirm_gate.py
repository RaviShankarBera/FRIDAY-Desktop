"""The approval must come from the user (UI / their own voice), never from a model-supplied parameter."""
import os
import re
import threading
import time
from pathlib import Path

import pytest

from core import confirm, interactive


@pytest.fixture(autouse=True)
def ui():
    shown, hidden = [], []
    confirm.bind(lambda t, d: shown.append((t, d)), lambda: hidden.append(1))
    confirm._pending = None
    yield shown
    confirm._pending = None
    confirm.bind(None, None)


def _wait(cond, t=3.0):
    end = time.time() + t
    while time.time() < end and not cond():
        time.sleep(0.01)
    return cond()


def test_first_call_then_confirmed_true_does_not_execute():
    ran = []
    r1 = interactive.park("t", "Do the thing", lambda: ran.append(1) or "done")
    assert r1.startswith("[CONFIRMATION_PENDING]") and not ran
    # a second model call that claims confirmation changes nothing: there is no parameter that can approve
    r2 = interactive.park("t", "Do the thing", lambda: ran.append(2) or "done")
    time.sleep(0.2)
    assert not ran and "already a confirmation waiting" in r2


def test_only_the_ui_runs_it():
    ran = []
    interactive.park("t", "Do the thing", lambda: ran.append("x") or "done")
    assert not ran
    confirm.resolve(True)
    assert _wait(lambda: ran == ["x"])


def test_cancel_and_expiry_never_execute(monkeypatch):
    ran = []
    interactive.park("t", "A", lambda: ran.append("a"))
    confirm.resolve(False)
    interactive.park("t", "B", lambda: ran.append("b"))
    monkeypatch.setattr(confirm, "TIMEOUT_SECONDS", -1.0)          # approval arrives after it expired
    confirm.resolve(True)
    time.sleep(0.2)
    assert ran == []


def test_changed_parameters_cannot_ride_an_old_approval():
    ran = []
    interactive.park("t", "Delete a.txt", lambda: ran.append("a"))
    confirm.resolve(False)                                             # user declines the first
    interactive.park("t", "Delete b.txt", lambda: ran.append("b"))     # model retries with different details
    time.sleep(0.2)
    assert ran == []                                                   # nothing ran; b waits for its own approval
    confirm.resolve(True)
    assert _wait(lambda: ran == ["b"])                                 # only what was on screen runs


def test_no_ui_means_refusal():
    confirm.bind(None, None)
    ran = []
    r = interactive.park("t", "x", lambda: ran.append(1))
    assert not ran and "not done" in r.lower() or "have not done it" in r


def test_no_model_writable_approval_left_in_gated_tools():
    root = Path(__file__).resolve().parent.parent
    assert not hasattr(interactive, "gate")
    for f in ("send_message", "file_controller", "system_doctor", "install_repo", "run_project"):
        src = (root / "actions" / f"{f}.py").read_text()
        assert not re.search(r'get\(["\']confirmed["\']', src.replace('k != "confirmed"', "")), f
        assert '"confirmed"' not in src.replace('k != "confirmed"', ""), f


def test_send_message_parks_and_ignores_confirmed_param(monkeypatch):
    from actions import send_message as sm
    sent = []
    monkeypatch.setattr(sm, "_PYAUTOGUI", True)
    monkeypatch.setattr(sm, "_resolve_platform", lambda p: (lambda r, m: sent.append((r, m)) or "Message sent"))
    r = sm.send_message({"receiver": "Ana", "message_text": "hi", "platform": "WhatsApp", "confirmed": "true"})
    assert r.startswith("[CONFIRMATION_PENDING]") and not sent
    confirm.resolve(True)
    assert _wait(lambda: sent == [("Ana", "hi")])


def test_file_delete_needs_ui(tmp_path):
    from actions.file_controller import file_controller
    f = tmp_path / "a.txt"; f.write_text("x")
    r = file_controller({"action": "delete", "path": str(tmp_path), "name": "a.txt", "confirmed": "true", "_approved": True})
    assert r.startswith("[CONFIRMATION_PENDING]") and f.exists()       # even a forged flag in params does nothing
    confirm.resolve(False)
    assert f.exists()


def test_duplicates_and_temp_cleanup_need_ui(tmp_path, monkeypatch):
    from actions import system_doctor as sd
    from core import doctor as dr
    monkeypatch.setattr(sd, "REPORT_DIR", tmp_path / "rep")
    data = os.urandom(3000)
    for n, age in (("a.bin", 4), ("b.bin", 0)):
        p = tmp_path / "x" / n; p.parent.mkdir(exist_ok=True); p.write_bytes(data)
        if age:
            t = time.time() - age * 86400; os.utime(p, (t, t))
    trashed = []
    import send2trash
    monkeypatch.setattr(send2trash, "send2trash", lambda p: (trashed.append(p), os.remove(p)))
    args = {"action": "delete_duplicates", "path": str(tmp_path / "x"), "min_mb": "0.001", "confirmed": "true"}
    assert sd.system_doctor(args).startswith("[CONFIRMATION_PENDING]")
    assert sd.system_doctor(args).startswith("There is already") and not trashed     # repeat call: still nothing
    confirm.resolve(True)
    assert _wait(lambda: len(trashed) == 1)
    root = tmp_path / "T"; root.mkdir(); f = root / "o.tmp"; f.write_bytes(b"x" * 9)
    t = time.time() - 9 * 86400; os.utime(f, (t, t))
    monkeypatch.setattr(dr, "temp_roots", lambda: [root])
    assert sd.system_doctor({"action": "clean_temp", "confirmed": "true"}).startswith("[CONFIRMATION_PENDING]")
    assert f.exists()
    confirm.resolve(True)
    assert _wait(lambda: not f.exists())


def test_install_and_run_need_ui(tmp_path, monkeypatch):
    import subprocess
    from actions import install_repo as ir, run_project as rp
    src = tmp_path / "src"; src.mkdir()
    (src / "requirements.txt").write_text(""); (src / "main.py").write_text("print('hi')")
    for c in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"]):
        subprocess.run(["git", *c], cwd=src, check=True)

    def fake_clone(owner, name, dest):
        subprocess.run(["git", "clone", "-q", str(src), str(dest)], check=True)
        return True, "", subprocess.run(["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr(ir, "_clone", fake_clone)
    monkeypatch.setattr(ir, "_meta", lambda o, n: {"stargazers_count": 999, "license": {"k": 1}})
    ran = []
    real = subprocess.run
    monkeypatch.setattr(ir.subprocess, "run", lambda argv, **kw: (ran.append(argv) or subprocess.CompletedProcess(argv, 0, "", "")) if ("venv" in argv or "pip" in argv) else real(argv, **kw))
    params = {"repo": "o/proj", "location": str(tmp_path / "apps"), "confirmed": "true"}
    assert ir.install_repo(params).startswith("[CONFIRMATION_PENDING]")
    assert not (tmp_path / "apps" / "proj").exists() and not ran
    confirm.resolve(True)
    assert _wait(lambda: (tmp_path / "apps" / "proj" / "main.py").exists() and any("pip" in a for a in ran))
    proj = tmp_path / "apps" / "proj"
    vpy = proj / ".venv" / "bin" / "python"; vpy.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(__import__("sys").executable, vpy)
    monkeypatch.setattr(ir.ri.os, "name", "posix")
    r = rp.run_project({"folder": str(proj), "confirmed": "true", "wait": "1"})
    assert r.startswith("[CONFIRMATION_PENDING]") and not (proj / ".friday_run.log").exists()
    confirm.resolve(True)
    assert _wait(lambda: (proj / ".friday_run.log").exists() and "hi" in (proj / ".friday_run.log").read_text())


def test_spoken_answers():
    a = confirm.answer_from_speech
    assert a("Yes.") is True and a("Friday, go ahead") is True and a("haan") is True
    assert a("no") is False and a("Cancel!") is False
    assert a("yes send it and also delete everything") is None      # a yes inside a sentence is not an answer
    assert a("tell her yes") is None and a("") is None
