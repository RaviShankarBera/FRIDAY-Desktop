"""Full pages behind the sidebar: Agents, Calendar, Knowledge Base, Workflows.

Every control here does something real. Nothing is a placeholder.
"""
from __future__ import annotations

import json
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QDate, QTime, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (QCalendarWidget, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QPushButton,
                             QScrollArea, QTextEdit, QTimeEdit, QVBoxLayout, QWidget)

from home_view import AMBER, CY, F, GREEN, RED, TXT, TXT_D, Card, clear_layout, lbl

BASE = Path(__file__).resolve().parent
BTN = ("QPushButton{color:%s;padding:6px 14px;background:rgba(10,36,66,170);"
       "border:1px solid rgba(40,150,200,150);border-radius:5px;}"
       "QPushButton:hover{border-color:#27d3ff;color:#fff;}"
       "QPushButton:disabled{color:#4d6b7d;border-color:rgba(40,100,140,90);}" % TXT)
EDIT = ("background:rgba(9,30,56,190);color:%s;border:1px solid rgba(40,150,200,150);"
        "border-radius:5px;padding:4px 8px;" % TXT)

# Which agent card lights up for which tool (matches the real action names).
AGENT_TOOLS = {
    "Coding Agent": {"code_helper", "dev_agent"},
    "Research Agent": {"web_search", "youtube_video", "flight_finder", "weather_report", "agent_task"},
    "Memory Agent": {"knowledge_add", "knowledge_search", "recall_memory", "save_memory"},
    "Browser Agent": {"browser_control", "web_search"},
    "Task Agent": {"agent_task", "reminder"},
    "System Agent": {"computer_settings", "computer_control", "system_monitor", "open_app", "desktop",
                     "file_controller", "file_processor", "screen_process"},
}


def agent_state(tasks: list[dict]) -> dict[str, dict]:
    """Per agent: running count, and the most recent task (name, status, note)."""
    out = {}
    for ag, tools in AGENT_TOOLS.items():
        mine = [t for t in tasks if t["name"] in tools]
        out[ag] = {"running": sum(1 for t in mine if t["status"] == "RUNNING"),
                   "last": mine[-1] if mine else None, "total": len(mine)}
    return out


def _btn(text, fn, tip=""):
    b = QPushButton(text); b.setFont(F(9)); b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(BTN); b.clicked.connect(fn)
    if tip:
        b.setToolTip(tip)
    return b


def _line(placeholder=""):
    e = QLineEdit(); e.setPlaceholderText(placeholder); e.setFont(F(9)); e.setStyleSheet(EDIT)
    return e


def _scroll(inner: QWidget) -> QScrollArea:
    s = QScrollArea(); s.setWidgetResizable(True); s.setFrameShape(QFrame.Shape.NoFrame)
    s.setStyleSheet("QScrollArea{background:transparent;border:none;}"); s.viewport().setStyleSheet("background:transparent;")
    s.setWidget(inner); return s


def _page(title: str, sub: str):
    w = QWidget(); w.setStyleSheet("background:transparent;")
    v = QVBoxLayout(w); v.setContentsMargins(14, 12, 14, 12); v.setSpacing(10)
    v.addWidget(lbl(title, 15, "#e9f6ff", True, 2)); v.addWidget(lbl(sub, 8.5, TXT_D))
    return w, v


class _Base(QWidget):
    _done = pyqtSignal(str)

    def __init__(self, win):
        super().__init__(); self.win = win
        self._done.connect(self._on_done)

    def _bg(self, fn):
        def run():
            try:
                self._done.emit(str(fn()))
            except Exception as e:                      # noqa: BLE001
                self._done.emit(f"Sorry, that failed: {e}")
        threading.Thread(target=run, daemon=True).start()

    def _on_done(self, msg: str): ...


