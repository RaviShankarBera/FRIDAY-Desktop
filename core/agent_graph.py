"""
FRIDAY multi-step agent (LangGraph).

plan -> run each step (shown on the task dashboard) -> summarise.
Tools are injected, so tests run with fakes and the real app wires in
knowledge search, web search and plain reasoning. All model calls go through
core.providers.Router (free-only fallback).
"""
from __future__ import annotations

import json
import re
from typing import Callable, TypedDict

from langgraph.graph import StateGraph, END

from core.providers import QuotaExhausted
from core.tasks import TASKS

MAX_STEPS = 5


class AgentState(TypedDict, total=False):
    goal: str
    steps: list[dict]
    idx: int
    results: list[str]
    answer: str
    error: str


def _parse_plan(text: str, allowed: set[str]) -> list[dict]:
    m = re.search(r"\[.*\]", text or "", re.S)
    steps: list[dict] = []
    if m:
        try:
            for s in json.loads(m.group(0)):
                if isinstance(s, dict) and s.get("tool") in allowed and str(s.get("input", "")).strip():
                    steps.append({"tool": s["tool"], "input": str(s["input"]).strip()})
        except Exception:
            steps = []
    return steps[:MAX_STEPS]


def build_agent(router, tools: dict[str, Callable[[str], str]]):
    """Returns a compiled graph. router needs .chat(messages)->str."""
    allowed = set(tools) | {"think"}

    def plan(state: AgentState) -> AgentState:
        sysmsg = ("You plan tasks for FRIDAY. Reply with ONLY a JSON array of at most "
                  f"{MAX_STEPS} steps, each {{\"tool\": <one of {sorted(allowed)}>, \"input\": <text>}}. "
                  "Use knowledge_search for the user's own documents, web_search for the web, "
                  "think for reasoning. Fewest steps that work.")
        t = TASKS.start("plan", state["goal"][:50])
        try:
            raw = router.chat([{"role": "system", "content": sysmsg},
                               {"role": "user", "content": state["goal"]}])
            steps = _parse_plan(raw, allowed) or [{"tool": "think", "input": state["goal"]}]
            TASKS.finish(t, True, f"{len(steps)} steps")
        except QuotaExhausted as e:
            TASKS.finish(t, False, "out of quota")
            return {"error": str(e), "steps": [], "idx": 0, "results": []}
        return {"steps": steps, "idx": 0, "results": []}

    def run_step(state: AgentState) -> AgentState:
        i = state["idx"]; step = state["steps"][i]
        t = TASKS.start(f"step {i + 1}/{len(state['steps'])}: {step['tool']}", step["input"][:50])
        ok = True
        try:
            if step["tool"] == "think":
                ctx = "\n".join(state["results"])
                out = router.chat([{"role": "system", "content": "Answer briefly and factually."},
                                   {"role": "user", "content": f"{step['input']}\n\nContext so far:\n{ctx}"}])
            else:
                out = tools[step["tool"]](step["input"])
        except QuotaExhausted as e:
            TASKS.finish(t, False, "out of quota")
            return {"error": str(e), "idx": len(state["steps"])}
        except Exception as e:                      # noqa: BLE001
            ok = False
            out = f"Step failed: {e}"
        TASKS.finish(t, ok, "" if ok else out[:80])
        return {"results": state["results"] + [f"[{step['tool']}] {out}"], "idx": i + 1}

    def summarize(state: AgentState) -> AgentState:
        if state.get("error"):
            return {"answer": state["error"]}
        t = TASKS.start("summarise", state["goal"][:50])
        try:
            ans = router.chat([
                {"role": "system", "content": "You are FRIDAY. Give the user a short spoken-style answer "
                                              "based on the step results. If a step failed, say sorry and what failed."},
                {"role": "user", "content": f"Goal: {state['goal']}\n\nResults:\n" + "\n".join(state["results"])}])
            TASKS.finish(t, True)
        except QuotaExhausted as e:
            TASKS.finish(t, False, "out of quota")
            return {"answer": str(e)}
        return {"answer": ans}

    def more(state: AgentState) -> str:
        return "run_step" if state.get("idx", 0) < len(state.get("steps", [])) else "summarize"

    g = StateGraph(AgentState)
    g.add_node("plan", plan)
    g.add_node("run_step", run_step)
    g.add_node("summarize", summarize)
    g.set_entry_point("plan")
    g.add_conditional_edges("plan", more, {"run_step": "run_step", "summarize": "summarize"})
    g.add_conditional_edges("run_step", more, {"run_step": "run_step", "summarize": "summarize"})
    g.add_edge("summarize", END)
    return g.compile()


def run_agent(goal: str, router, tools: dict[str, Callable[[str], str]]) -> str:
    graph = build_agent(router, tools)
    final = graph.invoke({"goal": goal})
    return final.get("answer") or final.get("error") or "Sorry, I could not finish that."
