"""
FRIDAY model switcher (the agent "brain", not the Gemini Live voice session).

Policy: FREE-ONLY by default.
  * Free providers: Gemini, NVIDIA (development/trial access).
  * Paid providers: DeepSeek, OpenAI. They are NEVER used by automatic
    fallback, even when a key is saved. They only run if the user turns on
    "allow_paid" in config AND picks that provider explicitly.
  * When every free provider is out of quota, chat() raises QuotaExhausted with
    a plain message and stops. It never silently spends money.

Keys live only in config/api_keys.json (gitignored) - see config/api_keys.example.json.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


@dataclass(frozen=True)
class Spec:
    name: str
    label: str
    free: bool
    key_field: str
    kind: str            # "gemini" | "openai_compat"
    base_url: str = ""
    default_model: str = ""


SPECS: dict[str, Spec] = {s.name: s for s in (
    Spec("gemini", "Gemini", True, "gemini_api_key", "gemini", "", "gemini-flash-latest"),
    Spec("nvidia", "NVIDIA", True, "nvidia_api_key", "openai_compat",
         "https://integrate.api.nvidia.com/v1", "meta/llama-3.3-70b-instruct"),
    Spec("ollama", "Local Ollama", True, "ollama_model", "ollama",
         "http://127.0.0.1:11434", "llama3.2:3b"),
    Spec("deepseek", "DeepSeek", False, "deepseek_api_key", "openai_compat",
         "https://api.deepseek.com", "deepseek-chat"),
    Spec("openai", "OpenAI", False, "openai_api_key", "openai_compat",
         "https://api.openai.com/v1", "gpt-4o-mini"),
)}
FREE_ORDER = ("gemini", "nvidia", "ollama")   # automatic fallback order; local Ollama is the last resort
PLACEHOLDER = "PASTE_YOUR"


class QuotaExhausted(Exception):
    """Every allowed provider is out of quota (or failed). Stop - do not spend money."""


class QuotaError(Exception):
    """One provider reported rate limit / quota / no balance."""


class ProviderError(Exception):
    pass


def load_config(path: Path | None = None) -> dict:
    try:
        return json.loads((path or CONFIG_PATH).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(updates: dict, path: Path | None = None) -> None:
    p = path or CONFIG_PATH
    cfg = load_config(p)
    cfg.update(updates)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=4), encoding="utf-8")


_OLLAMA_PROBE: dict = {"t": 0.0, "up": False}


def ollama_up(base: str = "http://127.0.0.1:11434", cache_s: float = 20.0) -> bool:
    """True when a local Ollama server answers. Cached so status() stays cheap."""
    import time
    now = time.monotonic()
    if now - _OLLAMA_PROBE["t"] < cache_s and _OLLAMA_PROBE["t"]:
        return _OLLAMA_PROBE["up"]
    up = False
    try:
        import requests
        up = requests.get(base + "/api/tags", timeout=0.6).status_code == 200
    except Exception:
        up = False
    _OLLAMA_PROBE.update(t=now, up=up)
    return up


def has_key(cfg: dict, name: str) -> bool:
    if name == "ollama":                 # no key: usable when enabled (default) and the server is running
        return bool(cfg.get("ollama_enabled", True)) and ollama_up(cfg.get("ollama_url") or SPECS[name].base_url)
    v = str(cfg.get(SPECS[name].key_field) or "").strip()
    return bool(v) and PLACEHOLDER not in v


def allow_paid(cfg: dict) -> bool:
    return bool(cfg.get("allow_paid", False))


def status(cfg: dict | None = None) -> dict[str, str]:
    """name -> 'active' | 'connected' | 'paid-off' | 'not-linked' (for the UI)."""
    cfg = load_config() if cfg is None else cfg
    act = cfg.get("active_provider") or "gemini"
    out = {}
    for n, s in SPECS.items():
        if not has_key(cfg, n):
            out[n] = "not-linked"
        elif not s.free and not allow_paid(cfg):
            out[n] = "paid-off"
        else:
            out[n] = "active" if n == act else "connected"
    return out


def automatic_chain(cfg: dict) -> list[str]:
    """Providers eligible for automatic use, in order. Paid ones are never included."""
    act = cfg.get("active_provider") or "gemini"
    chain: list[str] = []
    if act in SPECS and SPECS[act].free and has_key(cfg, act):
        chain.append(act)
    for n in FREE_ORDER:
        if n not in chain and has_key(cfg, n):
            chain.append(n)
    return chain


def full_chain(cfg: dict) -> list[str]:
    """Chain for a call: the explicitly chosen paid provider (only if allow_paid is on),
    then the automatic free chain. Fallback never moves to a paid provider."""
    act = cfg.get("active_provider") or "gemini"
    chain: list[str] = []
    if act in SPECS and not SPECS[act].free and allow_paid(cfg) and has_key(cfg, act):
        chain.append(act)
    for n in automatic_chain(cfg):
        if n not in chain:
            chain.append(n)
    return chain


def set_active(name: str, cfg_path: Path | None = None) -> str:
    """Switch the active provider. Returns a short message for the user."""
    name = (name or "").strip().lower()
    aliases = {"google": "gemini", "nim": "nvidia", "local": "ollama", "offline": "ollama", "gpt": "openai", "chatgpt": "openai"}
    name = aliases.get(name, name)
    if name not in SPECS:
        return f"Sorry, I don't know a provider called '{name}'. Options: gemini, nvidia, ollama."
    cfg = load_config(cfg_path)
    s = SPECS[name]
    if not has_key(cfg, name):
        if name == "ollama":
            return "Sorry, Ollama is not running. Install it from ollama.com, run 'ollama pull llama3.2:3b', then try again."
        return f"Sorry, {s.label} has no key saved yet. Add it in Manage Providers first."
    if not s.free and not allow_paid(cfg):
        return (f"Sorry, {s.label} is a paid provider and FRIDAY is in free-only mode, "
                f"so I will not use it.")
    save_config({"active_provider": name}, cfg_path)
    return f"Switched to {s.label}."


# ── provider calls ────────────────────────────────────────────────────────────
def _is_quota_text(t: str) -> bool:
    t = (t or "").lower()
    return any(k in t for k in ("quota", "rate limit", "rate_limit", "resource_exhausted",
                                "429", "insufficient", "exceeded", "too many requests"))


def call_gemini(messages: list[dict], key: str, model: str) -> str:
    from google import genai
    from google.genai import types
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    user = "\n\n".join(m["content"] for m in messages if m["role"] != "system")
    client = genai.Client(api_key=key)
    try:
        r = client.models.generate_content(
            model=model, contents=user,
            config=types.GenerateContentConfig(system_instruction=system or None))
    except Exception as e:                      # noqa: BLE001
        if _is_quota_text(str(e)):
            raise QuotaError(str(e)) from e
        raise ProviderError(str(e)) from e
    return (r.text or "").strip()


def call_ollama(messages: list[dict], model: str, base_url: str) -> str:
    """Local model through Ollama's /api/chat. Free, offline, no key."""
    import requests
    try:
        r = requests.post(f"{base_url}/api/chat",
                          json={"model": model, "messages": messages, "stream": False,
                                "options": {"temperature": 0.2}}, timeout=120)
    except Exception as e:                      # noqa: BLE001
        raise ProviderError(str(e)) from e
    if r.status_code >= 400:
        raise ProviderError(f"Ollama HTTP {r.status_code} (is the model pulled? run: ollama pull {model})")
    try:
        return (r.json()["message"]["content"] or "").strip()
    except Exception as e:                      # noqa: BLE001
        raise ProviderError("bad Ollama response") from e