# ───────────────────────────── Agents ─────────────────────────────
class AgentsPage(QWidget):
    def __init__(self, win):
        super().__init__(); self.win = win
        page, v = _page("AGENTS", "Live status of FRIDAY's specialist agents, taken from the real task board.")
        self.box = QVBoxLayout(); self.box.setSpacing(8); v.addLayout(self.box); v.addStretch()
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(_scroll(page))
        self.refresh()
        t = QTimer(self); t.timeout.connect(self.refresh); t.start(1500)

    def refresh(self):
        from core.tasks import TASKS
        st = agent_state(TASKS.snapshot())
        clear_layout(self.box)
        for ag, d in st.items():
            c = Card(); h = QHBoxLayout(); c.lay.addLayout(h)
            col = GREEN if d["running"] else AMBER
            h.addWidget(lbl(ag, 10, TXT, True))
            h.addWidget(lbl(f"● {'Running ' + str(d['running']) if d['running'] else 'Standby'}", 8.5, col), 0)
            h.addStretch()
            h.addWidget(lbl(f"{d['total']} tasks this session", 8, TXT_D))
            last = d["last"]
            line = (f"Last: {last['name']} - {last['status'].title()}" + (f" ({last.get('note')})" if last.get("note") else "")
                    if last else "No tasks yet. Ask for something like: " + sorted(AGENT_TOOLS[ag])[0].replace("_", " "))
            c.lay.addWidget(lbl(line[:140], 8.5, RED if last and last["status"] == "FAILED" else TXT_D))
            c.lay.addWidget(lbl("Tools: " + ", ".join(sorted(AGENT_TOOLS[ag])), 7.5, TXT_D))
            self.box.addWidget(c)


# ───────────────────────────── Calendar ─────────────────────────────
class CalendarPage(_Base):
    FILE = BASE / "config" / "reminders.local.json"

    def __init__(self, win):
        super().__init__(win)
        page, v = _page("CALENDAR", "Pick a day, set a real reminder (desktop notification), or open Google Calendar.")
        row = QHBoxLayout(); v.addLayout(row)
        self.cal = QCalendarWidget(); self.cal.setGridVisible(True)
        from PyQt6.QtWidgets import QCalendarWidget as _QC
        self.cal.setVerticalHeaderFormat(_QC.VerticalHeaderFormat.NoVerticalHeader)
        self.cal.setStyleSheet("QCalendarWidget QWidget{background:#0a2440;color:%s;}"
                               "QCalendarWidget QToolButton{color:%s;background:#0d3358;border:none;padding:4px 8px;}"
                               "QCalendarWidget QMenu{background:#0a2440;color:%s;}"
                               "QCalendarWidget QAbstractItemView{background:#08213b;color:%s;"
                               "selection-background-color:#1b8fb5;selection-color:#fff;"
                               "alternate-background-color:#08213b;gridline-color:#14507a;}"
                               "QCalendarWidget QAbstractItemView:disabled{color:#4d6b7d;}" % (TXT, TXT, TXT, TXT))
        row.addWidget(self.cal, 3)
        c = Card("SET A REMINDER"); row.addWidget(c, 2)
        self.msg = _line("Reminder text"); c.lay.addWidget(self.msg)
        self.time = QTimeEdit(QTime.currentTime().addSecs(3600)); self.time.setDisplayFormat("HH:mm"); self.time.setStyleSheet(EDIT)
        c.lay.addWidget(self.time)
        c.lay.addWidget(_btn("Set reminder", self._set, "Uses the system scheduler (Task Scheduler / launchd / systemd)"))
        self.status = lbl("", 8, TXT_D); self.status.setWordWrap(True); c.lay.addWidget(self.status)
        c.lay.addWidget(_btn("Open Google Calendar", lambda: webbrowser.open("https://calendar.google.com")))
        c.lay.addStretch()
        self.lst = Card("YOUR REMINDERS"); v.addWidget(self.lst); v.addStretch()
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(_scroll(page))
        self.show_list()

    def _load(self) -> list[dict]:
        try:
            return json.loads(self.FILE.read_text("utf-8"))
        except Exception:
            return []

    def show_list(self):
        while self.lst.lay.count() > 1:
            it = self.lst.lay.takeAt(1)
            if it.widget():
                it.widget().deleteLater()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        items = sorted(self._load(), key=lambda r: (r["date"], r["time"]))
        if not items:
            self.lst.lay.addWidget(lbl("No reminders set from here yet.", 8.5, TXT_D))
        for r in items:
            past = f"{r['date']} {r['time']}" < now
            self.lst.lay.addWidget(lbl(f"{r['date']}  {r['time']}   {r['message']}" + ("   (past)" if past else ""),
                                       8.5, TXT_D if past else TXT))

    def _set(self):
        text = self.msg.text().strip()
        if not text:
            self.status.setText("Type what to remind you about first."); return
        d = self.cal.selectedDate().toString("yyyy-MM-dd"); t = self.time.time().toString("HH:mm")
        if datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M") <= datetime.now():
            self.status.setText("Sorry, that time has already passed. Pick a later time or day."); return
        self.status.setText("Setting reminder...")
        def go():
            from actions.reminder import reminder
            res = str(reminder({"date": d, "time": t, "message": text}))
            if "sorry" in res.lower() or "fail" in res.lower() or "error" in res.lower():
                return "Sorry, " + res
            items = self._load() + [{"date": d, "time": t, "message": text}]
            self.FILE.write_text(json.dumps(items, indent=1), "utf-8")
            return "OK " + res
        self._bg(go)

    def _on_done(self, msg: str):
        ok = msg.startswith("OK ")
        self.status.setText(msg[3:] if ok else msg)
        self.status.setStyleSheet(f"color:{GREEN if ok else RED};background:transparent;")
        if ok:
            self.msg.clear(); self.show_list()


