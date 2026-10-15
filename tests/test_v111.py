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


def test_flight_url_has_no_hardcoded_route():
    from actions.flight_finder import _build_google_flights_url
    u = _build_google_flights_url("Bengaluru", "Kolkata", "2026-11-02")
    assert "tfs=" not in u and "LHR" not in u and "Kolkata" in u


def test_flight_slots_carry_across_turns(monkeypatch):
    from actions import flight_finder as ff
    ff._SLOTS.update(t=0.0, v={})
    r1 = ff.flight_finder({"origin": "Bengaluru", "destination": "Kolkata"})
    assert r1.startswith("[NEED_INFO]")
    r2 = ff.flight_finder({"date": "2099-01-05"})          # model forgets origin/destination
    assert r2.startswith("[NEED_INFO]") and "where from" not in r2 and "date" not in r2
    assert ff._SLOTS["v"]["destination"] == "Kolkata"
    r3 = ff.flight_finder({"destination": "Mumbai"})       # a new statement overrides
    assert ff._SLOTS["v"]["destination"] == "Mumbai" and ff._SLOTS["v"]["origin"] == "Bengaluru"


def test_no_gendered_honorifics_and_send_needs_platform():
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parent.parent
    bad = [str(p) for p in list((root / "actions").glob("*.py")) if re.search(r"\bsir\b", p.read_text(), re.I)]
    assert not bad, bad
    from actions.send_message import send_message
    assert send_message({"receiver": "A", "message_text": "hi"}).startswith("[NEED_INFO]")


def test_download_file(tmp_path, monkeypatch):
    from actions import download_file as d
    assert d.download_file({}).startswith("[NEED_INFO]")
    assert "private" in d.download_file({"url": "http://127.0.0.1/x.zip"})
    assert "http" in d.download_file({"url": "ftp://x/y"})
    assert d._filename("http://a/b/report.pdf?x=1", {}) == "report.pdf"
    assert d._filename("http://a/dl", {"content-disposition": 'attachment; filename="a b.zip"'}) == "a b.zip"
    (tmp_path / "f.txt").write_text("x")
    assert d._unique(tmp_path / "f.txt").name == "f (1).txt"
    import http.server, threading, functools
    (tmp_path / "srv").mkdir(); (tmp_path / "srv" / "hello.txt").write_text("hi there")
    monkeypatch.setattr(d, "_safe_host", lambda u: (True, ""))
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path / "srv"))
    srv = http.server.HTTPServer(("127.0.0.1", 0), h); threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = d.download_file({"url": f"http://127.0.0.1:{srv.server_port}/hello.txt", "folder": str(tmp_path / "out")})
    finally:
        srv.shutdown()
    assert r.startswith("Downloaded hello.txt") and (tmp_path / "out" / "hello.txt").read_text() == "hi there"


def test_official_installer_pick():
    from actions.download_file import pick_installer, resolve_official, download_file
    html = ('<a href="https://evil-downloads.com/claude.exe">x</a>'
            '<a href="https://downloads.claude.ai/releases/Claude-arm64.exe">arm</a>'
            '<a href="https://downloads.claude.ai/releases/Claude-x64.exe">x64</a>'
            '<a href="/mac/Claude.dmg">m</a>')
    doms = ("claude.ai", "claude.com")
    assert pick_installer(html, "https://claude.com/download", doms, "AMD64").endswith("Claude-x64.exe")
    assert pick_installer(html, "https://claude.com/download", doms, "ARM64").endswith("Claude-arm64.exe")
    assert pick_installer('<a href="https://evil.com/a.exe">', "https://claude.com/download", doms) is None
    assert resolve_official("Totally Unknown App") == (None, None, ())
    assert "official" in download_file({"app": "Totally Unknown App"})


def test_installer_pick_skips_other_products():
    from actions.download_file import pick_installer
    h = '<a href="https://downloads.claude.ai/claude-science/latest/windows-x64.exe">s</a>'
    assert pick_installer(h, "https://claude.com/download", ("claude.ai",)) is None


def test_readback_gate():
    from core import interactive as i
    i.reset()
    r = i.gate("send_message", "Sending WhatsApp message to Ana: 'hi'", None, now=100.0)
    assert r.startswith("[CONFIRM]")
    assert i.gate("send_message", "Sending WhatsApp message to Ana: 'hi'", "true", now=101.0) is None
    assert i.gate("send_message", "Sending WhatsApp message to Ana: 'hi'", "true", now=102.0).startswith("[CONFIRM]")  # one use only
    i.gate("send_message", "Sending to Bo: 'x'", None, now=200.0)
    assert i.gate("send_message", "Sending to Bo: 'CHANGED'", "true", now=201.0).startswith("[CONFIRM]")
    i.gate("send_message", "Sending to Bo: 'x'", None, now=300.0)
    assert i.gate("send_message", "Sending to Bo: 'x'", "true", now=300.0 + 500).startswith("[CONFIRM]")   # expired


def test_send_and_file_ops_need_readback(tmp_path):
    from core import interactive as i
    i.reset()
    from actions.send_message import send_message
    r = send_message({"receiver": "Ana", "message_text": "hi", "platform": "WhatsApp", "confirmed": "true"})
    assert r.startswith("[CONFIRM]")              # confirmed=true up front is not honoured
    from actions.file_controller import file_controller
    f = tmp_path / "a.txt"; f.write_text("x")
    assert file_controller({"action": "delete", "path": str(tmp_path), "name": "a.txt"}).startswith("[CONFIRM]")
    assert f.exists()
    assert not file_controller({"action": "list", "path": str(tmp_path)}).startswith("[CONFIRM]")


def test_download_detects_this_pc(monkeypatch):
    from actions import download_file as d
    assert d.detect_target()[0] in ("Windows", "macOS", "Linux")
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda u: opened.append(u))
    said = []
    r = d.download_file({"app": "VLC", "os": "macOS"}, speak=said.append)
    assert "Downloading VLC for macOS" in said[0] and opened and "nothing" in r
