"""
FRIDAY command-center home view (PyQt6).

Layout follows Ravi's reference: sidebar, top bar, holographic core (yellow),
overview / feed / agents / timeline / quick commands / system monitor / memory /
LLM status panels and a bottom TALK bar. Panels show live data where FRIDAY has
it (system metrics, tasks, voice state, key status) and clearly-labelled
standby values where a feature is not built yet.
"""
from __future__ import annotations

import json
import math
import random
import threading
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (QColor, QFont, QPainter, QPen, QBrush, QLinearGradient,
                         QRadialGradient, QPainterPath)
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                             QPushButton, QLineEdit, QSizePolicy, QFrame)

FONT_FAMILIES = ["Rajdhani", "Exo 2", "Segoe UI", "Helvetica Neue", "DejaVu Sans"]

# palette (navy / cyan, as in the reference) + yellow core
BG0 = QColor("#040a16")
BG1 = QColor("#07142a")
CARD = QColor(9, 30, 56, 175)
EDGE = QColor(32, 130, 190, 120)
CY = QColor("#27d3ff")
CY_D = QColor("#1b8fb5")
TXT = "#d6ecf7"
TXT_D = "#7fa6bd"
GREEN = "#2be39a"
AMBER = "#ffb02e"
RED = "#ff5a6e"
PURPLE = "#a46bff"
GOLD = QColor("#ffc928")
GOLD_L = QColor("#ffe58a")
GOLD_D = QColor("#b9820f")


def F(size: float, bold=False, spacing: float = 0.0) -> QFont:
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPointSizeF(size)
    f.setBold(bold)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def lbl(text, size=8.5, color=TXT, bold=False, spacing=0.0, align=None) -> QLabel:
    l = QLabel(text)
    l.setFont(F(size, bold, spacing))
    l.setStyleSheet(f"color:{color}; background:transparent;")
    if align:
        l.setAlignment(align)
    return l


def clear_layout(lay) -> None:
    """Remove and free every widget/sub-layout in a layout (recursively)."""
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w is not None:
            w.hide(); w.setParent(None); w.deleteLater()
        elif it.layout() is not None:
            clear_layout(it.layout())


class Backdrop(QWidget):
    """Window background: deep navy gradient with a faint grid."""
    def paintEvent(self, _):
        p = QPainter(self)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, BG0); g.setColorAt(0.5, BG1); g.setColorAt(1, QColor("#050c1c"))
        p.fillRect(self.rect(), g)
        p.setPen(QPen(QColor(30, 110, 170, 14), 1))
        for x in range(0, self.width(), 48):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 48):
            p.drawLine(0, y, self.width(), y)