# ───────────────────────────── Knowledge Base ─────────────────────────────
class KnowledgePage(_Base):
    def __init__(self, win):
        super().__init__(win)
        page, v = _page("KNOWLEDGE BASE", "Private documents FRIDAY can search. Everything stays on this computer.")
        a = Card("ADD KNOWLEDGE"); v.addWidget(a)
        r = QHBoxLayout(); a.lay.addLayout(r)
        r.addWidget(_btn("Add files...", self._pick_files, "txt, md, csv, json, code, pdf")); r.addStretch()
        self.name = _line("Name for the note"); a.lay.addWidget(self.name)
        self.text = QTextEdit(); self.text.setPlaceholderText("Or paste text FRIDAY should remember..."); self.text.setFixedHeight(80)
        self.text.setStyleSheet(EDIT); a.lay.addWidget(self.text)
        a.lay.addWidget(_btn("Add pasted text", self._add_text))
        self.status = lbl("", 8, TXT_D); self.status.setWordWrap(True); a.lay.addWidget(self.status)
        s = Card("SEARCH"); v.addWidget(s)
        self.q = _line("Ask your documents..."); self.q.returnPressed.connect(self._search); s.lay.addWidget(self.q)
        self.res = QVBoxLayout(); s.lay.addLayout(self.res)
        self.src = Card("INDEXED SOURCES"); v.addWidget(self.src); v.addStretch()
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(_scroll(page))
        self.show_sources()

    def _kb(self):
        from core.rag import KnowledgeBase
        return KnowledgeBase()

    def show_sources(self):
        while self.src.lay.count() > 1:
            it = self.src.lay.takeAt(1)
            w = it.widget()
            if w: w.deleteLater()
            elif it.layout(): clear_layout(it.layout())
        try:
            names = self._kb().sources()
        except Exception as e:
            names = []; self.status.setText(f"Sorry, the knowledge base could not load: {e}")
        if not names:
            self.src.lay.addWidget(lbl("Nothing indexed yet.", 8.5, TXT_D))
        for n in names:
            h = QHBoxLayout(); h.addWidget(lbl(n[:70], 8.5, TXT), 1)
            h.addWidget(_btn("Remove", lambda _=False, n=n: self._remove(n)))
            self.src.lay.addLayout(h)

    def _remove(self, n):
        self._bg(lambda: (self._kb().remove(n), "REMOVED")[1])

    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add to FRIDAY's knowledge", str(Path.home()),
                                                "Documents (*.txt *.md *.csv *.json *.py *.pdf);;All files (*)")
        if files:
            self.status.setText(f"Indexing {len(files)} file(s)...")
            def go():
                kb = self._kb(); n = 0; bad = []
                for f in files:
                    try:
                        n += kb.add_file(f)
                    except Exception as e:                  # noqa: BLE001
                        bad.append(f"{Path(f).name}: {e}")
                return f"ADDED {n} passages." + (" Sorry, skipped: " + "; ".join(bad) if bad else "")
            self._bg(go)

    def _add_text(self):
        t, n = self.text.toPlainText().strip(), self.name.text().strip() or "note"
        if not t:
            self.status.setText("Paste some text first."); return
        self._bg(lambda: f"ADDED {self._kb().add_text(n, t)} passages.")

    def _search(self):
        q = self.q.text().strip()
        if q:
            self._bg(lambda: "SEARCH" + json.dumps(self._kb().search(q, k=5), default=float))

    def _on_done(self, msg: str):
        if msg.startswith("SEARCH"):
            hits = json.loads(msg[6:]); clear_layout(self.res)
            if not hits:
                self.res.addWidget(lbl("Nothing matched. Add documents first or rephrase.", 8.5, TXT_D))
            for h in hits:
                w = lbl(f"{h['source']}: {h['text'][:260]}", 8.5, TXT); w.setWordWrap(True); self.res.addWidget(w)
            return
        self.status.setText(msg.replace("ADDED", "Added").replace("REMOVED", "Removed"))
        self.status.setStyleSheet(f"color:{RED if 'Sorry' in msg else GREEN};background:transparent;")
        self.show_sources()


