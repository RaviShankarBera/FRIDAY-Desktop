"""No leftover 'Jarvis' branding in anything the user can see."""
import ast, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"tests", "models", "__pycache__", ".git", ".knowledge", "logs"}
# internal identifiers that are never shown (wire keys, tool names, cert files, salt)
ALLOWED = ["shutdown_jarvis", "jarvis_token", "jarvis_key", "jarvis_device_token",
           "JARVIS-DASHBOARD-v1", "speaker === 'jarvis'", "jarvis.key", "jarvis.crt", "most trusted friend Jarvis"]


def _clean(s: str) -> str:
    for a in ALLOWED:
        s = s.replace(a, "")
    return s


def _files(*pats):
    for pat in pats:
        for p in ROOT.rglob(pat):
            if not (set(p.relative_to(ROOT).parts) & SKIP):
                yield p


def test_no_jarvis_in_python_strings():
    bad = []
    for p in _files("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                s = _clean(n.value)
                if re.search("jarvis", s, re.I) and s.strip().lower() != "jarvis":
                    bad.append(f"{p.relative_to(ROOT)}:{n.lineno}: {n.value[:60]!r}")
    assert not bad, bad


def test_no_jarvis_in_html_and_prompt():
    bad = []
    for p in list(_files("*.html")) + [ROOT / "core" / "prompt.txt"]:
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search("jarvis", _clean(line), re.I):
                bad.append(f"{p.relative_to(ROOT)}:{i}")
    assert not bad, bad


def test_memory_popup_title():
    src = (ROOT / "ui.py").read_text(encoding="utf-8")
    assert "WHAT FRIDAY REMEMBERS" in src
