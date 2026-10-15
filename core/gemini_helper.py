"""One-shot Gemini calls (text, image, audio) for the feature modules.

Uses the key already saved in config/api_keys.json (never read from anywhere else, never
written). Falls back through the free chain in core.providers when the call is text-only.
Tests replace ``generate`` through ``set_backend``.
"""
from __future__ import annotations

from typing import Callable, Optional

from core import providers

MODEL = "gemini-flash-latest"
_backend: Optional[Callable[..., str]] = None


def set_backend(fn: Optional[Callable[..., str]]) -> None:
    global _backend
    _backend = fn


def _key() -> str:
    cfg = providers.load_config()
    if not providers.has_key(cfg, "gemini"):
        raise RuntimeError("No Gemini API key saved yet. Add it in Manage Providers.")
    return str(cfg["gemini_api_key"]).strip()


def generate(prompt: str, media: list[tuple[bytes, str]] | None = None, system: str = "") -> str:
    """Return Gemini's text answer. media = [(bytes, mime_type), ...] (images or audio)."""
    if _backend is not None:
        return _backend(prompt, media or [], system)
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=_key())
    contents: list = [types.Part.from_bytes(data=b, mime_type=m) for b, m in (media or [])]
    contents.append(prompt)
    try:
        r = client.models.generate_content(
            model=providers.load_config().get("gemini_model") or MODEL,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system or None))
    except Exception as e:                       # noqa: BLE001
        if providers._is_quota_text(str(e)):
            raise providers.QuotaError(str(e)) from e
        raise
    return (r.text or "").strip()


def ask_text(prompt: str, system: str = "") -> str:
    """Text only: goes through the free-only router (Gemini, NVIDIA, local Ollama)."""
    if _backend is not None:
        return _backend(prompt, [], system)
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    return providers.Router().chat(msgs)
