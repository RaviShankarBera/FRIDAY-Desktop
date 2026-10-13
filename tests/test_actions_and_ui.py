import json, os, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_new_actions_are_discovered():
    from core.action_loader import discover_actions
    names = discover_actions(ROOT / "actions", set(), lambda m: None).names()
    assert {"agent_task", "knowledge_add", "knowledge_search", "switch_model"} <= names


def test_switch_model_action_refuses_paid(tmp_path, monkeypatch):
    from core import providers as P
    p = tmp_path / "k.json"
    p.write_text(json.dumps({"gemini_api_key": "g", "deepseek_api_key": "d"}))
    monkeypatch.setattr(P, "CONFIG_PATH", p)
    from actions.switch_model import switch_model
    assert "free-only" in switch_model({"provider": "deepseek"})
    assert switch_model({"provider": "gemini"}).startswith("Switched")


def test_knowledge_actions_roundtrip(tmp_path, monkeypatch):
    from core import rag
    monkeypatch.setattr(rag, "KB_DIR", tmp_path / "kb")
    monkeypatch.setattr(rag, "default_embedder", lambda: rag.HashEmbedder())
    from actions.knowledge_base import knowledge_add
    from actions.knowledge_search import knowledge_search
    assert "empty" in knowledge_search({"query": "x"})
    assert "Added" in knowledge_add({"text": "FRIDAY wake word is Friday", "name": "n"})
    assert "wake word" in knowledge_search({"query": "wake word"})


def test_prompt_has_identity_rules():
    t = (ROOT / "core" / "prompt.txt").read_text(encoding="utf-8")
    for k in ("Godspeed", "Yes boss", "Mr. Ravi Shankar Bera and his most trusted friend Jarvis", "V1.0"):
        assert k in t


def test_ui_renders_and_enforces_free_only(tmp_path):
    pytest.importorskip("PyQt6")
    cfg = ROOT / "config" / "api_keys.json"
    if cfg.exists():
        pytest.skip("real key file present; not touching it")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["FRIDAY_UI_TEST"] = "1"
    cfg.write_text(json.dumps({"gemini_api_key": "DUMMY", "deepseek_api_key": "DUMMY", "os_system": "linux"}))
    try:
        sys.path.insert(0, str(ROOT))
        import ui
        from PyQt6.QtWidgets import QApplication
        jui = ui.JarvisUI("")
        w = jui._win
        for _ in range(5):
            QApplication.processEvents()
        w._home._pick("deepseek")
        assert json.loads(cfg.read_text()).get("active_provider") in (None, "gemini")
        assert w.grab().width() > 900
    finally:
        from core.tasks import TASKS
        TASKS.on_change = None          # the window is going away
        cfg.unlink(missing_ok=True)
