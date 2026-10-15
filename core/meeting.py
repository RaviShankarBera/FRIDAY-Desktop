"""Meeting assistant: record the mic, transcribe, summarise, list action items.

Records 16 kHz mono WAV with sounddevice, in chunks of at most CHUNK_SECONDS so each piece stays
inside the free Gemini audio limit. Transcription and summary use the free Gemini key. Files go to
meetings/<timestamp>/ (gitignored). Only the microphone is recorded: other people on a call are
captured only if their voices come out of your speakers. Tell people you are recording.
"""
from __future__ import annotations

import datetime as dt
import io
import threading
import wave
from pathlib import Path
from typing import Callable

BASE = Path(__file__).resolve().parent.parent
MEETINGS_DIR = BASE / "meetings"
RATE = 16000
CHUNK_SECONDS = 8 * 60

SUMMARY_PROMPT = """Below is a meeting transcript. Write:
SUMMARY: 3-6 short bullet points.
DECISIONS: bullets, or "none".
ACTION ITEMS: bullets as "Owner - task - due date if said", or "none". Only items actually said.
Do not invent names, dates or facts. If the transcript is empty or unclear, say so.

TRANSCRIPT:
"""


def wav_bytes(pcm: bytes, rate: int = RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)
    return buf.getvalue()


def split_pcm(pcm: bytes, chunk_seconds: int = CHUNK_SECONDS, rate: int = RATE) -> list[bytes]:
    n = chunk_seconds * rate * 2
    return [pcm[i:i + n] for i in range(0, len(pcm), n)] or [b""]


class Recorder:
    def __init__(self, device=None, stream_factory: Callable | None = None):
        self.device = device
        self._factory = stream_factory
        self._frames: list[bytes] = []
        self._stream = None
        self.started_at: dt.datetime | None = None
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self._stream is not None

    def _cb(self, indata, frames, time_info, status) -> None:
        with self._lock:
            self._frames.append(bytes(indata))

    def start(self) -> None:
        if self.active:
            raise RuntimeError("already recording")
        if self._factory:
            self._stream = self._factory(self._cb)
        else:
            import sounddevice as sd
            self._stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16",
                                             device=self.device, callback=self._cb)
        self._stream.start()
        self.started_at = dt.datetime.now()

    def stop(self) -> bytes:
        if not self.active:
            raise RuntimeError("not recording")
        try:
            self._stream.stop(); self._stream.close()
        finally:
            self._stream = None
        with self._lock:
            pcm = b"".join(self._frames); self._frames = []
        return pcm

    def seconds(self) -> int:
        with self._lock:
            return sum(len(f) for f in self._frames) // (RATE * 2)


def process(pcm: bytes, started: dt.datetime, transcribe: Callable[[bytes], str],
            summarise: Callable[[str], str], out_root: Path | None = None) -> dict:
    """Transcribe in chunks, summarise, save files. Returns {dir, transcript, summary}."""
    root = out_root or MEETINGS_DIR
    d = root / started.strftime("%Y-%m-%d_%H%M")
    d.mkdir(parents=True, exist_ok=True)
    if len(pcm) < RATE * 2 * 2:                      # under ~2 seconds of audio
        raise ValueError("The recording is too short, nothing to transcribe.")
    (d / "audio.wav").write_bytes(wav_bytes(pcm))
    parts = [transcribe(wav_bytes(c)).strip() for c in split_pcm(pcm) if len(c) > RATE * 2]
    transcript = "\n".join(p for p in parts if p).strip()
    (d / "transcript.md").write_text(transcript or "(no speech detected)", encoding="utf-8")
    summary = summarise(transcript) if transcript else "No speech was detected in the recording."
    (d / "summary.md").write_text(summary, encoding="utf-8")
    return {"dir": str(d), "transcript": transcript, "summary": summary}


# ---- real model-backed callables ----
def gemini_transcribe(wav: bytes) -> str:
    from core import gemini_helper
    return gemini_helper.generate(
        "Transcribe this audio exactly. Keep the original language (Hindi or English; write Hindi in Roman "
        "letters if mixed). Label speakers as Speaker 1, Speaker 2 where you can tell. "
        "Output only the transcript. If there is no speech, output nothing.",
        [(wav, "audio/wav")])


def gemini_summarise(transcript: str) -> str:
    from core import gemini_helper
    return gemini_helper.ask_text(SUMMARY_PROMPT + transcript)


_REC = Recorder()


def recorder() -> Recorder:
    return _REC
