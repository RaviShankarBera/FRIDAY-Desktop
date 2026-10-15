import json
import pytest
from core import bridge as B


class Fake:
    def __init__(self): self.calls = []; self.updates = []
    def __call__(self, method, payload=None, files=None, timeout=60):
        self.calls.append((method, payload, files))
        if method == "getUpdates":
            u, self.updates = self.updates, []
            return {"ok": True, "result": u}
        return {"ok": True}
    def sent(self): return [p["text"] for m, p, _ in self.calls if m == "sendMessage"]


def upd(i, chat, text): return {"update_id": i, "message": {"chat": {"id": chat}, "text": text}}


@pytest.fixture
def mk(tmp_path):
    cfg = tmp_path / "k.json"; cfg.write_text("{}")
    def make(handler=lambda t: "ok:" + t):
        f = Fake(); logs = []
        b = B.Bridge("T", handler, logs.append, f, cfg, screenshot=lambda: b"jpg")
        return b, f, logs, cfg
    return make


def test_unpaired_ignores_everything_but_pair(mk):
    b, f, logs, cfg = mk()
    b.handle_update(upd(1, 7, "open chrome"))
    b.handle_update(upd(2, 7, "/pair 000000" if b.pair_code != "000000" else "/pair 111111"))
    assert f.sent() == [] and b.owner() is None


def test_pair_then_only_owner_commands(mk):
    ran = []
    b, f, logs, cfg = mk(lambda t: ran.append(t) or "done")
    b.handle_update(upd(1, 7, f"/pair {b.pair_code}"))
    assert b.owner() == 7 and "Paired" in f.sent()[0]
    assert json.loads(cfg.read_text())["bridge_owner_chat_id"] == 7
    b.handle_update(upd(2, 7, "work mode"))
    b.handle_update(upd(3, 99, "shutdown"))          # stranger
    assert ran == ["work mode"] and f.sent()[-1] == "done"


def test_screen_sends_photo_and_errors_are_spoken(mk):
    b, f, *_ = mk()
    b._set_owner(7)
    b.handle_update(upd(1, 7, "/screen"))
    assert f.calls[-1][0] == "sendPhoto" and f.calls[-1][2]["photo"][1] == b"jpg"
    b.screenshot = lambda: (_ for _ in ()).throw(RuntimeError("no display"))
    b.handle_update(upd(2, 7, "/screen"))
    assert "could not take a screenshot" in f.sent()[-1]


def test_handler_crash_becomes_sorry(mk):
    def boom(t): raise RuntimeError("x")
    b, f, *_ = mk(boom); b._set_owner(7)
    b.handle_update(upd(1, 7, "hi"))
    assert f.sent()[-1].startswith("Sorry, that failed")


def test_poll_advances_offset(mk):
    b, f, *_ = mk(); b._set_owner(7)
    f.updates = [upd(10, 7, "a"), upd(11, 7, "b")]
    assert b.poll_once() == 2 and b.offset == 12
    assert f.sent() == ["ok:a", "ok:b"]


def test_poll_error_raises(mk):
    b, f, *_ = mk()
    f.__class__.__call__ = lambda s, *a, **k: {"ok": False, "description": "Unauthorized"}
    with pytest.raises(RuntimeError):
        b.poll_once()


def test_split_long_message():
    parts = B.split_message("a" * 9000)
    assert all(len(p) <= B.MAX_LEN for p in parts) and "".join(parts) == "a" * 9000
    assert B.split_message("") == ["Done."]


def test_not_started_without_token(monkeypatch):
    monkeypatch.setattr(B.providers, "load_config", lambda *a: {})
    assert B.start_if_configured(lambda t: "", print) is None
    monkeypatch.setattr(B.providers, "load_config", lambda *a: {"telegram_bot_token": "PASTE_YOUR_TOKEN"})
    assert B.start_if_configured(lambda t: "", print) is None
