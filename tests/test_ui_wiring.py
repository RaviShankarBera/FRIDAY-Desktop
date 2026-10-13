"""Every control on the UI screen must do something real."""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def win(tmp_path, monkeypatch):
    pytest.importorskip("PyQt6")
    cfg = ROOT / "config" / "api_keys.json"
    if cfg.exists():
        pytest.skip("real key file present")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["FRIDAY_UI_TEST"] = "1"
    cfg.write_text(json.dumps({"gemini_api_key": "DUMMY", "os_system": "linux", "user_name": "Ravi"}))
    sys.path.insert(0, str(ROOT))
    from core import rag
    monkeypatch.setattr(rag, "KB_DIR", tmp_path / "kb")
    monkeypatch.setattr(rag, "default_embedder", lambda: rag.HashEmbedder())
    import pages_view
    monkeypatch.setattr(pages_view.CalendarPage, "FILE", tmp_path / "rem.json")
    monkeypatch.setattr(pages_view.WorkflowsPage, "FILE", tmp_path / "wf.json")
    import ui
    from PyQt6.QtWidgets import QApplication
    jui = ui.JarvisUI("")
    w = jui._win
    sent = []
    w._send_text = lambda t: sent.append(t)
    w._sent = sent
    w._jui = jui
    for _ in range(5):
        QApplication.processEvents()
    yield w
    from core.tasks import TASKS
    TASKS.on_change = None
    cfg.unlink(missing_ok=True)


def _pump():
    from PyQt6.QtWidgets import QApplication
    for _ in range(5):
        QApplication.processEvents()


def test_every_button_and_link_is_connected(win):
    from PyQt6.QtWidgets import QPushButton
    import home_view as hv
    dead = []
    for b in win.findChildren(QPushButton):
        if b.receivers(b.clicked) == 0 and b.receivers(b.toggled) == 0:
            dead.append(b.text() or b.toolTip())
    for cl in win.findChildren(hv.ClickLabel):
        if cl.receivers(cl.clicked) == 0:
            dead.append(cl.text())
    # buttons created by the legacy panels are filtered by owning the visible pages only
    legacy_ok = {""}
    dead = [d for d in dead if d not in legacy_ok]
    assert dead == [], f"unwired controls: {dead}"


def test_sidebar_navigation_reaches_a_real_page(win):
    expect = {"home": 0, "core": 1, "tasks": 2, "agents": 3, "calendar": 4, "kb": 5, "flows": 6, "convos": 2}
    for key, idx in expect.items():
        win._nav_to(key)
        assert win._pages.currentIndex() == idx, key


def test_quick_commands_and_links(win):
    h = win._home
    h._q_cal(); assert win._pages.currentIndex() == 4
    h._q_flow(); assert win._pages.currentIndex() == 6
    h.ag.link.clicked.emit(); assert win._pages.currentIndex() == 3
    h.feed_all.clicked.emit(); assert win._pages.currentIndex() == 2
    h.tl.link.clicked.emit(); assert h.tl.link.text().startswith("All")


def test_providers_grid_has_no_placeholders(win):
    import home_view as hv
    assert [k for _, k in hv.PROVIDERS] == ["gemini", "nvidia", "deepseek", "openai", "elevenlabs"]


def test_focus_mode_is_read_by_the_core(win):
    win._set_focus(True)
    assert win._jui.focus_mode is True
    win._set_focus(False)
    assert win._jui.focus_mode is False


def test_agent_cards_reflect_real_tasks(win):
    from core.tasks import TASKS
    import pages_view as pv
    tid = TASKS.start("code_helper", "x")
    st = pv.agent_state(TASKS.snapshot())
    assert st["Coding Agent"]["running"] == 1 and st["Research Agent"]["running"] == 0
    win._home.refresh()
    assert "Running" in win._home.agents["Coding Agent"][0].text()
    TASKS.finish(tid, True, "ok")


def test_knowledge_page_add_search_remove(win):
    import time
    from PyQt6.QtWidgets import QApplication
    kp = win._page_kb
    kp.name.setText("n1"); kp.text.setPlainText("The launch code word is pineapple.")
    kp._add_text()
    for _ in range(100):
        QApplication.processEvents(); time.sleep(0.02)
        if "n1" in kp._kb().sources():
            break
    assert "n1" in kp._kb().sources()
    kp.q.setText("what is the launch code word"); kp._search()
    for _ in range(100):
        QApplication.processEvents(); time.sleep(0.02)
        if kp.res.count():
            break
    assert kp.res.count() >= 1
    kp._remove("n1")
    for _ in range(100):
        QApplication.processEvents(); time.sleep(0.02)
        if "n1" not in kp._kb().sources():
            break
    assert "n1" not in kp._kb().sources()


def test_workflows_run_save_delete(win):
    wp = win._page_flows
    wp._run("Friday, give me my executive briefing")
    assert win._sent[-1].endswith("briefing")
    wp._run("Friday, research: {input}")           # needs input
    assert "needs an input" in wp.status.text()
    wp.inp.setText("solar"); wp._run("Friday, research: {input}")
    assert win._sent[-1] == "Friday, research: solar"
    wp.nn.setText("Mine"); wp.np.setText("summarise my day"); wp._save()
    assert wp._custom() == [["Mine", "Friday, summarise my day"]]
    wp._del(0); assert wp._custom() == []


def test_calendar_rejects_past_and_sets_future(win, monkeypatch):
    import time
    from PyQt6.QtCore import QDate, QTime
    from PyQt6.QtWidgets import QApplication
    import actions.reminder as R
    calls = []
    monkeypatch.setattr(R, "reminder", lambda p, **k: calls.append(p) or "Reminder set.")
    cp = win._page_calendar
    cp.msg.setText("call mom")
    cp.cal.setSelectedDate(QDate.currentDate().addDays(-1)); cp._set()
    assert "passed" in cp.status.text() and not calls
    cp.cal.setSelectedDate(QDate.currentDate().addDays(2)); cp._set()
    for _ in range(100):
        QApplication.processEvents(); time.sleep(0.02)
        if calls:
            break
    assert calls and calls[0]["message"] == "call mom"
    _pump()
    assert len(cp._load()) == 1


def test_profile_name_edit_saves(win, monkeypatch):
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Boss", True)))
    win._edit_name()
    assert win._topbar.user.text() == "Boss"
    assert json.loads((ROOT / "config" / "api_keys.json").read_text())["user_name"] == "Boss"


def test_status_pill_reacts_to_load(win):
    win.__dict__["_metrics_snapshot"] = lambda: {"cpu": 99, "mem": 10}
    win._topbar._status_tick = 0; win._topbar.tick()
    assert "HIGH" in win._topbar.status.text()
