import pytest
from core import offline_commands as O
from core import voice_fallback as V
from core.providers import QuotaExhausted


@pytest.mark.parametrize("said,name,args", [
    ("open chrome", "open_app", {"app_name": "chrome"}),
    ("Open VS Code.", "open_app", {"app_name": "VS Code"}),
    ("work mode", "work_mode", {"mode": "work"}),
    ("start gaming mode", "work_mode", {"mode": "gaming"}),
    ("timer 25 minutes", "pc_control", {"action": "timer", "value": "25 minutes"}),
    ("set a timer for 10 minutes", "pc_control", {"action": "timer", "value": "10 minutes"}),
    ("volume 40", "pc_control", {"action": "volume", "value": "40"}),
    ("set brightness to 70%", "pc_control", {"action": "brightness", "value": "70"}),
    ("take a screenshot", "pc_control", {"action": "screenshot"}),
    ("close spotify", "pc_control", {"action": "close_app", "value": "spotify"}),
    ("find the resume file", "pc_control", {"action": "find_file", "value": "resume"}),
])
def test_matches(said, name, args):
    assert O.match(said) == {"name": name, "args": args}


@pytest.mark.parametrize("said", ["", "what is the weather", "tell me a joke", "openly discuss"])
def test_no_wild_guesses(said):
    assert O.match(said) is None


class Dead:
    def chat(self, m): raise QuotaExhausted("Sorry, every free model is out of quota.")


def test_fallback_brain_runs_basic_command_when_all_models_dead():
    ran = []
    b = V.FallbackBrain(Dead(), "sys", [], lambda n, a: ran.append((n, a)) or "Timer set.", lambda m: None)
    assert b.reply("timer 5 minutes") == "Timer set."
    assert ran == [("pc_control", {"action": "timer", "value": "5 minutes"})]


def test_fallback_brain_explains_when_nothing_matches():
    b = V.FallbackBrain(Dead(), "sys", [], lambda n, a: "x", lambda m: None)
    out = b.reply("write me a poem")
    assert "out of quota" in out and "basic commands offline" in out
