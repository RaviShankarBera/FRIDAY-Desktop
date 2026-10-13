"""Search FRIDAY's local knowledge base."""
from __future__ import annotations


def knowledge_search(parameters: dict, player=None) -> str:
    from core.rag import KnowledgeBase
    q = str((parameters or {}).get("query", "")).strip()
    if not q:
        return "Please tell me what to search for."
    kb = KnowledgeBase()
    if not kb.sources():
        return "The knowledge base is empty. Ask me to add a document first."
    hits = kb.search(q, k=4)
    if not hits:
        return "No results found in the knowledge base."
    return "\n\n".join(f"[{h['source']}] {h['text'][:400]}" for h in hits)


TOOL = {
    "name": "knowledge_search",
    "description": "Search the user's private local knowledge base (documents they added) and return the best passages.",
    "parameters": {"type": "OBJECT", "properties": {
        "query": {"type": "STRING", "description": "What to look for."}}, "required": ["query"]},
    "handler": knowledge_search,
}
