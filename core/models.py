"""Speech models FRIDAY downloads on first use. Weights are never stored in the repo (models/ is gitignored)."""
from __future__ import annotations

import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"

VOSK_BASE = "https://alphacephei.com/vosk/models"
MODELS = {
    "en": ("vosk-model-small-en-us-0.15", "~40 MB"),
    "hi": ("vosk-model-small-hi-0.22", "~42 MB"),
}


def model_dir(lang: str) -> Path:
    return MODELS_DIR / MODELS[lang][0]


def present(lang: str) -> bool:
    d = model_dir(lang)
    return (d / "am").is_dir() and (d / "conf").is_dir()


def ensure(lang: str, logger: Callable[[str], None] = print) -> tuple[bool, str]:
    """Download and unpack the model once. Never raises. Returns (ok, message)."""
    if lang not in MODELS:
        return False, f"unknown language '{lang}'"
    if present(lang):
        return True, "ready"
    name, size = MODELS[lang]
    zpath = MODELS_DIR / f"{name}.zip"
    try:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        logger(f"Downloading the {lang.upper()} speech model ({size}, one-time)...")
        urllib.request.urlretrieve(f"{VOSK_BASE}/{name}.zip", zpath)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(MODELS_DIR)
    except Exception as e:
        return False, f"{lang} model download failed: {e}"
    finally:
        try:
            zpath.unlink()
        except Exception:
            pass
    return (True, "ready") if present(lang) else (False, f"{lang} model unpacked but not found")
