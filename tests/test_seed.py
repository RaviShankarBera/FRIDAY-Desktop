import re
from core.rag import KnowledgeBase, HashEmbedder
from core import seed
from core.seed import import_seed, TEMPLATE_DIR, LOCAL_DIR, BRIEFING_PROMPT


def test_template_loads_once_and_answers(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb", embedder=HashEmbedder())
    st = tmp_path / "s.json"
    first = import_seed(kb, TEMPLATE_DIR, st)
    assert len(first) >= 5
    assert import_seed(kb, TEMPLATE_DIR, st) == []
    assert any("MORNING BRIEF" in h["text"] for h in kb.search("morning brief top 10 India news", k=2))


def test_private_folder_wins_when_present(tmp_path, monkeypatch):
    local = tmp_path / "knowledge_seed.local"; local.mkdir()
    (local / "01-about-me.md").write_text("Name: Test Person", encoding="utf-8")
    monkeypatch.setattr(seed, "LOCAL_DIR", local)
    assert seed._pick_dir() == local
    monkeypatch.setattr(seed, "LOCAL_DIR", tmp_path / "missing")
    assert seed._pick_dir() == TEMPLATE_DIR


def test_public_template_has_no_personal_data():
    blob = "\n".join(p.read_text(encoding="utf-8") for p in TEMPLATE_DIR.glob("*.md"))
    assert not re.search(r"AIza[0-9A-Za-z_-]{20}|sk-[A-Za-z0-9]{20}|password\s*[:=]", blob, re.I)
    assert "@" not in blob.replace("@", "", 0) or "@gmail" not in blob
    for word in ("kg", "kcal", "weight", "stacknity", "nagarro", "gyansys", "hexaware", "offer", "salary", "ravi"):
        assert word not in blob.lower(), word


def test_local_folder_is_gitignored():
    from pathlib import Path
    gi = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert "knowledge_seed.local/" in gi


def test_briefing_prompt_points_at_spec():
    assert "MORNING BRIEF spec" in BRIEFING_PROMPT and "10 India" in BRIEFING_PROMPT
