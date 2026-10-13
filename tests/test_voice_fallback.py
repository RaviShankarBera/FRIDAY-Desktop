import json
import pytest
from core.providers import QuotaExhausted, Router
from core import voice_fallback as vf


class FakeRouter:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def chat(self, messages):
        self.calls.append(messages)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


DECLS = [{"name": "web_search", "description": "Search the web", "parameters": {"properties": {"query": {}}}}]


def brain(replies, tool=lambda n, a: "ok"):
    logs = []
    return vf.FallbackBrain(FakeRouter(replies), "SYS", DECLS, tool, logs.append), logs


def test_prefix_required():
    assert vf.strip_prefix("what time is it") is None
    assert vf.strip_prefix("Friday, what time is it") == "what time is it"
    assert vf.strip_prefix("hey friday open notepad") == "open notepad"
    assert vf.strip_prefix("Friday") == ""
    assert vf.strip_prefix("fridays are fun") is None
    assert vf.strip_prefix("फ्राइडे मुझे समय बताओ") == "मुझे समय बताओ"


def test_parse_tool_call():
    assert vf.parse_tool_call('TOOL: {"name":"web_search","args":{"query":"x"}}') == {"name": "web_search", "args": {"query": "x"}}
    assert vf.parse_tool_call("just talk") is None
    assert vf.parse_tool_call("TOOL: {bad") is None


def test_voice_picks_hindi_for_devanagari():
    assert vf.pick_voice("hello") == "en-IN-NeerjaNeural"
    assert vf.pick_voice("नमस्ते") == "hi-IN-SwaraNeural"


def test_plain_reply_and_history():
    b, _ = brain(["It is noon."])
    assert b.reply("time?") == "It is noon."
    assert b.history[-1]["role"] == "assistant"


def test_tool_loop_runs_once_then_answers():
    seen = []
    b, logs = brain(['TOOL: {"name":"web_search","args":{"query":"rain"}}', "I opened the results."],
                    tool=lambda n, a: seen.append((n, a)) or "opened")
    assert b.reply("search rain") == "I opened the results."
    assert seen == [("web_search", {"query": "rain"})]
    assert any("web_search" in l for l in logs)


def test_tool_loop_is_bounded():
    call = 'TOOL: {"name":"web_search","args":{}}'
    b, _ = brain([call] * 5)
    assert b.reply("x").startswith("Sorry")


def test_tool_error_is_passed_back_not_raised():
    def boom(n, a):
        raise RuntimeError("nope")
    b, _ = brain(['TOOL: {"name":"web_search","args":{}}', "Sorry, search failed."], tool=boom)
    assert b.reply("x").startswith("Sorry")


def test_quota_exhausted_message_is_spoken():
    b, _ = brain([QuotaExhausted("Sorry, every free model is out of quota.")])
    assert "out of quota" in b.reply("hi")


def test_router_never_uses_paid_in_fallback():
    cfg = {"gemini_api_key": "g", "deepseek_api_key": "d", "openai_api_key": "o", "allow_paid": False}
    called = []

    def quota(_m):
        from core.providers import QuotaError
        called.append("free")
        raise QuotaError("q")

    def paid(_m):
        called.append("PAID")
        return "x"
    r = Router(cfg, callers={"gemini": quota, "nvidia": quota, "deepseek": paid, "openai": paid})
    with pytest.raises(QuotaExhausted):
        r.chat([{"role": "user", "content": "hi"}])
    assert "PAID" not in called


class FakeSTT:
    def __init__(self, items):
        self.items = list(items)

    def process_chunk(self, pcm):
        return self.items.pop(0)


def test_voice_ignores_unprefixed_and_speaks_prefixed():
    spoken, logs = [], []
    b, _ = brain(["Hello there."])
    v = vf.FallbackVoice(FakeSTT([("", False), ("what is going on", True), ("friday hello", True)]),
                         b, spoken.append, logs.append)
    assert v.on_pcm(b"x") is None
    assert v.on_pcm(b"x") is None and spoken == []
    assert v.on_pcm(b"x") == "Hello there."
    assert spoken == ["Hello there."]
    assert any(l.startswith("FRIDAY:") for l in logs)


