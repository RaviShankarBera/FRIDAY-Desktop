"""Phone bridge: send FRIDAY a command from your phone, FRIDAY does it on the PC and replies.

Transport: a Telegram bot (free, official API, long polling: no public URL, no port forwarding).
WhatsApp has no free official way to do this without a public web server, so the bridge keeps the
transport separate from the command logic (Bridge.handle_update) and Telegram is the one shipped.

Safety:
  * Only ONE paired chat can command the PC. Everyone else is ignored silently.
  * Pairing: the PC shows a 6-digit code in the log; you send "/pair 123456" to the bot once.
  * The bot token lives in config/api_keys.json (gitignored) as "telegram_bot_token".
  * Commands run through the same tools and the same on-screen confirmation gate as voice
    (shutdown, restart, close app still need a click on the PC), so a stolen phone cannot power the PC off.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path
from typing import Callable

from core import providers

API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 3900


def split_message(text: str, limit: int = MAX_LEN) -> list[str]:
    text = text or "Done."
    out = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        cut = cut if cut > limit // 2 else limit
        out.append(text[:cut]); text = text[cut:].lstrip("\n")
    out.append(text)
    return out


class Bridge:
    def __init__(self, token: str, handler: Callable[[str], str], log: Callable[[str], None] = print,
                 http: Callable[..., dict] | None = None, cfg_path: Path | None = None,
                 screenshot: Callable[[], bytes] | None = None):
        self.token, self.handler, self.log = token, handler, log
        self._http = http or self._real_http
        self.cfg_path = cfg_path
        self.screenshot = screenshot
        self.offset = 0
        self.pair_code = f"{secrets.randbelow(10**6):06d}"
        self._stop = threading.Event()

    # -- config
    def owner(self) -> int | None:
        v = providers.load_config(self.cfg_path).get("bridge_owner_chat_id")
        return int(v) if v else None

    def _set_owner(self, chat_id: int) -> None:
        providers.save_config({"bridge_owner_chat_id": int(chat_id)}, self.cfg_path)

    # -- telegram
    def _real_http(self, method: str, payload: dict | None = None, files: dict | None = None, timeout: int = 60) -> dict:
        import requests
        r = requests.post(API.format(token=self.token, method=method), data=payload, files=files, timeout=timeout)
        return r.json()

    def send(self, chat_id: int, text: str) -> None:
        for part in split_message(text):
            self._http("sendMessage", {"chat_id": chat_id, "text": part})

    def send_photo(self, chat_id: int, jpg: bytes) -> None:
        self._http("sendPhoto", {"chat_id": chat_id}, files={"photo": ("screen.jpg", jpg)})

    # -- logic (pure, tested)
    def handle_update(self, upd: dict) -> None:
        msg = upd.get("message") or {}
        text = (msg.get("text") or "").strip()
        chat = (msg.get("chat") or {}).get("id")
        if not text or chat is None:
            return
        owner = self.owner()
        if owner is None:
            if text.lower().startswith("/pair") and text.split()[-1] == self.pair_code:
                self._set_owner(chat)
                self.send(chat, "Paired. This chat can now command FRIDAY. Try: screenshot, work mode, timer 10 minutes.")
                self.log("SYS: Phone bridge paired.")
            return                                   # unpaired: ignore everything else silently
        if chat != owner:
            return                                   # not the owner: ignore silently
        low = text.lower()
        if low in ("/start", "/help"):
            self.send(chat, "FRIDAY is online. Send any command as text. /screen sends a screenshot of the PC.")
        elif low == "/screen":
            try:
                self.send_photo(chat, self.screenshot())
            except Exception as e:                   # noqa: BLE001
                self.send(chat, f"Sorry, I could not take a screenshot: {e}")
        else:
            self.log(f"[Phone]: {text}")
            try:
                reply = self.handler(text)
            except Exception as e:                   # noqa: BLE001
                reply = f"Sorry, that failed: {e}"
            self.send(chat, reply)

    def poll_once(self, timeout: int = 25) -> int:
        d = self._http("getUpdates", {"offset": self.offset, "timeout": timeout}, timeout=timeout + 10)
        if not d.get("ok"):
            raise RuntimeError(str(d.get("description", "telegram error"))[:80])
        ups = d.get("result", [])
        for u in ups:
            self.offset = max(self.offset, u["update_id"] + 1)
            self.handle_update(u)
        return len(ups)

    def run(self) -> None:
        if self.owner() is None:
            self.log(f"SYS: Phone bridge ready. In Telegram send the bot: /pair {self.pair_code}")
        else:
            self.log("SYS: Phone bridge online.")
        fails = 0
        while not self._stop.is_set():
            try:
                self.poll_once(); fails = 0
            except Exception as e:                   # noqa: BLE001
                fails += 1
                if fails in (1, 10):
                    self.log(f"SORRY: phone bridge connection problem ({str(e)[:60]}), retrying.")
                self._stop.wait(min(60, 2 ** min(fails, 6)))

    def stop(self) -> None:
        self._stop.set()


def start_if_configured(handler: Callable[[str], str], log: Callable[[str], None]) -> Bridge | None:
    cfg = providers.load_config()
    tok = str(cfg.get("telegram_bot_token") or "").strip()
    if not tok or providers.PLACEHOLDER in tok:
        return None

    def shot() -> bytes:
        from actions.screen_processor import _capture_screen
        return _capture_screen()[0]
    b = Bridge(tok, handler, log, screenshot=shot)
    threading.Thread(target=b.run, daemon=True, name="phone-bridge").start()
    return b