def call_openai_compat(messages: list[dict], key: str, model: str, base_url: str) -> str:
    import requests
    try:
        r = requests.post(f"{base_url}/chat/completions",
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": model, "messages": messages, "temperature": 0.2},
                          timeout=60)
    except Exception as e:                      # noqa: BLE001
        raise ProviderError(str(e)) from e
    if r.status_code in (402, 429) or (r.status_code >= 400 and _is_quota_text(r.text)):
        raise QuotaError(f"HTTP {r.status_code}")
    if r.status_code >= 400:
        raise ProviderError(f"HTTP {r.status_code}")
    try:
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:                      # noqa: BLE001
        raise ProviderError("bad response") from e


def _default_caller(name: str, cfg: dict) -> Callable[[list[dict]], str]:
    s = SPECS[name]
    if s.kind == "ollama":
        return lambda msgs: call_ollama(msgs, cfg.get("ollama_model") or s.default_model,
                                        cfg.get("ollama_url") or s.base_url)
    key = str(cfg.get(s.key_field)).strip()
    model = cfg.get(f"{name}_model") or s.default_model
    if s.kind == "gemini":
        return lambda msgs: call_gemini(msgs, key, model)
    return lambda msgs: call_openai_compat(msgs, key, model, s.base_url)


class Router:
    """chat(messages) with free-only fallback. `callers` lets tests inject fakes."""

    def __init__(self, cfg: dict | None = None, callers: dict[str, Callable] | None = None,
                 notify: Callable[[str], None] | None = None):
        self._cfg = cfg
        self._callers = callers or {}
        self.notify = notify or (lambda _m: None)
        self.last_used: str | None = None

    def cfg(self) -> dict:
        return self._cfg if self._cfg is not None else load_config()

    def chat(self, messages: list[dict]) -> str:
        cfg = self.cfg()
        chain = full_chain(cfg)
        if not chain:
            raise QuotaExhausted("Sorry, no free model has a key yet. Add a Gemini or NVIDIA key "
                                 "in Manage Providers.")
        tried: list[str] = []
        for i, name in enumerate(chain):
            fn = self._callers.get(name) or _default_caller(name, cfg)
            try:
                out = fn(messages)
                self.last_used = name
                if i > 0:
                    self.notify(f"{SPECS[chain[0]].label} is out of quota, switched to "
                                f"{SPECS[name].label}.")
                return out
            except (QuotaError, ProviderError):
                tried.append(SPECS[name].label)
        raise QuotaExhausted(
            "Sorry, every free model I can use (" + ", ".join(tried) + ") is out of quota or "
            "unavailable right now. I stopped instead of using a paid provider. Try again later.")