def test_tts_failure_keeps_text_and_logs_sorry():
    logs = []
    b, _ = brain(["Hi."])

    def bad(_t):
        raise RuntimeError("no audio")
    v = vf.FallbackVoice(FakeSTT([("friday hi", True)]), b, bad, logs.append)
    assert v.on_pcm(b"x") == "Hi."
    assert any(l.startswith("SORRY") for l in logs)


def test_bare_friday_answers_yes():
    spoken = []
    b, _ = brain([])
    v = vf.FallbackVoice(FakeSTT([("friday", True)]), b, spoken.append, lambda m: None)
    assert "listening" in v.on_pcm(b"x")


def test_bilingual_stt_prefers_prefixed_higher_confidence(monkeypatch):
    class Rec:
        def __init__(self, text, conf):
            self.text, self.conf = text, conf
        def AcceptWaveform(self, _):
            return True
        def Result(self):
            return json.dumps({"text": self.text, "result": [{"conf": self.conf}]})
        FinalResult = Result
    st = object.__new__(vf.BilingualSTT)
    st.recs = [("en", Rec("friday which has some", 0.7)), ("hi", Rec("फ्राइडे मुझे समय बताओ", 0.99))]
    assert st.process_chunk(b"x") == ("फ्राइडे मुझे समय बताओ", True)
    st.recs = [("en", Rec("friday what time is it", 0.95)), ("hi", Rec("गलत बात", 0.99))]
    assert st.process_chunk(b"x") == ("friday what time is it", True)


def test_models_ensure_downloads_once_and_never_raises(tmp_path, monkeypatch):
    import zipfile
    from core import models
    monkeypatch.setattr(models, "MODELS_DIR", tmp_path)
    name = models.MODELS["hi"][0]

    def fake_get(url, dest):
        assert url.endswith(name + ".zip")
        with zipfile.ZipFile(dest, "w") as z:
            z.writestr(f"{name}/am/final.mdl", "x"); z.writestr(f"{name}/conf/model.conf", "x")
    monkeypatch.setattr(models.urllib.request, "urlretrieve", fake_get)
    logs = []
    assert models.ensure("hi", logs.append) == (True, "ready") and models.present("hi")
    monkeypatch.setattr(models.urllib.request, "urlretrieve", lambda *a: (_ for _ in ()).throw(AssertionError("again")))
    assert models.ensure("hi")[0] is True          # already present, no second download
    monkeypatch.setattr(models, "MODELS_DIR", tmp_path / "empty")
    monkeypatch.setattr(models.urllib.request, "urlretrieve", lambda *a: (_ for _ in ()).throw(OSError("offline")))
    ok, msg = models.ensure("en")
    assert ok is False and "offline" in msg


def test_system_voice_prefers_female():
    from types import SimpleNamespace as V
    from core.voice_fallback import pick_system_voice
    vs = [V(id="d", name="Microsoft David Desktop"), V(id="z", name="Microsoft Zira Desktop")]
    assert pick_system_voice(vs) == "z"
    assert pick_system_voice([V(id="d", name="Microsoft David Desktop")]) is None
    assert pick_system_voice([V(id="x", name="Voice", gender="female")]) == "x"


def test_default_live_voice_is_female():
    from memory import config_manager as c
    assert c.DEFAULT_VOICE == "Kore" and set(c.AVAILABLE_VOICES) == {"Kore", "Aoede"}
    assert "Charon" not in c.AVAILABLE_VOICES


def test_edge_voices_female():
    from core.voice_fallback import EDGE_VOICES
    assert EDGE_VOICES == {"en": "en-IN-NeerjaNeural", "hi": "hi-IN-SwaraNeural"}