class Card(QFrame):
    """Glass panel with a title row and glowing corner accents."""
    def __init__(self, title: str = "", link: str = "", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 9, 12, 9)
        self.lay.setSpacing(6)
        if title:
            row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(lbl(title, 8, "#bcd9ea", True, 1.4))
            row.addStretch()
            self.link = None
            if link:
                self.link = ClickLabel(link); self.link.setFont(F(7.5))
                self.link.setStyleSheet(f"color:{CY.name()};background:transparent;")
                self.link.setCursor(Qt.CursorShape.PointingHandCursor)
                row.addWidget(self.link)
            self.lay.addLayout(row)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        g = QLinearGradient(0, 0, 0, r.height())
        g.setColorAt(0, QColor(12, 40, 72, 190)); g.setColorAt(1, QColor(6, 22, 44, 190))
        p.setBrush(g); p.setPen(QPen(EDGE, 1))
        p.drawRoundedRect(r, 7, 7)
        p.setPen(QPen(CY, 2))
        L = 12
        for (x, y, dx, dy) in [(r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                               (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)]:
            p.drawLine(QPointF(x, y + dy * 6), QPointF(x, y + dy * 6 + dy * L))
            p.drawLine(QPointF(x + dx * 6, y), QPointF(x + dx * 6 + dx * L, y))


# ───────────────────────────── globe ─────────────────────────────
class Globe(QWidget):
    """FRIDAY core: fiery orange-gold particle/energy sphere on black - streaky
    particle shell (densest at the rim), dark interior, glowing arcs and a hot
    white-gold core. Animated, reacts to audio level."""
    def __init__(self, name="FRIDAY", version="V1.0", parent=None):
        super().__init__(parent)
        self.name, self.version = name, version
        self.setMinimumSize(260, 200)
        rnd = random.Random(11)
        self.shell = []   # (x,y,z, kind, length, bright, hue)
        for _ in range(4200):
            z = rnd.uniform(-1, 1); a = rnd.uniform(0, 2 * math.pi)
            r = math.sqrt(1 - z * z)
            rad = 1.0 - (rnd.random() ** 3) * 0.28     # most points near the surface
            self.shell.append((r * math.cos(a) * rad, z * rad, r * math.sin(a) * rad,
                               rnd.choice((0, 0, 1, 2)), rnd.uniform(0.01, 0.07), rnd.random(), rnd.random()))
        self.inner = []   # swirling core particles
        for _ in range(260):
            a = rnd.uniform(0, 2 * math.pi); r = (rnd.random() ** 1.6) * 0.34
            self.inner.append((a, r, rnd.uniform(0.4, 1.6), rnd.random()))
        self.rot = 0.0
        self.level = 0.0
        self.t = 0.0
        t = QTimer(self); t.timeout.connect(self._step); t.start(40)

    def set_level(self, v: float):
        self.level = max(self.level, min(1.0, v))

    def _step(self):
        self.rot += 0.006; self.t += 0.04
        self.level *= 0.9
        if self.isVisible():
            self.update()

    @staticmethod
    def _fire(h: float, a: int) -> QColor:
        # h 0..1: deep orange -> gold -> pale yellow
        return QColor(255, int(95 + 140 * h), int(10 + 90 * h * h), a)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cx, cy = W / 2, H * 0.47
        R = min(W * 0.40, H * 0.43) * (1 + 0.025 * self.level)

        # faint big half-disc behind (like the reference's dark amber plate)
        plate = QRadialGradient(cx - R * 0.2, cy - R * 0.2, R * 1.5)
        plate.setColorAt(0.6, QColor(60, 34, 6, 70)); plate.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(plate)
        p.drawEllipse(QPointF(cx, cy), R * 1.5, R * 1.5)

        # thin HUD frame lines in amber
        p.setPen(QPen(QColor(200, 120, 20, 90), 1))
        p.drawLine(QPointF(cx - R * 1.45, cy - R * 0.98), QPointF(cx + R * 0.2, cy - R * 0.98))
        p.drawLine(QPointF(cx - R * 1.45, cy - R * 0.93), QPointF(cx - R * 0.5, cy - R * 0.93))
        p.drawLine(QPointF(cx + R * 1.3, cy - R), QPointF(cx + R * 1.3, cy + R * 0.9))
        p.drawLine(QPointF(cx - R * 1.3, cy + R * 0.95), QPointF(cx + R * 1.2, cy + R * 0.95))

        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        # dark interior glow edge
        rim = QRadialGradient(cx, cy, R * 1.12)
        rim.setColorAt(0.7, QColor(0, 0, 0, 0)); rim.setColorAt(0.93, QColor(190, 90, 10, 55)); rim.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(rim); p.drawEllipse(QPointF(cx, cy), R * 1.12, R * 1.12)

        c, s = math.cos(self.rot), math.sin(self.rot)
        tilt = 0.28; ct, st = math.cos(tilt), math.sin(tilt)

        def proj(x, y, z):
            x2, z2 = x * c + z * s, -x * s + z * c
            y2, z3 = y * ct - z2 * st, y * st + z2 * ct
            return cx + x2 * R, cy - y2 * R, z3

        # streaky particle shell
        for (x, y, z, kind, ln, br, hue) in self.shell:
            X, Y, Z = proj(x, y, z)
            d = math.hypot(X - cx, Y - cy) / R          # 0 centre .. 1 rim
            if Z < -0.25 and d < 0.8:
                continue                                  # back face mostly hidden
            tw = 0.55 + 0.45 * math.sin(self.t * 2 + br * 40)
            a = int((40 + 190 * (d ** 1.6)) * br * tw * (1 + self.level))
            if a < 12:
                continue
            col = self._fire(0.25 + 0.7 * hue * (0.5 + 0.5 * d), min(255, a))
            ang = math.atan2(Y - cy, X - cx)
            if kind == 0:      # tangential streak
                dx, dy = -math.sin(ang), math.cos(ang)
            elif kind == 1:    # radial streak
                dx, dy = math.cos(ang), math.sin(ang)
            else:              # horizontal glitch bar
                dx, dy = 1.0, 0.0
            L = ln * R * (0.6 + br)
            p.setPen(QPen(col, 1.0 + 1.2 * br))
            p.drawLine(QPointF(X - dx * L, Y - dy * L), QPointF(X + dx * L, Y + dy * L))

        # glowing inner arcs (the curved bands in the reference)
        for (k, rr, a0, span, w, al) in ((0, 0.62, 200, 150, 5, 170), (1, 0.50, 20, 120, 3, 120), (2, 0.82, 250, 90, 2, 120)):
            p.save(); p.translate(cx, cy); p.rotate(math.degrees(self.rot * (1.5 - k * 0.6)) + k * 40)
            rect = QRectF(-R * rr, -R * rr * 0.9, R * rr * 2, R * rr * 1.8)
            for ww, aa in ((w * 3, al // 5), (w, al)):
                p.setPen(QPen(QColor(255, 150, 20, aa), ww, cap=Qt.PenCapStyle.RoundCap))
                p.drawArc(rect, a0 * 16, span * 16)
            p.restore()

        # hot core
        pulse = 0.9 + 0.1 * math.sin(self.t * 1.7) + 0.35 * self.level
        for rad, col in ((0.50, QColor(255, 120, 10, 38)), (0.34, QColor(255, 170, 30, 70)),
                         (0.20, QColor(255, 215, 80, 130)), (0.10, QColor(255, 245, 190, 210))):
            g = QRadialGradient(cx, cy, R * rad * pulse)
            g.setColorAt(0, col); g.setColorAt(1, QColor(col.red(), col.green(), col.blue(), 0))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(g)
            p.drawEllipse(QPointF(cx, cy), R * rad * pulse, R * rad * pulse)
        for (a, r, sp, br) in self.inner:                # swirling core filaments
            ang = a + self.t * sp * 0.8
            X = cx + math.cos(ang) * r * R * 1.05; Y = cy + math.sin(ang) * r * R * 0.8
            p.setPen(QPen(self._fire(0.6 + 0.4 * br, int(110 + 120 * br)), 1.4))
            p.drawLine(QPointF(X, Y), QPointF(X - math.sin(ang) * 6, Y + math.cos(ang) * 5))

        # name plate
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        nm = F(max(15, R * 0.24), True, R * 0.07); p.setFont(nm)
        p.setPen(QColor(0, 0, 0, 170))
        p.drawText(QRectF(cx - R + 2, cy - R * 0.22 + 2, R * 2, R * 0.45), Qt.AlignmentFlag.AlignCenter, self.name)
        p.setPen(QColor("#fff6cf"))
        p.drawText(QRectF(cx - R, cy - R * 0.22, R * 2, R * 0.45), Qt.AlignmentFlag.AlignCenter, self.name)
        p.setPen(QColor("#ffd45a")); p.setFont(F(max(7, R * 0.085), False, R * 0.05))
        p.drawText(QRectF(cx - R, cy + R * 0.22, R * 2, R * 0.2), Qt.AlignmentFlag.AlignCenter, "AI CORE")
        p.setPen(QColor("#e0a020")); p.setFont(F(max(6.5, R * 0.07)))
        p.drawText(QRectF(cx - R, cy + R * 0.40, R * 2, R * 0.2), Qt.AlignmentFlag.AlignCenter, f"v{self.version.lstrip('Vv')}")


class Wave(QWidget):
    """Animated bar waveform driven by the live audio level."""
    def __init__(self, color=CY, bars=40, parent=None):
        super().__init__(parent)
        self.color, self.n = QColor(color), bars
        self.level = 0.0
        self.active = True
        self.phase = random.random() * 10
        t = QTimer(self); t.timeout.connect(self._step); t.start(60)

    def set_level(self, v):
        self.level = max(self.level, min(1.0, v))

    def _step(self):
        self.phase += 0.35; self.level *= 0.85
        if self.isVisible():
            self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height(); mid = H / 2
        step = W / self.n
        for i in range(self.n):
            edge = math.sin(math.pi * (i + 0.5) / self.n)
            amp = (0.18 + 0.22 * (math.sin(self.phase + i * 0.55) * 0.5 + 0.5) + self.level * 0.9) * edge
            if not self.active:
                amp = 0.08 * edge
            h = max(1.5, amp * H * 0.95)
            c = QColor(self.color); c.setAlpha(int(70 + 185 * edge))
            p.setPen(QPen(c, max(1.5, step * 0.45), cap=Qt.PenCapStyle.RoundCap))
            x = step * (i + 0.5)
            p.drawLine(QPointF(x, mid - h / 2), QPointF(x, mid + h / 2))


class Ring(QWidget):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name, self.val = name, 0.0
        self.setMinimumSize(70, 70)

    def set_value(self, v):
        self.val = max(0.0, min(100.0, v)); self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = min(self.width(), self.height()) - 8
        r = QRectF((self.width() - s) / 2, (self.height() - s) / 2, s, s)
        p.setBrush(QColor(4, 16, 32, 200)); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(r)
        w = max(5, s * 0.1)
        rr = r.adjusted(w, w, -w, -w)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(30, 70, 100, 200), w)); p.drawEllipse(rr)
        p.setPen(QPen(CY, w, cap=Qt.PenCapStyle.RoundCap))
        p.drawArc(rr, 90 * 16, int(-self.val / 100 * 360 * 16))
        p.setPen(QColor(TXT)); p.setFont(F(max(7, s * 0.14), True))
        p.drawText(QRectF(r.left(), r.top() + s * 0.2, s, s * 0.3), Qt.AlignmentFlag.AlignCenter, self.name)
        p.setFont(F(max(8, s * 0.17), True))
        p.drawText(QRectF(r.left(), r.top() + s * 0.45, s, s * 0.3), Qt.AlignmentFlag.AlignCenter, f"{self.val:.0f}%")


class Constellation(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        rnd = random.Random(3)
        self.p = [(rnd.random(), rnd.random()) for _ in range(14)]

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        pts = [QPointF(10 + x * (W - 20), 8 + y * (H - 26)) for x, y in self.p]
        p.setPen(QPen(QColor(40, 150, 200, 110), 1))
        for i in range(len(pts) - 1):
            p.drawLine(pts[i], pts[i + 1])
        p.drawLine(pts[0], pts[5]); p.drawLine(pts[3], pts[9])
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#7fe3ff"))
        for q in pts:
            p.drawEllipse(q, 2.4, 2.4)


class Clickable(QFrame):
    clicked = pyqtSignal()

    def mousePressEvent(self, e):
        self.clicked.emit()


class ClickLabel(QLabel):
    clicked = pyqtSignal()

    def mousePressEvent(self, e):
        self.clicked.emit()


class ProviderDialog(QWidget):
    """Manage Providers: paste keys (stored only in config/api_keys.json, gitignored)
    and pick the active free model. Existing keys are never shown."""
    def __init__(self, win, parent=None):
        super().__init__(parent, Qt.WindowType.Dialog)
        from core import providers as P
        self.P = P; self.win = win
        self.setWindowTitle("Manage Providers")
        self.setStyleSheet("QWidget{background:#071428;color:%s;} QLineEdit{background:#0a1f3a;border:1px solid #1f6a96;"
                           "border-radius:4px;padding:5px;} QPushButton{background:#0b3a66;border:1px solid #27d3ff;"
                           "border-radius:4px;padding:6px 14px;} QPushButton:hover{background:#0d4a80;}" % TXT)
        v = QVBoxLayout(self); v.setSpacing(8)
        v.addWidget(lbl("MANAGE PROVIDERS", 11, "#e9f6ff", True, 2))
        v.addWidget(lbl("Free-only mode: FRIDAY never uses a paid model automatically. Keys stay on this computer "
                        "(config/api_keys.json, never uploaded).", 8, TXT_D))
        v.itemAt(v.count() - 1).widget().setWordWrap(True)
        cfg = P.load_config()
        self.edits = {}
        fields = [("gemini", "Gemini API key (free tier)"), ("nvidia", "NVIDIA API key (free trial)"),
                  ("elevenlabs", "ElevenLabs API key (free plan, voice)"),
                  ("deepseek", "DeepSeek key (PAID - not used in free-only mode)"),
                  ("openai", "OpenAI key (PAID - not used in free-only mode)")]
        for key, label in fields:
            field = "elevenlabs_api_key" if key == "elevenlabs" else P.SPECS[key].key_field
            saved = bool(str(cfg.get(field) or "").strip()) and "PASTE_YOUR" not in str(cfg.get(field))
            v.addWidget(lbl(label + ("  - saved" if saved else ""), 8.5, GREEN if saved else TXT))
            e = QLineEdit(); e.setEchoMode(QLineEdit.EchoMode.Password)
            e.setPlaceholderText("saved - type to replace" if saved else "paste key here")
            self.edits[field] = e; v.addWidget(e)
        v.addWidget(lbl("Active model", 8.5))
        from PyQt6.QtWidgets import QComboBox
        self.combo = QComboBox()
        for n in P.FREE_ORDER:
            self.combo.addItem(P.SPECS[n].label, n)
        cur = cfg.get("active_provider") or "gemini"
        i = self.combo.findData(cur)
        self.combo.setCurrentIndex(max(0, i))
        v.addWidget(self.combo)
        row = QHBoxLayout(); row.addStretch()
        b = QPushButton("Save"); b.clicked.connect(self._save); row.addWidget(b)
        c = QPushButton("Close"); c.clicked.connect(self.close); row.addWidget(c)
        v.addLayout(row)
        self.setMinimumWidth(420)

    def _save(self):
        upd = {f: e.text().strip() for f, e in self.edits.items() if e.text().strip()}
        if upd:
            self.P.save_config(upd)
        msg = self.P.set_active(self.combo.currentData())
        self.win._log.append_log(f"SYS: Providers saved. {msg}")
        self.win._home.refresh()
        self.close()


class Dot(QWidget):
    def __init__(self, color, parent=None):
        super().__init__(parent); self.c = QColor(color); self.setFixedSize(8, 8)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(self.c); p.drawEllipse(1, 1, 6, 6)


class Row(QFrame):
    """Small bordered row: icon box + two-line text (+ optional tag)."""
    def __init__(self, icon, title, sub="", sub_color=GREEN, tag="", tag_color=CY.name(), parent=None):
        super().__init__(parent)
        self.setStyleSheet("QFrame{background:rgba(10,36,66,150);border:1px solid rgba(40,130,190,90);border-radius:5px;}")
        h = QHBoxLayout(self); h.setContentsMargins(6, 3, 6, 3); h.setSpacing(8)
        ic = QLabel(icon); ic.setFixedWidth(22); ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setFont(F(10)); ic.setStyleSheet(f"color:{CY.name()};background:rgba(20,70,110,160);border:1px solid rgba(40,150,200,120);border-radius:4px;")
        h.addWidget(ic)
        col = QVBoxLayout(); col.setSpacing(0); col.setContentsMargins(0, 0, 0, 0)
        self.t = QLabel(title); self.t.setFont(F(8.5, True)); self.t.setStyleSheet(f"color:{TXT};background:transparent;border:none;")
        self.s = QLabel(sub); self.s.setFont(F(7)); self.s.setStyleSheet(f"color:{sub_color};background:transparent;border:none;")
        col.addWidget(self.t); col.addWidget(self.s)
        h.addLayout(col, 1)
        self.tag = QLabel(tag); self.tag.setFont(F(6.5, True))
        self.tag.setStyleSheet(f"color:{tag_color};background:transparent;border:none;")
        h.addWidget(self.tag)

    def set(self, title=None, sub=None, sub_color=None, tag=None):
        if title is not None: self.t.setText(title)
        if sub is not None: self.s.setText(sub)
        if sub_color: self.s.setStyleSheet(f"color:{sub_color};background:transparent;border:none;")
        if tag is not None: self.tag.setText(tag)


# ───────────────────────────── home view ─────────────────────────────
PROVIDERS = [("Gemini", "gemini"), ("NVIDIA", "nvidia"), ("DeepSeek", "deepseek"),
             ("OpenAI", "openai"), ("ElevenLabs", "elevenlabs")]


class HomeView(QWidget):
    _weather_sig = pyqtSignal(str, str)

    def __init__(self, win, name="FRIDAY", parent=None):
        super().__init__(parent)
        self.win, self.name = win, name
        self._feed_items: list[tuple[str, str, str]] = []
        self.setStyleSheet("background:transparent;")
        self.setMinimumSize(960, 620)
        root = QVBoxLayout(self); root.setContentsMargins(8, 8, 8, 8); root.setSpacing(8)

        # row 1: overview | globe | feed
        r1 = QHBoxLayout(); r1.setSpacing(10)
        self.ov = Card("AI CORE OVERVIEW"); self.ov.setMinimumWidth(165); self.ov.setMaximumWidth(215)
        self.ov_rows = {}
        for key, ic, t, s, col in [("core", "◎", "AI Core", "Active", GREEN), ("mem", "▤", "Memory", "—", CY.name()),
                                   ("voice", "♪", "Voice", "Online", GREEN), ("agents", "⚇", "Agents", "0 Running", PURPLE),
                                   ("llms", "◈", "LLMs", "—", AMBER), ("sys", "⛨", "System", "Optimal", GREEN)]:
            r = Row(ic, t, s, col); self.ov_rows[key] = r; self.ov.lay.addWidget(r)
        self.globe = Globe(name)
        self.feed = Card("LIVE INTELLIGENCE FEED"); self.feed.setMinimumWidth(205); self.feed.setMaximumWidth(290)
        live = lbl("● LIVE", 7, GREEN, True); self.feed.lay.itemAt(0).layout().addWidget(live)
        self.feed_box = QVBoxLayout(); self.feed_box.setSpacing(4)
        self.feed.lay.addLayout(self.feed_box); self.feed.lay.addStretch()
        self.feed_all = self._link("View All Intelligence ›", lambda: self.win._nav_to("tasks"), Qt.AlignmentFlag.AlignRight)
        self.feed.lay.addWidget(self.feed_all)
        r1.addWidget(self.ov, 3); r1.addWidget(self.globe, 9); r1.addWidget(self.feed, 4)

        # row 2: agents | timeline | quick
        r2 = QHBoxLayout(); r2.setSpacing(10)
        self.ag = Card("ACTIVE AGENTS", "View All ›")
        self.ag.link.clicked.connect(lambda: self.win._nav_to("agents"))
        grid = QGridLayout(); grid.setSpacing(6)
        self.agents = {}
        for i, (nm, ic) in enumerate([("Coding Agent", "</>"), ("Research Agent", "⌕"), ("Memory Agent", "▤"),
                                      ("Browser Agent", "◍"), ("Task Agent", "☑"), ("System Agent", "⛨")]):
            c = QFrame(); c.setStyleSheet("QFrame{background:rgba(10,36,66,150);border:1px solid rgba(40,130,190,100);border-radius:6px;}")
            v = QHBoxLayout(c); v.setContentsMargins(8, 5, 8, 5); v.setSpacing(6)
            icl = lbl(ic, 11, CY.name(), True); icl.setStyleSheet(f"color:{CY.name()};background:transparent;border:none;")
            v.addWidget(icl)
            col = QVBoxLayout(); col.setSpacing(0)
            t = lbl(nm, 8, TXT, True); t.setStyleSheet(f"color:{TXT};background:transparent;border:none;")
            st = lbl("● Standby", 7, AMBER); st.setStyleSheet(f"color:{AMBER};background:transparent;border:none;")
            col.addWidget(t); col.addWidget(st); v.addLayout(col, 1)
            w = Wave(CY, 14); w.setFixedSize(46, 22); w.active = False; v.addWidget(w)
            c.setCursor(Qt.CursorShape.PointingHandCursor); c.mousePressEvent = (lambda e: self.win._nav_to("agents"))
            self.agents[nm] = (st, w)
            grid.addWidget(c, i // 3, i % 3)
        self.ag.lay.addLayout(grid, 1)
        self.tl = Card("MISSION TIMELINE", "Today ⌄"); self._tl_all = False
        self.tl.link.clicked.connect(self._toggle_tl)
        self.tl_box = QVBoxLayout(); self.tl_box.setSpacing(5); self.tl.lay.addLayout(self.tl_box)
        self.tl.lay.addStretch()
        self.tl.lay.addWidget(self._link("View Full Schedule ›", lambda: self.win._nav_to("calendar"), Qt.AlignmentFlag.AlignCenter))
        self.qc = Card("QUICK COMMANDS")
        for ic, t, fn in [("＋", "Start New Task", self._q_new), ("▦", "Open Calendar", self._q_cal),
                          ("♪", "Start Voice Chat", self._q_voice), ("▷", "Run Workflow", self._q_flow)]:
            b = QPushButton(f"  {ic}   {t}"); b.setFont(F(8.5)); b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet("QPushButton{color:%s;text-align:left;padding:5px 8px;background:rgba(10,36,66,150);"
                            "border:1px solid rgba(40,130,190,100);border-radius:5px;}"
                            "QPushButton:hover{border-color:%s;background:rgba(20,70,110,170);}" % (TXT, CY.name()))
            b.clicked.connect(fn); self.qc.lay.addWidget(b)
        self.qc.lay.addStretch()
        r2.addWidget(self.ag, 8); r2.addWidget(self.tl, 4); r2.addWidget(self.qc, 3)

        # row 3: system monitor | memory insights | llm status
        r3 = QHBoxLayout(); r3.setSpacing(10)
        self.sm = Card("SYSTEM MONITOR")
        rr = QHBoxLayout(); self.rings = {k: Ring(k) for k in ("CPU", "RAM", "Disk")}
        for w in self.rings.values(): rr.addWidget(w)
        self.sm.lay.addLayout(rr, 1)
        self.mi = Card("MEMORY INSIGHTS")
        mh = QHBoxLayout(); self.const = Constellation(); mh.addWidget(self.const, 3)
        st = QVBoxLayout(); st.setSpacing(2)
        self.mi_vals = {}
        for k in ("Memories", "Session Turns", "Tool Calls"):
            st.addWidget(lbl(k, 7, TXT_D)); v = lbl("0", 12, TXT, True); self.mi_vals[k] = v; st.addWidget(v)
        mh.addLayout(st, 2); self.mi.lay.addLayout(mh, 1)
        self.mi.lay.addWidget(self._link("View Memory Map ›", lambda: self.win._nav_to("memory"), Qt.AlignmentFlag.AlignCenter))
        self.ls = Card("LLM STATUS"); self.ls.lay.itemAt(0).layout().addWidget(lbl("", 7, GREEN, True))
        self.ls_count = self.ls.lay.itemAt(0).layout().itemAt(2).widget()
        lg = QGridLayout(); lg.setSpacing(5); self.ls_cells = {}
        for i, (nm, key) in enumerate(PROVIDERS):
            c = Clickable(); c.setStyleSheet("QFrame{background:rgba(10,36,66,150);border:1px solid rgba(40,130,190,90);border-radius:5px;}")
            c.setCursor(Qt.CursorShape.PointingHandCursor)
            c.clicked.connect(lambda k=key: self._pick(k))
            h = QHBoxLayout(c); h.setContentsMargins(7, 3, 7, 3); h.setSpacing(6)
            ic = lbl("◈", 10, CY.name()); ic.setStyleSheet(f"color:{CY.name()};background:transparent;border:none;"); h.addWidget(ic)
            col = QVBoxLayout(); col.setSpacing(0)
            t = lbl(nm, 8, TXT, True); t.setStyleSheet(f"color:{TXT};background:transparent;border:none;")
            s = lbl("Not Linked", 7, TXT_D); s.setStyleSheet(f"color:{TXT_D};background:transparent;border:none;")
            col.addWidget(t); col.addWidget(s); h.addLayout(col, 1)
            self.ls_cells[key] = s; lg.addWidget(c, i // 3, i % 3)
        self.ls.lay.addLayout(lg, 1)
        mp = ClickLabel("Manage Providers ›"); mp.setFont(F(8)); mp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mp.setStyleSheet(f"color:{CY.name()};background:transparent;"); mp.setCursor(Qt.CursorShape.PointingHandCursor)
        mp.clicked.connect(self._manage); self.ls.lay.addWidget(mp)
        r3.addWidget(self.sm, 5); r3.addWidget(self.mi, 5); r3.addWidget(self.ls, 9)

        root.addLayout(r1, 27); root.addLayout(r2, 15); root.addLayout(r3, 15)

        self._tmr = QTimer(self); self._tmr.timeout.connect(self.refresh); self._tmr.start(1500)
        self._weather_sig.connect(self._set_weather)
        self.refresh()
        self._push("FRIDAY online", "System", "LIVE", GREEN)

    def _link(self, text, fn, align):
        l = ClickLabel(text); l.setFont(F(8)); l.setAlignment(align)
        l.setStyleSheet(f"color:{CY.name()};background:transparent;"); l.setCursor(Qt.CursorShape.PointingHandCursor)
        l.clicked.connect(fn); return l

    def _toggle_tl(self):
        self._tl_all = not self._tl_all
        self.tl.link.setText("All ⌄" if self._tl_all else "Today ⌄")
        self.refresh()

    # ---- feed ----
    def _push(self, title, sub, tag, color=None):
        self._feed_items.insert(0, (title, sub, tag, color or CY.name()))
        del self._feed_items[6:]
        clear_layout(self.feed_box)
        for (t, s, g, c) in self._feed_items:
            r = Row("◉", t[:34], s, TXT_D, g, c); self.feed_box.addWidget(r)

    def on_log(self, text: str):
        t = text.strip()
        if not t:
            return
        if t.startswith("SORRY") or "SORRY:" in t:
            self._push(t[:60], "Task failed", "WARN", RED)
        elif t.startswith("You:"):
            self._push(t[4:].strip()[:60], "Command", "INFO", CY.name())
        elif t.startswith("SYS:"):
            self._push(t[4:].strip()[:60], "System", "INFO", CY.name())

    def _manage(self):
        self._dlg = ProviderDialog(self.win)
        self._dlg.show()

    def _pick(self, key: str):
        if key == "elevenlabs":
            self._manage(); return
        from core import providers as P
        if key in P.SPECS:
            msg = P.set_active(key)
            self.win._log.append_log(f"SYS: {msg}")
            self._push(msg[:48], "Model switch", "INFO", CY.name())
            self.refresh()

    # ---- quick commands ----
    def _q_new(self):
        self.win._nav_to("search")
    def _q_cal(self):
        self.win._nav_to("calendar")
    def _q_voice(self):
        self.win._tap_wake_manual()
    def _q_flow(self):
        self.win._nav_to("flows")

    # ---- live data ----
    def set_level(self, v):
        self.globe.set_level(v)

    def _keys(self) -> dict:
        try:
            d = json.loads((Path(__file__).resolve().parent / "config" / "api_keys.json").read_text("utf-8"))
        except Exception:
            d = {}
        return d

    def refresh(self):
        try:
            from core.tasks import TASKS
            tasks, cnt = TASKS.snapshot(), TASKS.counts()
        except Exception:
            tasks, cnt = [], {"RUNNING": 0, "DONE": 0, "FAILED": 0}
        from core import providers as P
        d = self._keys()
        st = P.status(d)
        n = 0
        for key, s in self.ls_cells.items():
            if key in st:
                v = st[key]
            elif key == "elevenlabs":
                v = "connected" if str(d.get("elevenlabs_api_key") or "").strip() else "not-linked"
            else:
                v = "soon"
            text, col = {"active": ("Active", GREEN), "connected": ("Connected", GREEN),
                         "paid-off": ("Paid - off", AMBER), "not-linked": ("Not Linked", TXT_D),
                         "soon": ("Coming soon", TXT_D)}[v]
            s.setText(text); s.setStyleSheet(f"color:{col};background:transparent;border:none;")
            if v in ("active", "connected"):
                n += 1
        self.ls_count.setText(f"{n} Connected")
        self.ov_rows["llms"].set(sub=f"{n} Connected")
        self.ov_rows["agents"].set(sub=f"{cnt['RUNNING']} Running")
        muted = getattr(self.win, "_muted", False)
        self.ov_rows["voice"].set(sub="Muted" if muted else "Online", sub_color=RED if muted else GREEN)
        # memory count
        try:
            from memory.memory_manager import load_memory
            m = load_memory(); cntm = sum(len(v) for v in m.values()) if isinstance(m, dict) else 0
        except Exception:
            cntm = 0
        self.ov_rows["mem"].set(sub=f"{cntm:,} Stored"); self.mi_vals["Memories"].setText(f"{cntm:,}")
        self.mi_vals["Tool Calls"].setText(str(len(tasks)))
        self.mi_vals["Session Turns"].setText(str(getattr(self.win, "_turns", 0)))
        # agents: lit by the real tasks they own (see pages_view.AGENT_TOOLS)
        from pages_view import agent_state
        astate = agent_state(tasks)
        for nm, (st, w) in self.agents.items():
            n_run = astate.get(nm, {}).get("running", 0)
            on = n_run > 0
            st.setText(f"● Running {n_run}" if on else "● Standby")
            col = GREEN if on else AMBER
            st.setStyleSheet(f"color:{col};background:transparent;border:none;"); w.active = on
        # timeline
        clear_layout(self.tl_box)
        _today = time.strftime("%Y-%m-%d")
        _pool = tasks if self._tl_all else [t for t in tasks if time.strftime("%Y-%m-%d", time.localtime(t["started"])) == _today]
        shown = list(reversed(_pool[-4:]))
        if not shown:
            self.tl_box.addWidget(lbl('No tasks yet. Say "Friday, ..." to start one.', 8, TXT_D))
        for t in shown:
            col = {"RUNNING": AMBER, "DONE": GREEN, "FAILED": RED}[t["status"]]
            word = {"RUNNING": "Running", "DONE": "Done", "FAILED": "Failed"}[t["status"]]
            h = QHBoxLayout(); h.setSpacing(6)
            h.addWidget(lbl(time.strftime("%I:%M", time.localtime(t["started"])), 7.5, TXT_D))
            h.addWidget(Dot(col)); h.addWidget(lbl(t["name"][:22], 8, TXT, True), 1)
            h.addWidget(lbl(word, 7.5, col)); self.tl_box.addLayout(h)
        # system rings
        snap = self.win._metrics_snapshot()
        self.rings["CPU"].set_value(snap.get("cpu", 0)); self.rings["RAM"].set_value(snap.get("mem", 0))
        try:
            import psutil
            self.rings["Disk"].set_value(psutil.disk_usage(Path.home().anchor or "/").percent)
        except Exception:
            pass

    # ---- weather / location (filled by the window's bottom bar) ----
    def _set_weather(self, *_):
        pass


# ───────────────────────────── chrome: sidebar / top bar / talk bar ─────────────────────────────
NAV = [("Command Center", "▦", "home"), ("AI Core", "◎", "core"), ("Agents", "⚇", "agents"),
       ("Tasks", "☑", "tasks"), ("Calendar", "▤", "calendar"), ("Memory", "⛁", "memory"),
       ("Conversations", "☰", "convos"), ("Knowledge Base", "▥", "kb"),
       ("Tools && Skills", "⚒", "tools"), ("Workflows", "⛓", "flows")]


class LogoBadge(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent); self.setFixedSize(34, 34)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(17, 17)
        for r, a in ((15, 255), (10, 200), (5, 255)):
            p.setPen(QPen(QColor(39, 211, 255, a), 1.8)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawEllipse(c, r, r)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(CY); p.drawEllipse(c, 2.5, 2.5)


class Sidebar(QWidget):
    navigate = pyqtSignal(str)

    def __init__(self, win, name="FRIDAY", parent=None):
        super().__init__(parent)
        self.win = win; self.setFixedWidth(196)
        v = QVBoxLayout(self); v.setContentsMargins(8, 8, 4, 8); v.setSpacing(6)
        head = Card(); head.lay.setContentsMargins(10, 8, 10, 8)
        hh = QHBoxLayout(); hh.addWidget(LogoBadge())
        col = QVBoxLayout(); col.setSpacing(0)
        self.title = lbl(name, 17, "#e9f6ff", True, 3)
        col.addWidget(self.title); col.addWidget(lbl("COMMAND CENTER", 6.5, "#7fc6e6", False, 2.4))
        hh.addLayout(col); head.lay.addLayout(hh); v.addWidget(head)
        self.btns = {}
        self.badge = {}
        for (t, ic, key) in NAV:
            b = QPushButton(f"  {ic}    {t}"); b.setCheckable(True); b.setFont(F(9.5))
            b.setCursor(Qt.CursorShape.PointingHandCursor); b.setFixedHeight(31)
            b.setStyleSheet("QPushButton{color:%s;text-align:left;padding-left:8px;border:1px solid transparent;"
                            "background:transparent;border-radius:3px;}"
                            "QPushButton:hover{background:rgba(20,70,110,110);}"
                            "QPushButton:checked{color:#ffffff;background:rgba(25,90,140,120);"
                            "border:1px solid rgba(39,211,255,170);}" % TXT)
            b.clicked.connect(lambda _=False, k=key: self.navigate.emit(k))
            self.btns[key] = b; v.addWidget(b)
        self.btns["home"].setChecked(True)
        v.addStretch()
        vc = Card("VOICE STATUS"); vc.lay.setSpacing(4)
        self.wave = Wave(CY, 26); self.wave.setFixedHeight(28); vc.lay.addWidget(self.wave)
        self.vstate = lbl("Listening...", 8, TXT, align=Qt.AlignmentFlag.AlignCenter); vc.lay.addWidget(self.vstate)
        self.mic = QPushButton("🎙"); self.mic.setFixedSize(62, 62); self.mic.setFont(F(18))
        self.mic.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mic.setStyleSheet("QPushButton{color:#7fe3ff;border:2px solid #27d3ff;border-radius:31px;"
                               "background:qradialgradient(cx:.5,cy:.5,radius:.7,stop:0 #0d3a66,stop:1 #06182e);}"
                               "QPushButton:hover{background:#0f4a82;}")
        self.mic.clicked.connect(win._tap_wake_manual)
        mrow = QHBoxLayout(); mrow.addStretch(); mrow.addWidget(self.mic); mrow.addStretch(); vc.lay.addLayout(mrow)
        vc.lay.addWidget(lbl("Tap to Speak", 7.5, TXT_D, align=Qt.AlignmentFlag.AlignCenter))
        self.focus = QPushButton("⚡ Focus Mode"); self.focus.setFont(F(8.5)); self.focus.setCheckable(True)
        self.focus.setStyleSheet("QPushButton{color:%s;padding:5px;border:1px solid rgba(40,130,190,130);"
                                 "border-radius:12px;background:rgba(10,36,66,150);}"
                                 "QPushButton:checked{border-color:#27d3ff;color:#fff;}" % TXT)
        self.focus.setToolTip("FRIDAY stays quiet: no proactive check-ins or monitor alerts")
        self.focus.toggled.connect(win._set_focus)
        vc.lay.addWidget(self.focus)
        v.addWidget(vc)

    def select(self, key: str):
        for k, b in self.btns.items():
            b.setChecked(k == key)

    def set_task_count(self, n: int):
        b = self.btns["tasks"]
        b.setText(f"  ☑    Tasks" + (f"      ●{n}" if n else ""))


class TopBar(QWidget):
    def __init__(self, win, parent=None):
        super().__init__(parent); self.win = win; self.setFixedHeight(64)
        h = QHBoxLayout(self); h.setContentsMargins(8, 8, 8, 4); h.setSpacing(10)
        pill = QFrame(); pill.setStyleSheet("QFrame{background:rgba(9,30,56,190);border:1px solid rgba(40,150,200,150);border-radius:15px;}")
        ph = QHBoxLayout(pill); ph.setContentsMargins(14, 4, 14, 4); ph.setSpacing(8)
        a = lbl("SYSTEM STATUS", 8, TXT, True, 1.2); a.setStyleSheet(f"color:{TXT};border:none;background:transparent;")
        self.status = lbl("● OPTIMAL", 8, GREEN, True); self.status.setStyleSheet(f"color:{GREEN};border:none;background:transparent;")
        ph.addWidget(a); ph.addWidget(self.status); h.addWidget(pill)
        h.addStretch()
        mid = QVBoxLayout(); mid.setSpacing(0)
        self.date = lbl("", 8.5, TXT, align=Qt.AlignmentFlag.AlignCenter)
        self.clock = lbl("", 17, CY.name(), True, 1.5, Qt.AlignmentFlag.AlignCenter)
        mid.addWidget(self.date); mid.addWidget(self.clock); h.addLayout(mid)
        h.addStretch()
        self.search = QLineEdit(); self.search.setPlaceholderText('🔍  Say "Friday, ..." or type a command')
        self.search.setFont(F(9)); self.search.setFixedHeight(34); self.search.setMinimumWidth(190); self.search.setMaximumWidth(300)
        self.search.setStyleSheet("QLineEdit{color:%s;background:rgba(9,30,56,190);border:1px solid rgba(40,150,200,150);"
                                  "border-radius:6px;padding:0 10px;}QLineEdit:focus{border-color:#27d3ff;}" % TXT)
        self.search.returnPressed.connect(self._go); h.addWidget(self.search, 1)

        def ib(txt, tip, fn):
            b = QPushButton(txt); b.setFixedSize(34, 34); b.setFont(F(11)); b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet("QPushButton{color:%s;background:rgba(9,30,56,190);border:1px solid rgba(40,150,200,130);border-radius:6px;}"
                            "QPushButton:hover{border-color:#27d3ff;color:#fff;}" % TXT)
            b.clicked.connect(fn); h.addWidget(b); return b
        self._opt = []
        ib("⛶", "Full screen on/off  [F11]", win._toggle_fullscreen)
        self._opt.append(ib("▦", "Command Center", lambda: win._nav_to("home")))
        self._opt.append(ib("⚑", "Activity", lambda: win._nav_to("tasks")))
        ib("⚙", "Settings & Controls", lambda: win._drawer_btn.click())
        prof = QFrame(); prof.setStyleSheet("QFrame{background:rgba(9,30,56,190);border:1px solid rgba(40,150,200,150);border-radius:17px;}")
        pl = QHBoxLayout(prof); pl.setContentsMargins(12, 2, 6, 2); pl.setSpacing(8)
        col = QVBoxLayout(); col.setSpacing(0)
        self.user = lbl("Operator", 8.5, TXT, True); self.user.setStyleSheet(f"color:{TXT};border:none;background:transparent;")
        sub = lbl("Commander", 7, TXT_D); sub.setStyleSheet(f"color:{TXT_D};border:none;background:transparent;")
        col.addWidget(self.user); col.addWidget(sub); pl.addLayout(col)
        av = lbl("◉", 14, CY.name()); av.setStyleSheet(f"color:{CY.name()};border:none;background:transparent;"); pl.addWidget(av)
        prof.setCursor(Qt.CursorShape.PointingHandCursor); prof.setToolTip("Click to change your name")
        prof.mousePressEvent = lambda e: win._edit_name()
        h.addWidget(prof); self.prof = prof
        self._status_tick = 0
        t = QTimer(self); t.timeout.connect(self.tick); t.start(1000); self.tick()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        w = self.width()
        for b in self._opt:
            b.setVisible(w >= 940)
        self.prof.setVisible(w >= 820)
        self.search.setMinimumWidth(120 if w < 940 else 190)

    def _go(self):
        txt = self.search.text().strip()
        if txt:
            self.search.clear(); self.win._send_text(txt)

    def tick(self):
        self._status_tick += 1
        if self._status_tick % 3 == 1:
            try:
                s = self.win._metrics_snapshot(); cpu, mem = s.get("cpu", 0), s.get("mem", 0)
                if cpu >= 90 or mem >= 92:
                    self.status.setText("● HIGH LOAD"); c = RED
                elif cpu >= 75 or mem >= 85:
                    self.status.setText("● BUSY"); c = AMBER
                else:
                    self.status.setText("● OPTIMAL"); c = GREEN
                self.status.setStyleSheet(f"color:{c};border:none;background:transparent;")
            except Exception:
                pass
        self.date.setText(time.strftime("%A, %d %B %Y"))
        self.clock.setText(time.strftime("%I:%M:%S %p").lower())


class TalkBar(QWidget):
    _wx = pyqtSignal(str, str)

    def __init__(self, win, name="FRIDAY", parent=None):
        super().__init__(parent); self.win = win; self.setFixedHeight(74)
        h = QHBoxLayout(self); h.setContentsMargins(8, 4, 8, 8); h.setSpacing(8)

        self._chips = []

        def chip(icon, head, val):
            c = QFrame(); c.setStyleSheet("QFrame{background:rgba(9,30,56,190);border:1px solid rgba(40,130,190,110);border-radius:6px;}")
            l = QHBoxLayout(c); l.setContentsMargins(10, 4, 12, 4); l.setSpacing(8)
            ic = lbl(icon, 12, AMBER); ic.setStyleSheet(f"color:{AMBER};border:none;background:transparent;"); l.addWidget(ic)
            col = QVBoxLayout(); col.setSpacing(0)
            a = lbl(head, 6.5, TXT_D); a.setStyleSheet(f"color:{TXT_D};border:none;background:transparent;")
            b = lbl(val, 8.5, TXT, True); b.setStyleSheet(f"color:{TXT};border:none;background:transparent;")
            col.addWidget(a); col.addWidget(b); l.addLayout(col); h.addWidget(c); self._chips.append(c); return b
        self.loc = chip("⌖", "Location", "Locating…")
        self.wx = chip("☀", "Weather", "—")
        self.net = chip("⌁", "Network", "—")
        h.addStretch()
        self.btn = QPushButton(); self.btn.setFixedHeight(58); self.btn.setMinimumWidth(300)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setFont(F(10, True, 1.5))
        self.btn.setStyleSheet("QPushButton{color:#7fe3ff;border:2px solid #27d3ff;border-radius:29px;"
                               "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #072746,stop:.5 #0b3a66,stop:1 #072746);}"
                               "QPushButton:hover{background:#0d4a80;}")
        self.btn.clicked.connect(win._tap_wake_manual)
        self.set_state("LISTENING")
        h.addWidget(self.btn)
        self.wave = Wave(CY, 30); self.wave.setFixedSize(150, 40)
        h.addWidget(self.wave)
        h.addStretch()
        eb = QPushButton("▤  Executive Briefing"); eb.setFont(F(9)); eb.setFixedHeight(38)
        eb.setCursor(Qt.CursorShape.PointingHandCursor)
        eb.setStyleSheet("QPushButton{color:%s;padding:0 16px;background:rgba(9,30,56,190);border:1px solid rgba(40,150,200,150);border-radius:6px;}"
                         "QPushButton:hover{border-color:#27d3ff;}" % TXT)
        eb.clicked.connect(lambda: win._send_text(__import__("core.seed", fromlist=["x"]).BRIEFING_PROMPT))
        h.addWidget(eb); self._eb = eb
        self._wx.connect(self._set_wx)
        self._nt = QTimer(self); self._nt.timeout.connect(self._net); self._nt.start(5000); self._net()
        import os
        if not os.environ.get("FRIDAY_UI_TEST"):
            threading.Thread(target=self._fetch_wx, daemon=True).start()
        else:
            self._wx.emit("", "")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        w = self.width()
        self.wave.setVisible(w >= 1120)
        self._chips[2].setVisible(w >= 1000)
        self._chips[1].setVisible(w >= 900)
        self._eb.setText("▤  Executive Briefing" if w >= 900 else "▤")
        self.btn.setMinimumWidth(300 if w >= 900 else 220)

    def set_state(self, text_line: str):
        pass

    def set_voice(self, name: str, line: str):
        self.btn.setText(f"TALK TO {name.upper()}\n{line}")

    def _net(self):
        try:
            import psutil
            up = any(s.isup for k, s in psutil.net_if_stats().items() if not k.lower().startswith("lo"))
            self.net.setText("Excellent" if up else "Offline")
        except Exception:
            self.net.setText("—")

    def _fetch_wx(self):
        try:
            import urllib.request
            raw = urllib.request.urlopen("https://wttr.in/?m&format=%l|%t|%C", timeout=5).read().decode("utf-8", "ignore")
            loc, t, c = (raw.strip().split("|") + ["", "", ""])[:3]
            self._wx.emit(loc.strip(), f"{t.strip()} {c.strip()}".strip())
        except Exception:
            self._wx.emit("", "")

    def _set_wx(self, loc: str, wx: str):
        import re
        if loc and re.fullmatch(r"[-+0-9., ]+", loc):
            loc = "Auto-detected"
        self.loc.setText(loc[:22] if loc else "Unavailable")
        self.wx.setText(wx[:22] if wx else "Unavailable")
