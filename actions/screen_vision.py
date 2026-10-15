"""Screen vision: "Friday, what is this error?" - looks at the screen and explains it in words.

Differs from screen_process (which feeds a frame into the live voice session): this one asks a
vision model directly and returns a text answer, so it also works in fallback voice mode, can
read just the active window, and can copy a suggested fix to the clipboard.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

SYSTEM = ("You are FRIDAY looking at the user's screen. Answer the question about what is visible. "
          "If there is an error, say what it means in plain words, the likely cause, and the exact fix "
          "steps. Read text exactly. If something is not visible, say so; never guess. "
          "Be brief: under 120 words unless asked for detail. Do not repeat passwords, keys or "
          "other secrets you can see; say they are on screen.")

_BASE = Path(__file__).resolve().parent.parent


def _grab_screen() -> tuple[bytes, str]:
    from actions.screen_processor import _capture_screen
    return _capture_screen()


def _grab_active_window() -> tuple[bytes, str]:
    import mss
    import mss.tools
    import pygetwindow as gw
    w = gw.getActiveWindow()
    if w is None or w.width < 50 or w.height < 50:
        raise RuntimeError("no active window")
    box = {"left": max(0, w.left), "top": max(0, w.top), "width": w.width, "height": w.height}
    with mss.mss() as sct:
        shot = sct.grab(box)
        png = mss.tools.to_png(shot.rgb, shot.size)
    from actions.screen_processor import _compress
    return _compress(png, "PNG")


def _copy(text: str) -> bool:
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        return False


def screen_vision(parameters: dict, player=None) -> str:
    from core import gemini_helper
    p = parameters or {}
    question = str(p.get("question") or "What is on my screen? Explain any error.").strip()
    target = str(p.get("target") or "screen").strip().lower()
    try:
        if target in ("window", "active", "active_window"):
            try:
                img, mime = _grab_active_window()
            except Exception:
                img, mime = _grab_screen()          # fall back to the full screen
        elif target == "clipboard_image":
            from PIL import ImageGrab
            im = ImageGrab.grabclipboard()
            if im is None or not hasattr(im, "save"):
                return "Sorry, there is no image on the clipboard."
            buf = io.BytesIO(); im.convert("RGB").save(buf, "JPEG", quality=85)
            img, mime = buf.getvalue(), "image/jpeg"
        else:
            img, mime = _grab_screen()
    except Exception as e:                           # noqa: BLE001
        return f"Sorry, I could not capture the screen: {e}"
    try:
        answer = gemini_helper.generate(question, [(img, mime)], SYSTEM)
    except Exception as e:                           # noqa: BLE001
        return f"Sorry, I could not analyse the screen: {e}"
    if not answer:
        return "Sorry, the vision model returned nothing. Try again."
    if str(p.get("copy_answer", "")).lower() in ("true", "yes", "1") and _copy(answer):
        answer += " (Copied to your clipboard.)"
    if player:
        try: player.write_log(f"FRIDAY (vision): {answer}")
        except Exception: pass
    return answer


TOOL = {
    "name": "screen_vision",
    "description": ("Looks at the user's screen (or just the active window) and answers a question about it: "
                    "explain an error message, read text, summarise a page, say what a dialog wants. Use for "
                    "'Friday, what is this error', 'explain this screen', 'read this window'. Returns a text "
                    "answer. Set copy_answer=true when the user wants the fix copied to the clipboard."),
    "parameters": {"type": "OBJECT", "properties": {
        "question": {"type": "STRING", "description": "What the user wants to know about the screen."},
        "target": {"type": "STRING", "description": "'screen' (default), 'window' for the active window, or 'clipboard_image'."},
        "copy_answer": {"type": "STRING", "description": "'true' to copy the answer to the clipboard."}}},
    "handler": screen_vision,
}
