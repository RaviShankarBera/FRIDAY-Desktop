"""Loads personal knowledge (knowledge_seed.local/*.md if present, else the template knowledge_seed/*.md) into the Knowledge Base.

Runs at start. Each file is imported once, and again only when the file in
knowledge_seed/ itself changes. Edit those files to update what FRIDAY knows.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
LOCAL_DIR = _ROOT / "knowledge_seed.local"   # private, gitignored, never uploaded
TEMPLATE_DIR = _ROOT / "knowledge_seed"      # generic template shipped in the repo


def _pick_dir() -> Path:
    """Your private folder wins when it has files; otherwise the shipped template."""
    if LOCAL_DIR.is_dir() and any(LOCAL_DIR.glob("*.md")):
        return LOCAL_DIR
    return TEMPLATE_DIR


SEED_DIR = _pick_dir()
STATE = Path(__file__).resolve().parent.parent / "config" / "seed_state.local.json"


def import_seed(kb=None, seed_dir: Path | None = None, state: Path | None = None) -> list[str]:
    seed_dir, state = Path(seed_dir or _pick_dir()), Path(state or STATE)
    if not seed_dir.is_dir():
        return []
    if kb is None:
        from core.rag import KnowledgeBase
        kb = KnowledgeBase()
    try:
        done = json.loads(state.read_text(encoding="utf-8"))
    except Exception:
        done = {}
    added = []
    for f in sorted(seed_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
        if done.get(f.name) == digest:
            continue
        if kb.add_text(f.name, text):
            done[f.name] = digest
            added.append(f.name)
    if added:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(done, indent=2), encoding="utf-8")
    return added


BRIEFING_PROMPT = ("Friday, give me my morning briefing. First search the knowledge base for "
                   "'MORNING BRIEF spec' and follow it exactly: most important email with a "
                   "suggested reply, LinkedIn urgent messages, who was wished and the engagement "
                   "tally, then top 10 India news and 5 international news from a live search. "
                   "Say plainly which parts you cannot reach.")
