"""
Non-Live voice fallback for FRIDAY (free only).

When Gemini Live is unavailable or out of free quota, FRIDAY keeps talking:

    mic -> offline STT (Vosk) -> active provider via Router (free-only) -> free TTS

Rules kept here, in one testable place:
  * Commands need the "Friday" prefix (same as the Live path). Anything else is ignored.
  * The LLM comes from core.providers.Router, so DeepSeek/OpenAI are never used
    automatically. When every free model is out of quota we say so and stop.
  * TTS order: ElevenLabs (only if the user added a key) -> Edge TTS (free) -> system voice (pyttsx3, offline).
    A TTS failure is logged and the reply stays visible in the log.
  * No key is read or written here; Router and the TTS engines take them from config.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from core.providers import QuotaExhausted, Router

PREFIX_RE = re.compile(r"^\W*(?:hey\s+|ok\s+|okay\s+)?(?:friday|फ्राइडे|फ्राइडै|फ्राईडे)(?=[\s,:.\-!?]|$)[\s,:.\-]*", re.I)
TOOL_RE = re.compile(r"^\s*TOOL:\s*(\{.*\})\s*$", re.S)
DEVANAGARI = re.compile(r"[\u0900-\u097F]")

EDGE_VOICES = {"en": "en-IN-NeerjaNeural", "hi": "hi-IN-SwaraNeural"}

FALLBACK_ADDENDUM = """
FALLBACK VOICE MODE: the live voice link is unavailable, so you are answering through text.
Reply in 1-3 short spoken sentences, plain text only (no markdown, no lists).
To use a tool, reply with exactly one line and nothing else:
TOOL: {"name": "<tool name>", "args": {...}}
Available tools:
%s
After a tool result arrives, tell the user the outcome in one short sentence.
If a tool failed, start with "Sorry" and say what you could not do.
"""


def strip_prefix(text: str) -> str | None:
    """Return the command after 'Friday', or None when the prefix is missing."""
    t = (text or "").strip()
    m = PREFIX_RE.match(t)
    if not m:
        return None
    return t[m.end():].strip() or ""


def parse_tool_call(reply: str) -> dict | None:
    m = TOOL_RE.match(reply or "")
    if not m:
        return None
    try:
        d = json.loads(m.group(1))
    except Exception:
        return None
    if isinstance(d, dict) and isinstance(d.get("name"), str):
        args = d.get("args")
        return {"name": d["name"], "args": args if isinstance(args, dict) else {}}
    return None


def pick_voice(text: str) -> str:
    return EDGE_VOICES["hi"] if DEVANAGARI.search(text or "") else EDGE_VOICES["en"]


def tool_lines(declarations: list[dict], limit: int = 40) -> str:
    out = []
    for d in declarations[:limit]:
        props = ", ".join((d.get("parameters") or {}).get("properties", {}).keys())
        desc = (d.get("description") or "").split("\n")[0][:90]
        out.append(f"- {d.get('name')}({props}): {desc}")
    return "\n".join(out)


class BilingualSTT:
    """Runs one Vosk recognizer per language on the same audio and keeps the better result.

    Preference: a result that starts with 'Friday' beats one that does not; then higher
    average word confidence wins. Same interface as VoskSTT.process_chunk.
    """

    def __init__(self, models: dict[str, str], log: Callable[[str], None] = print):
        from vosk import KaldiRecognizer, Model
        self.recs: list[tuple[str, object]] = []
        for lang, path in models.items():
            try:
                r = KaldiRecognizer(Model(path), 16000)
                r.SetWords(True)
                self.recs.append((lang, r))
            except Exception as e:
                log(f"SORRY: {lang} speech model failed to load ({str(e)[:70]}).")
        if not self.recs:
            raise RuntimeError("no speech model could be loaded")
        self.languages = [l for l, _ in self.recs]

    @staticmethod
    def _parse(raw: str) -> tuple[str, float]:
        d = json.loads(raw)
        words = d.get("result") or []
        conf = sum(w.get("conf", 0) for w in words) / len(words) if words else 0.0
        return (d.get("text") or "").strip(), conf

    def process_chunk(self, pcm: bytes) -> tuple[str, bool]:
        finals = [r.AcceptWaveform(pcm) for _, r in self.recs]
        if not any(finals):
            return "", False
        cands = []
        for (lang, r), fin in zip(self.recs, finals):
            text, conf = self._parse(r.Result() if fin else r.FinalResult())
            if text:
                cands.append((strip_prefix(text) is not None, conf, lang, text))
        if not cands:
            return "", True
        cands.sort(reverse=True)
        return cands[0][3], True


class FallbackBrain:
    """Text in, spoken text out. Pure logic, no audio, fully testable."""

    MAX_TOOL_STEPS = 2

    def __init__(self, router: Router, system_prompt: str, declarations: list[dict],
                 run_tool: Callable[[str, dict], str], log: Callable[[str], None]):
        self.router = router
        self.log = log
        self.run_tool = run_tool
        self.system = system_prompt + FALLBACK_ADDENDUM % tool_lines(declarations)
        self.history: list[dict] = []

    def _chat(self, extra: list[dict]) -> str:
        msgs = [{"role": "system", "content": self.system}] + self.history[-12:] + extra
        return self.router.chat(msgs).strip()

    def reply(self, command: str) -> str:
        self.history.append({"role": "user", "content": command})
        extra: list[dict] = []
        try:
            for _ in range(self.MAX_TOOL_STEPS + 1):
                out = self._chat(extra)
                call = parse_tool_call(out)
                if not call:
                    self.history.append({"role": "assistant", "content": out})
                    return out
                self.log(f"SYS: Fallback voice running {call['name']}.")
                try:
                    res = str(self.run_tool(call["name"], call["args"]))[:1500]
                except Exception as e:
                    res = f"Tool failed: {e}"
                extra += [{"role": "assistant", "content": out},
                          {"role": "user", "content": f"TOOL RESULT ({call['name']}): {res}"}]
            return "Sorry, I could not finish that task."
        except QuotaExhausted as e:
            return str(e)


class FallbackVoice:
    """Feeds PCM to STT, gates on the 'Friday' prefix, asks the brain, speaks the answer."""

    def __init__(self, stt, brain: FallbackBrain, speak: Callable[[str], None],
                 log: Callable[[str], None]):
        self.stt, self.brain, self.speak, self.log = stt, brain, speak, log

    def on_pcm(self, pcm: bytes) -> str | None:
        """Feed int16 mono 16 kHz bytes. Returns the reply when an utterance completed."""
        text, final = self.stt.process_chunk(pcm)
        if not final or not text.strip():
            return None
        return self.on_text(text)

    def on_text(self, text: str) -> str | None:
        cmd = strip_prefix(text)
        if cmd is None:
            return None
        self.log(f"You: {text}")
        if not cmd:
            reply = "Yes? I am listening."
        else:
            reply = self.brain.reply(cmd)
        self.log(f"FRIDAY: {reply}")
        try:
            self.speak(reply)
        except Exception as e:
            self.log(f"SORRY: voice output failed ({str(e)[:80]}). The answer is in the log.")
        return reply


def make_speaker(cfg: dict, log: Callable[[str], None]) -> Callable[[str], None]:
    """ElevenLabs if a key exists, else Edge TTS (free). Falls back per call."""
    from core.tts import EdgeTTSEngine, ElevenLabsTTSEngine
    try:
        from memory.config_manager import get_elevenlabs_key, get_elevenlabs_voice_id
        key, voice = get_elevenlabs_key(), get_elevenlabs_voice_id()
    except Exception:
        key = (cfg.get("elevenlabs_api_key") or "").strip()
        voice = (cfg.get("elevenlabs_voice_id") or "").strip() or "21m00Tcm4TlvDq8ikWAM"

    def speak(text: str) -> None:
        if key:
            try:
                ElevenLabsTTSEngine(api_key=key, voice_id=voice).speak(text)
                return
            except Exception as e:
                log(f"SORRY: ElevenLabs failed ({str(e)[:60]}), using the free Edge voice.")
        try:
            EdgeTTSEngine(voice=pick_voice(text)).speak(text)
            return
        except Exception as e:
            log(f"SORRY: Edge voice failed ({str(e)[:60]}), trying the offline system voice.")
        _system_voice(text)
    return speak


FEMALE_HINTS = ("zira", "heera", "hazel", "susan", "aria", "jenny", "female", "woman",
                "samantha", "victoria", "karen", "moira", "tessa", "veena", "kalpana")



def pick_system_voice(voices) -> str | None:
    """Id of a female system voice, or None when none can be identified.
    Never returns a voice that looks male."""
    def nm(v):
        return ((getattr(v, "name", "") or "") + " " + str(getattr(v, "id", ""))).lower()
    for v in voices or []:
        n = nm(v)
        if any(h in n for h in FEMALE_HINTS) and "male" not in n.replace("female", ""):
            return v.id
    for v in voices or []:
        g = str(getattr(v, "gender", "") or "").lower()
        if g.startswith("f"):
            return v.id
    return None


def _system_voice(text: str) -> None:
    """Last resort, fully offline: the operating system voice via pyttsx3, female only."""
    import pyttsx3
    eng = pyttsx3.init()
    vid = pick_system_voice(eng.getProperty("voices"))
    if vid is None:
        raise RuntimeError("no female system voice installed")
    eng.setProperty("voice", vid)
    eng.say(text)
    eng.runAndWait()
