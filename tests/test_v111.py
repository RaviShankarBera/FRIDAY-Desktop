import pytest
from actions import flight_finder as F, web_search as W


def call(**kw): return F.flight_finder(kw)


def test_flight_asks_first_when_only_route_given(monkeypatch):
    monkeypatch.setattr(F, "_search_flights_browser", lambda *a: pytest.fail("must not search"))
    out = call(origin="Bengaluru", destination="Kolkata", date="", trip_type="", passengers=None)
    assert out.startswith("[NEED_INFO]") and "departure date" in out and "one-way or round trip" in out and "travelers" in out


def test_flight_roundtrip_needs_return_date(monkeypatch):
    monkeypatch.setattr(F, "_search_flights_browser", lambda *a: pytest.fail("must not search"))
    out = call(origin="BLR", destination="CCU", date="2099-01-10", trip_type="roundtrip", passengers=1)
    assert "return date" in out and "NEED_INFO" in out


def test_flight_past_date_rejected(monkeypatch):
    monkeypatch.setattr(F, "_search_flights_browser", lambda *a: pytest.fail("must not search"))
    assert "NEED_INFO" in call(origin="BLR", destination="CCU", date="2020-01-10", trip_type="oneway", passengers=1)


def test_flight_searches_when_complete(monkeypatch):
    seen = {}
    monkeypatch.setattr(F, "_search_flights_browser", lambda *a: (seen.setdefault("a", a) and "text", "http://u"))
    monkeypatch.setattr(F, "_parse_flights_with_gemini", lambda *a: [])
    monkeypatch.setattr(F, "_format_spoken", lambda *a: "ok flights")
    out = call(origin="BLR", destination="CCU", date="2099-01-10", trip_type="oneway", passengers=2, return_date="2099-01-12")
    assert out == "ok flights" and seen["a"][3] is None and seen["a"][4] == 2   # one-way drops return date


def test_flight_tool_requires_slots():
    assert {"trip_type", "passengers", "date"} <= set(F.TOOL["parameters"]["required"])


# ---- news
RSS = "<rss><channel>" + "".join(f"<item><title>Headline {i} about AI - Src</title><source>Src</source><link>http://x/{i}</link></item>" for i in range(1, 9)) + "</channel></rss>"


def test_news_falls_back_to_rss_when_gemini_and_ddg_fail(monkeypatch):
    import requests
    def bad(*a, **k): raise RuntimeError("down")
    monkeypatch.setattr(W, "_gemini_search", bad)
    monkeypatch.setattr(W, "_ddg_news", bad)
    class R:
        text = RSS
        def raise_for_status(self): pass
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    monkeypatch.setattr(W, "_open_google", lambda *a, **k: True)
    out = W.web_search({"query": "top 5 AI news today", "mode": "search"})
    assert "1. Headline 1 about AI" in out and "5. Headline 5" in out and "6. Headline 6" not in out


def test_news_total_failure_message_names_sources(monkeypatch):
    import requests
    def bad(*a, **k): raise RuntimeError("down")
    monkeypatch.setattr(W, "_gemini_search", bad); monkeypatch.setattr(W, "_ddg_news", bad)
    monkeypatch.setattr(requests, "get", bad)
    monkeypatch.setattr(W, "_open_google", lambda *a, **k: True)
    out = W.web_search({"query": "ai news", "mode": "news"})
    assert out.startswith("Sorry") and "Gemini, DuckDuckGo and Google News" in out


def test_plain_search_falls_back_to_rss(monkeypatch):
    import requests
    def bad(*a, **k): raise RuntimeError("down")
    monkeypatch.setattr(W, "_gemini_search", bad); monkeypatch.setattr(W, "_ddg_search", bad)
    class R:
        text = RSS
        def raise_for_status(self): pass
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    assert "Headline 1" in W._search("ai")


def test_every_action_file_loads():
    """Regression: flight_finder, youtube_video and game_updater silently failed to import
    (config helpers were missing), so the model fell back to bare web searches."""
    from pathlib import Path
    from core.action_loader import discover_actions
    names = discover_actions(Path(__file__).resolve().parent.parent / "actions", set(), lambda m: None).names()
    assert {"flight_finder", "youtube_video", "game_updater"} <= names


def test_app_match_and_bargein():
    from core.app_match import resolve
    from core.wake_word import WakeWordDetector
    I = ["Claude", "Google Chrome", "Visual Studio Code", "Cloudflare WARP"]
    assert resolve("Cloud desktop app", I)[:2] == ("launch", "Claude")
    assert resolve("chrome", I)[:2] == ("launch", "Google Chrome")
    assert resolve("Photoshop", I)[0] == "none"
    assert resolve("cloud", ["Cloudflare WARP"])[0] == "confirm"
    d = WakeWordDetector(lambda: None)
    assert not d._heard("stop") and d._heard("friday")
    d.accept_stop = True
    assert d._heard("please stop")
