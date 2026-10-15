"""
Local wake-word detection for FRIDAY ("Friday").

Uses Vosk (small offline English model, ~40 MB) restricted to a one-word grammar
so it only has to decide "Friday" or "something else". Everything runs on the
machine; while FRIDAY is asleep the mic audio never leaves the computer.

The public surface is unchanged from the original "Friday" module
(is_installed, is_ready, install_and_download, WakeWordDetector) so main.py and
the UI keep working.
"""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

WAKE_PHRASE = "friday"
MODEL_NAME  = "vosk-model-small-en-us-0.15"
MODEL_URL   = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
SAMPLE_RATE = 16000
# Ignore repeat detections of the same utterance for this long (seconds).
DEBOUNCE_S  = 1.5

BASE_DIR  = Path(__file__).resolve().parent.parent
MODEL_DIR = BASE_DIR / "models" / MODEL_NAME


def is_installed() -> bool:
    """True if the vosk package is importable (no model check)."""
    try:
        import importlib.util
        return importlib.util.find_spec("vosk") is not None
    except Exception:
        return False


def _model_present() -> bool:
    return (MODEL_DIR / "am").is_dir() and (MODEL_DIR / "conf").is_dir()


def is_ready() -> bool:
    """vosk installed AND model files on disk. Cheap, deterministic, never raises."""
    try:
        return is_installed() and _model_present()
    except Exception:
        return False


def contains_wake_word(text: str) -> bool:
    """True if `text` contains the wake word as a whole word (case-insensitive)."""
    return WAKE_PHRASE in (text or "").lower().replace(",", " ").replace(".", " ").replace(":", " ").split()


def install_and_download(logger: Callable[[str], None] = print) -> tuple[bool, str]:
    """One-click setup: pip-install vosk if missing, then download the small model.
    Returns (ok, message). Never raises."""
    try:
        if not is_installed():
            logger("Wake word: installing vosk (one-time)…")
            r = subprocess.run([sys.executable, "-m", "pip", "install", "vosk"],
                               capture_output=True, text=True)
            if r.returncode != 0:
                tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
                return False, f"pip install failed: {tail[0][:160]}"
        if not _model_present():
            logger("Wake word: downloading speech model (~40 MB, one-time)…")
            MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
            zpath = MODEL_DIR.parent / f"{MODEL_NAME}.zip"
            try:
                urllib.request.urlretrieve(MODEL_URL, zpath)
                with zipfile.ZipFile(zpath) as z:
                    z.extractall(MODEL_DIR.parent)
            except Exception as e:
                return False, f"model download failed: {e}"
            finally:
                try:
                    zpath.unlink()
                except Exception:
                    pass
        if not is_ready():
            return False, "installed, but the wake model could not be found."
        logger("Wake word: ready.")
        return True, "Wake word installed and ready."
    except Exception as e:
        return False, f"setup error: {e}"


class WakeWordDetector:
    """
    Runs the recogniser in a dedicated thread. The mic thread calls feed() with
    raw int16 frames; detections invoke on_detect() from this thread.
    """

    def __init__(self, on_detect: Callable[[], None],
                 threshold: float = 0.0,          # kept for API compatibility
                 logger: Callable[[str], None] = print):
        self._on_detect = on_detect
        self._logger    = logger
        self._queue: queue.Queue = queue.Queue(maxsize=100)
        self._thread: threading.Thread | None = None
        self._running = False
        self._rec = None
        self._ready = False
        self._last_fire = 0.0
        self.accept_stop = False     # True only while FRIDAY is speaking: "stop" then counts as a barge-in

    def start(self) -> bool:
        if self._running:
            return True
        try:
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)
            model = Model(str(MODEL_DIR))
            self._rec = KaldiRecognizer(model, SAMPLE_RATE, json.dumps([WAKE_PHRASE, "stop", "[unk]"]))
        except Exception as e:
            self._logger(f"Wake word: could not load model — {e}")
            self._rec = None
            return False
        self._running = True
        self._ready = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="WakeWordThread")
        self._thread.start()
        self._logger("Wake word: listening for 'Friday'.")
        return True

    def stop(self) -> None:
        self._running = False
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass
        self._rec = None
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def feed(self, frame_int16) -> None:
        """Called from the real-time mic callback. Cheap, never blocks."""
        if not self._running:
            return
        try:
            data = frame_int16[:, 0] if getattr(frame_int16, "ndim", 1) > 1 else frame_int16
            self._queue.put_nowait(data.tobytes())
        except Exception:
            pass

    def _heard(self, text: str) -> bool:
        if contains_wake_word(text):
            return True
        return self.accept_stop and "stop" in (text or "").lower().split()

    def _fire(self) -> None:
        now = time.monotonic()
        if now - self._last_fire < DEBOUNCE_S:
            return
        self._last_fire = now
        self._drain()
        try:
            if self._rec is not None:
                self._rec.Reset()
        except Exception:
            pass
        try:
            self._on_detect()
        except Exception as e:
            self._logger(f"Wake word: on_detect error — {e}")

    def _loop(self) -> None:
        while self._running:
            try:
                chunk = self._queue.get()
                if chunk is None or not self._running or self._rec is None:
                    break
                if self._rec.AcceptWaveform(chunk):
                    text = json.loads(self._rec.Result()).get("text", "")
                else:
                    text = json.loads(self._rec.PartialResult()).get("partial", "")
                if self._heard(text):
                    self._fire()
            except Exception as e:
                self._logger(f"Wake word: inference error — {e}")

    def _drain(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except Exception:
            pass
