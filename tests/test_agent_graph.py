import json
from core import providers as P
from core.agent_graph import run_agent, _parse_plan
from core.tasks import TASKS


class FakeRouter:
    def __init__(self, plan, fail_on=None):
        self.plan, self.calls, self.fail_on = plan, [], fail_on
    def chat(self, messages):
        self.calls.append(messages[0]["content"][:12])
        if self.fail_on and self.fail_on in messages[0]["content"]:
            raise P.QuotaExhausted("Sorry, out of quota. I stopped.")
        if "plan tasks" in messages[0]["content"]:
            return "Plan: " + json.dumps(self.plan)
        if "FRIDAY" in messages[0]["content"]:
            return "Final answer."
        return "thought"


def test_parse_plan_filters_bad_tools():
    p = _parse_plan('x [{"tool":"rm_rf","input":"a"},{"tool":"think","input":"b"}]', {"think"})
    assert p == [{"tool": "think", "input": "b"}]
    assert _parse_plan("nonsense", {"think"}) == []


def test_runs_steps_and_updates_dashboard():
    before = len(TASKS.snapshot())
    r = FakeRouter([{"tool": "knowledge_search", "input": "chai"}, {"tool": "web_search", "input": "chai"}])
    out = run_agent("make chai", r, {"knowledge_search": lambda q: "doc says boil", "web_search": lambda q: "web"})
    assert out == "Final answer."
    names = [t["name"] for t in TASKS.snapshot()[before:]]
    assert "plan" in names and any(n.startswith("step 1/2") for n in names) and "summarise" in names
    assert all(t["status"] == "DONE" for t in TASKS.snapshot()[before:])


def test_failing_step_is_marked_failed_and_reported():
    before = len(TASKS.snapshot())
    def boom(q): raise RuntimeError("net down")
    out = run_agent("x", FakeRouter([{"tool": "web_search", "input": "q"}]), {"web_search": boom})
    assert out == "Final answer."
    stat = [t["status"] for t in TASKS.snapshot()[before:] if t["name"].startswith("step")]
    assert stat == ["FAILED"]


def test_quota_stops_with_clear_message():
    out = run_agent("x", FakeRouter([], fail_on="plan tasks"), {})
    assert "out of quota" in out
