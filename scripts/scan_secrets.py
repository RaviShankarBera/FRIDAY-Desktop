"""
Pre-upload secret scan. Run before every commit/push:

    python scripts/scan_secrets.py

Scans every file that git would include (tracked + untracked, minus .gitignore)
or, outside a git repo, every file under the project folder except ignored
paths. Exits 1 and prints file:line (never the secret itself) on any match.
"""
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PATTERNS = {
    "Google/Gemini API key":   r"AIza[0-9A-Za-z_\-]{30,}",
    "OpenAI-style key":        r"\bsk-[A-Za-z0-9_\-]{20,}",
    "NVIDIA API key":          r"\bnvapi-[A-Za-z0-9_\-]{20,}",
    "GitHub token":            r"\bgh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}",
    "ElevenLabs key":          r"\bsk_[a-f0-9]{30,}",
    "Private key block":       r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "Key assigned in config":  r"""["']?[A-Za-z_]*(api_?key|secret|token|password)["']?\s*[:=]\s*["'][A-Za-z0-9_\-\.]{24,}["']""",
}
PLACEHOLDER = re.compile(r"PASTE_|YOUR_|EXAMPLE|PLACEHOLDER|xxxx", re.I)
SKIP_DIRS = {".git", "__pycache__", "models", "venv", ".venv", "node_modules"}
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".onnx", ".pyc", ".mp3", ".wav", ".js"}


def candidate_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout
        return [ROOT / p for p in out.splitlines() if p]
    except Exception:
        ignore = [l.strip() for l in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
                  if l.strip() and not l.startswith("#")] if (ROOT / ".gitignore").exists() else []
        files = []
        for p in ROOT.rglob("*"):
            rel = p.relative_to(ROOT).as_posix()
            if not p.is_file() or set(p.relative_to(ROOT).parts) & SKIP_DIRS:
                continue
            if any(fnmatch.fnmatch(rel, pat.rstrip("/") + ("/*" if pat.endswith("/") else ""))
                   or fnmatch.fnmatch(p.name, pat) for pat in ignore):
                continue
            files.append(p)
        return files


def main() -> int:
    hits = []
    for f in candidate_files():
        if f.suffix.lower() in SKIP_SUFFIX or not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if PLACEHOLDER.search(line):
                continue
            for label, pat in PATTERNS.items():
                if re.search(pat, line, re.I if "assigned" in label else 0):
                    hits.append((f.relative_to(ROOT).as_posix(), n, label))
    if hits:
        print("SECRET SCAN FAILED - possible keys found (values not shown):")
        for path, n, label in hits:
            print(f"  {path}:{n}  {label}")
        print("Remove them (keep keys only in config/api_keys.json or env vars) and re-run.")
        return 1
    print(f"Secret scan clean ({len(candidate_files())} files checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
