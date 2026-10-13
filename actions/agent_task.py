"""agent_task: multi-step tasks (plan -> steps -> answer), with every step on the task dashboard."""
from __future__ import annotations

from core.providers import Router, QuotaExhausted


def _tools(player=None):
    tools = {}

    def knowledge_search(q: str) -> str:
        from core.rag import KnowledgeBase
        hits = KnowledgeBase().search(q, k=4)
        return "\n".join(f"({h['source']}) {h['text'][:300]}" for h in hits) or "Nothing in the knowledge base matches."
    tools["knowledge_search"] = knowledge_search

    def web_search(q: str) -> str:
        from actions.web_search import web_search as ws
        return ws(parameters={"query": q, "mode": "search"}, player=player)
    tools["web_search"] = web_search
    return tools


def agent_task(parameters: dict, player=None) -> str:
    goal = str((parameters or {}).get("goal", "")).strip()
    if not goal:
        return "Please provide the goal for the task."
    from core.agent_graph import run_agent
    log = (lambda m: player.write_log(f"SYS: {m}")) if player else (lambda m: None)
    try:
        return run_agent(goal, Router(notify=log), _tools(player))
    except QuotaExhausted as e:
        return str(e)


TOOL = {
    "name": "agent_task",
    "description": ("Run a complex multi-step task: it plans the steps, runs them (knowledge search, web "
                    "search, reasoning) and reports. Use only for genuinely multi-step requests."),
    "parameters": {"type": "OBJECT", "properties": {
        "goal": {"type": "STRING", "description": "The full goal in plain words."}}, "required": ["goal"]},
    "handler": agent_task,
}
