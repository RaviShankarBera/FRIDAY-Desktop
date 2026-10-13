"""Knowledge base tools: add a document to FRIDAY's local knowledge, or search it."""
from __future__ import annotations


def knowledge_add(parameters: dict, player=None) -> str:
    from core.rag import KnowledgeBase
    path = str((parameters or {}).get("path", "")).strip()
    text = str((parameters or {}).get("text", "")).strip()
    name = str((parameters or {}).get("name", "")).strip() or "note"
    kb = KnowledgeBase()
    try:
        n = kb.add_file(path) if path else kb.add_text(name, text)
    except Exception as e:                          # noqa: BLE001
        return f"Sorry, I could not add that: {e}"
    return f"Added to the knowledge base ({n} passages). It stays on this computer." if n else "Nothing to add."


TOOL = {
    "name": "knowledge_add",
    "description": "Add a file (path) or some text to FRIDAY's private local knowledge base so it can be searched later.",
    "parameters": {"type": "OBJECT", "properties": {
        "path": {"type": "STRING", "description": "File path (txt, md, csv, json, code, pdf)."},
        "text": {"type": "STRING", "description": "Plain text to remember instead of a file."},
        "name": {"type": "STRING", "description": "Name for pasted text."}}},
    "handler": knowledge_add,
}
