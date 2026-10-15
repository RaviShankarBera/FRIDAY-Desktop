import json, pytest
from core import providers as P

KEYS = {"gemini_api_key": "g-key", "nvidia_api_key": "n-key",
        "deepseek_api_key": "d-key", "openai_api_key": "o-key"}


def quota(_m): raise P.QuotaError("429")
def ok(name): return lambda _m: f"from {name}"


def test_paid_never_in_automatic_chain_even_with_keys():
    assert P.automatic_chain(KEYS) == ["gemini", "nvidia"]
    assert P.full_chain(KEYS) == ["gemini", "nvidia"]


def test_active_paid_is_ignored_without_allow_paid():
    cfg = {**KEYS, "active_provider": "deepseek"}
    assert "deepseek" not in P.full_chain(cfg)
    assert P.full_chain(cfg)[0] == "gemini"


def test_paid_only_when_allowed_and_chosen_and_never_a_fallback():
    cfg = {**KEYS, "active_provider": "openai", "allow_paid": True}
    assert P.full_chain(cfg)[0] == "openai"
    cfg2 = {**KEYS, "active_provider": "gemini", "allow_paid": True}
    assert P.full_chain(cfg2) == ["gemini", "nvidia"]      # paid still not a fallback


def test_fallback_gemini_to_nvidia_with_notice():
    seen = []
    r = P.Router(KEYS, {"gemini": quota, "nvidia": ok("nvidia")}, notify=seen.append)
    assert r.chat([{"role": "user", "content": "hi"}]) == "from nvidia"
    assert "switched to NVIDIA" in seen[0]


def test_all_free_exhausted_stops_and_never_calls_paid():
    called = []
    def paid(_m): called.append(1); return "paid!"
    r = P.Router(KEYS, {"gemini": quota, "nvidia": quota, "deepseek": paid, "openai": paid})
    with pytest.raises(P.QuotaExhausted) as e:
        r.chat([{"role": "user", "content": "hi"}])
    assert not called
    assert "out of quota" in str(e.value) and "paid" in str(e.value)


def test_placeholder_key_is_not_a_key():
    assert not P.has_key({"gemini_api_key": "PASTE_YOUR_GEMINI_KEY_HERE"}, "gemini")
    with pytest.raises(P.QuotaExhausted):
        P.Router({"gemini_api_key": "PASTE_YOUR_GEMINI_KEY_HERE"}).chat([])


def test_switch_rules(tmp_path):
    p = tmp_path / "k.json"; p.write_text(json.dumps(KEYS))
    assert P.set_active("nvidia", p).startswith("Switched")
    assert json.loads(p.read_text())["active_provider"] == "nvidia"
    assert "free-only" in P.set_active("deepseek", p)
    assert "no key" in P.set_active("nvidia", tmp_path / "none.json")
    assert json.loads(p.read_text())["active_provider"] == "nvidia"


def test_status_labels():
    st = P.status({**KEYS, "active_provider": "nvidia"})
    assert st == {"gemini": "connected", "nvidia": "active", "ollama": "not-linked",
                  "deepseek": "paid-off", "openai": "paid-off"}


def test_ollama_is_last_free_fallback_when_running(monkeypatch):
    monkeypatch.setattr(P, "ollama_up", lambda *a, **k: True)
    assert P.automatic_chain(KEYS) == ["gemini", "nvidia", "ollama"]
    seen = []
    r = P.Router(KEYS, {"gemini": quota, "nvidia": quota, "ollama": ok("ollama")}, notify=seen.append)
    assert r.chat([{"role": "user", "content": "hi"}]) == "from ollama"
    assert "switched to Local Ollama" in seen[0]


def test_ollama_alone_works_without_any_key(monkeypatch):
    monkeypatch.setattr(P, "ollama_up", lambda *a, **k: True)
    r = P.Router({}, {"ollama": ok("ollama")})
    assert r.chat([]) == "from ollama"


def test_ollama_not_running_is_skipped_and_can_be_disabled(monkeypatch):
    monkeypatch.setattr(P, "ollama_up", lambda *a, **k: False)
    assert "ollama" not in P.automatic_chain(KEYS)
    monkeypatch.setattr(P, "ollama_up", lambda *a, **k: True)
    assert "ollama" not in P.automatic_chain({**KEYS, "ollama_enabled": False})


def test_call_ollama_parses_response_and_maps_errors(monkeypatch):
    import requests
    class R:
        def __init__(s, code, js): s.status_code, s._j = code, js
        def json(s): return s._j
    monkeypatch.setattr(requests, "post", lambda *a, **k: R(200, {"message": {"content": " hi "}}))
    assert P.call_ollama([], "m", "http://x") == "hi"
    monkeypatch.setattr(requests, "post", lambda *a, **k: R(404, {}))
    with pytest.raises(P.ProviderError):
        P.call_ollama([], "m", "http://x")
    def down(*a, **k): raise requests.ConnectionError("refused")
    monkeypatch.setattr(requests, "post", down)
    with pytest.raises(P.ProviderError):
        P.call_ollama([], "m", "http://x")


def test_switch_to_ollama_when_down_gives_install_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "ollama_up", lambda *a, **k: False)
    assert "ollama pull" in P.set_active("local", tmp_path / "k.json")
