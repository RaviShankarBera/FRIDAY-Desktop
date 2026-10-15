import datetime as dt
from pathlib import Path
import pytest
from core import brief, meeting

RSS = """<rss><channel>
<item><title>Rates held steady - Reuters</title><source>Reuters</source><link>http://a</link></item>
<item><title>AI law passes</title><source>BBC</source><link>http://b</link></item>
<item><title></title></item></channel></rss>"""


def test_parse_rss_strips_source_and_skips_empty():
    r = brief.parse_rss(RSS, 5)
    assert [x["title"] for x in r] == ["Rates held steady", "AI law passes"]
    assert r[0]["source"] == "Reuters"
    assert len(brief.parse_rss(RSS, 1)) == 1


NOW = dt.datetime(2026, 10, 16, 8, 0)


def test_brief_full():
    src = {"weather": lambda: "Bengaluru: now 22°C",
           "calendar": lambda: [{"title": "Standup", "start": "2026-10-16T10:30:00+05:30"}],
           "mail": lambda: [{"from": "Acme", "subject": "Invoice"}],
           "news": lambda: ([{"title": "N1"}, {"title": "N2"}], [{"title": "W1"}])}
    t = brief.build_brief(src, NOW)
    assert t.startswith("Good morning. It is Friday, 16 October.")
    assert "Standup at 10:30 AM" in t and "Acme, Invoice" in t and "1. N1. 2. N2." in t and "World. 1. W1." in t
    assert "could not reach" not in t


def test_brief_names_failed_sources_and_never_invents():
    def boom(): raise RuntimeError("Google not connected")
    t = brief.build_brief({"calendar": boom, "mail": boom, "news": lambda: ([{"title": "N1"}], [])}, NOW)
    assert "N1" in t and "could not reach: calendar (Google not connected), mail" in t
    assert "Today you have" not in t and "unread" not in t


def test_brief_empty_calendar_and_mail():
    t = brief.build_brief({"calendar": lambda: [], "mail": lambda: []}, NOW)
    assert "calendar is clear" in t and "No new unread mail" in t


def test_auto_brief_once_per_day(tmp_path):
    p = tmp_path / "s.json"
    cfg = {"morning_brief_auto": True, "brief_hour": 6}
    assert brief.should_auto_brief(cfg, NOW, p)
    assert not brief.should_auto_brief(cfg, NOW.replace(hour=5), p)
    brief.mark_briefed(NOW, p)
    assert not brief.should_auto_brief(cfg, NOW, p)
    assert brief.should_auto_brief(cfg, NOW + dt.timedelta(days=1), p)
    assert not brief.should_auto_brief({}, NOW, tmp_path / "x.json")      # off by default


def test_default_sources_without_google_flags_calendar():
    s = brief.default_sources({})
    assert "news" in s and "weather" not in s and "mail" not in s
    with pytest.raises(RuntimeError):
        s["calendar"]()


# ---- meeting
class FakeStream:
    def __init__(self, cb): self.cb, self.on = cb, False
    def start(self): self.on = True; self.cb(b"\x01\x00" * 16000 * 3, 0, None, None)
    def stop(self): self.on = False
    def close(self): pass


def test_recorder_start_stop():
    r = meeting.Recorder(stream_factory=FakeStream)
    r.start()
    assert r.active and r.seconds() == 3
    with pytest.raises(RuntimeError):
        r.start()
    pcm = r.stop()
    assert len(pcm) == 16000 * 3 * 2 and not r.active
    with pytest.raises(RuntimeError):
        r.stop()


def test_wav_and_split():
    import wave, io
    w = wave.open(io.BytesIO(meeting.wav_bytes(b"\0\0" * 100)))
    assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getnframes() == 100
    pcm = b"\0\0" * (16000 * 20)
    assert [len(c) // 32000 for c in meeting.split_pcm(pcm, 8)] == [8, 8, 4]


def test_process_saves_files_and_chunks(tmp_path):
    pcm = b"\x01\x00" * (16000 * 20)
    meeting.CHUNK_SECONDS = 8
    calls = []
    try:
        res = meeting.process(pcm, NOW, lambda w: calls.append(len(w)) or "hello", lambda t: "SUMMARY: " + t[:5], tmp_path)
    finally:
        meeting.CHUNK_SECONDS = 8 * 60
    assert len(calls) == 1 or len(calls) == 3
    d = Path(res["dir"])
    assert (d / "audio.wav").exists() and (d / "transcript.md").read_text().startswith("hello")
    assert (d / "summary.md").read_text().startswith("SUMMARY: hello")


def test_process_rejects_too_short_and_handles_silence(tmp_path):
    with pytest.raises(ValueError):
        meeting.process(b"\0\0" * 100, NOW, lambda w: "x", lambda t: "s", tmp_path)
    res = meeting.process(b"\0\0" * 16000 * 5, NOW, lambda w: "", lambda t: "s", tmp_path)
    assert "No speech" in res["summary"]


def test_action_flow(monkeypatch, tmp_path):
    from actions import meeting_assistant as ma
    r = meeting.Recorder(stream_factory=FakeStream)
    monkeypatch.setattr(meeting, "_REC", r)
    monkeypatch.setattr(meeting, "MEETINGS_DIR", tmp_path)
    monkeypatch.setattr(meeting, "gemini_transcribe", lambda w: "we agreed to ship Friday")
    monkeypatch.setattr(meeting, "gemini_summarise", lambda t: "ACTION: ship Friday")
    assert "Recording started" in ma.meeting_assistant({"action": "start"})
    assert "Already recording" in ma.meeting_assistant({"action": "start"})
    out = ma.meeting_assistant({"action": "stop"})
    assert "ship Friday" in out and "saved" in out
    assert "not recording" in ma.meeting_assistant({"action": "stop"})