# ───────────────────────────── Workflows ─────────────────────────────
from core.seed import BRIEFING_PROMPT
BUILTIN = [
    ("Morning briefing", BRIEFING_PROMPT),
    ("System health check", "Friday, check my system: CPU, memory, disk and network, and tell me if anything needs attention"),
    ("Research a topic", "Friday, research this topic and summarise it in five points: {input}"),
    ("Search my knowledge", "Friday, search my knowledge base for: {input}"),
]


class WorkflowsPage(_Base):
    FILE = BASE / "config" / "workflows.local.json"

    def __init__(self, win):
        super().__init__(win)
        page, v = _page("WORKFLOWS", "One click runs a saved multi-step request. {input} is replaced by what you type below.")
        self.inp = _line("Input for workflows that need one (a topic, a question)"); v.addWidget(self.inp)
        self.status = lbl("", 8.5, TXT_D); v.addWidget(self.status)
        self.box = Card("YOUR WORKFLOWS"); v.addWidget(self.box)
        n = Card("SAVE A NEW WORKFLOW"); v.addWidget(n); v.addStretch()
        self.nn = _line("Name"); self.np = _line('What FRIDAY should do, e.g. "Friday, summarise my emails and set a reminder"')
        n.lay.addWidget(self.nn); n.lay.addWidget(self.np); n.lay.addWidget(_btn("Save workflow", self._save))
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(_scroll(page))
        self.render()

    def _custom(self) -> list[list[str]]:
        try:
            return json.loads(self.FILE.read_text("utf-8"))
        except Exception:
            return []

    def render(self):
        while self.box.lay.count() > 1:
            it = self.box.lay.takeAt(1)
            if it.widget(): it.widget().deleteLater()
            elif it.layout(): clear_layout(it.layout())
        for i, (nm, pr) in enumerate(BUILTIN + self._custom()):
            h = QHBoxLayout(); h.addWidget(lbl(nm, 9, TXT, True), 1)
            h.addWidget(_btn("Run", lambda _=False, p=pr: self._run(p)))
            if i >= len(BUILTIN):
                h.addWidget(_btn("Delete", lambda _=False, k=i - len(BUILTIN): self._del(k)))
            self.box.lay.addLayout(h)

    def _run(self, prompt: str):
        if "{input}" in prompt:
            if not self.inp.text().strip():
                self.status.setText("Sorry, this workflow needs an input. Type it in the box above."); return
            prompt = prompt.replace("{input}", self.inp.text().strip())
        self.status.setText("Started. Watch the Tasks page for progress.")
        self.win._send_text(prompt)

    def _save(self):
        nm, pr = self.nn.text().strip(), self.np.text().strip()
        if not nm or not pr:
            self.status.setText("Give the workflow a name and instructions."); return
        items = self._custom() + [[nm, pr if pr.lower().startswith("friday") else "Friday, " + pr]]
        self.FILE.write_text(json.dumps(items, indent=1), "utf-8")
        self.nn.clear(); self.np.clear(); self.render(); self.status.setText(f"Saved '{nm}'.")

    def _del(self, k: int):
        items = self._custom()
        if 0 <= k < len(items):
            items.pop(k); self.FILE.write_text(json.dumps(items, indent=1), "utf-8"); self.render()
