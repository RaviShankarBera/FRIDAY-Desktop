"""System doctor: report-first helpers. Pure functions with injectable roots so they are testable off Windows.

Nothing here deletes, moves or disables anything by itself except the explicit apply_* functions, which the action only
calls after the read-back gate. Every apply_* re-checks that the path is inside an allowed root.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import time
from collections import defaultdict
from pathlib import Path

PROTECTED_PARTS = {"windows", "program files", "program files (x86)", "programdata", "system volume information",
                   "$recycle.bin", "node_modules", ".git", ".venv", "venv", "site-packages", "__pycache__", "appdata"}
CAVEAT = ("This is a heuristic check, not antivirus. It flags things that look unusual; it cannot prove a file is safe or "
          "malicious. For a real scan use Windows Security.")


def human(n: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def digest(paths: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(paths)).encode()).hexdigest()[:8]


def _walk_files(root: Path, skip_protected: bool = True, deadline: float | None = None):
    stack = [root]
    while stack:
        d = stack.pop()
        if deadline and time.monotonic() > deadline:
            return
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            if skip_protected and e.name.lower() in PROTECTED_PARTS:
                                continue
                            stack.append(Path(e.path))
                        elif e.is_file(follow_symlinks=False):
                            yield Path(e.path), e.stat()
                    except OSError:
                        continue
        except OSError:
            continue


def _hash(path: Path, limit: int | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        if limit:
            h.update(f.read(limit))
        else:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
    return h.hexdigest()


# ── 1. duplicates ────────────────────────────────────────────────────────────
def find_duplicates(roots: list[Path], min_bytes: int = 1 << 20, max_seconds: float = 60.0) -> dict:
    """Real duplicates only: same size, same first 64 KB, same full SHA-256. Keeper = oldest file (shortest path on tie)."""
    deadline = time.monotonic() + max_seconds
    by_size: dict[int, list[tuple[Path, float]]] = defaultdict(list)
    seen = set()
    for r in roots:
        for p, st in _walk_files(r, deadline=deadline):
            if st.st_size >= min_bytes and p not in seen:
                seen.add(p)
                by_size[st.st_size].append((p, st.st_mtime))
    groups = []
    for size, items in by_size.items():
        if len(items) < 2:
            continue
        part: dict[str, list] = defaultdict(list)
        for p, m in items:
            try:
                part[_hash(p, 65536)].append((p, m))
            except OSError:
                pass
        for cand in part.values():
            if len(cand) < 2:
                continue
            full: dict[str, list] = defaultdict(list)
            for p, m in cand:
                try:
                    full[_hash(p)].append((p, m))
                except OSError:
                    pass
            for files in full.values():
                if len(files) > 1:
                    files.sort(key=lambda x: (x[1], len(str(x[0]))))
                    groups.append({"size": size, "keep": str(files[0][0]), "dupes": [str(p) for p, _ in files[1:]]})
    groups.sort(key=lambda g: g["size"] * len(g["dupes"]), reverse=True)
    return {"groups": groups, "wasted": sum(g["size"] * len(g["dupes"]) for g in groups),
            "timed_out": time.monotonic() > deadline}


def apply_duplicates(groups: list[dict], trash) -> tuple[int, int, list[str]]:
    """Move each duplicate to `trash` (recoverable) after re-verifying it is still identical to its keeper."""
    n = freed = 0
    errors = []
    for g in groups:
        keep = Path(g["keep"])
        for d in g["dupes"]:
            p = Path(d)
            try:
                if p == keep or not keep.exists() or not p.exists() or _hash(p) != _hash(keep):
                    errors.append(f"{p.name}: changed since the scan, skipped")
                    continue
                size = p.stat().st_size
                trash(str(p))
                n += 1
                freed += size
            except Exception as e:
                errors.append(f"{p.name}: {str(e)[:60]}")
    return n, freed, errors


# ── 2. temp cleanup ──────────────────────────────────────────────────────────
def temp_roots() -> list[Path]:
    import tempfile
    roots = [Path(tempfile.gettempdir())]
    win = os.environ.get("SystemRoot")
    if win:
        roots.append(Path(win) / "Temp")
    la = os.environ.get("LOCALAPPDATA")
    if la:
        roots.append(Path(la) / "CrashDumps")
    out, seen = [], set()
    for r in roots:
        k = str(r).lower()
        if k not in seen and r.is_dir():
            seen.add(k)
            out.append(r)
    return out


def scan_temp(roots: list[Path], min_age_days: float = 2.0) -> dict:
    """Files not touched for `min_age_days`, so nothing a running program is using right now."""
    cutoff = time.time() - min_age_days * 86400
    per, files = {}, []
    for r in roots:
        tot = 0
        for p, st in _walk_files(r, skip_protected=False):
            if max(st.st_mtime, st.st_atime) < cutoff:
                files.append((str(p), st.st_size))
                tot += st.st_size
        per[str(r)] = tot
    files.sort(key=lambda x: x[1], reverse=True)
    return {"per_root": per, "files": files, "total": sum(s for _, s in files)}


def apply_temp(files: list[tuple[str, int]], roots: list[Path]) -> tuple[int, int, list[str]]:
    n = freed = 0
    errors = []
    rs = [r.resolve() for r in roots]
    for path, size in files:
        p = Path(path)
        try:
            rp = p.resolve()
            if not any(rp == r or r in rp.parents for r in rs) or p.is_symlink():
                errors.append(f"{p.name}: outside the temp folders, skipped")
                continue
            p.unlink()
            n += 1
            freed += size
        except OSError:
            continue              # in use or protected: leave it
    for r in roots:                # tidy empty sub-folders, never the roots
        for dp, dn, fn in os.walk(r, topdown=False):
            if Path(dp) != r:
                try:
                    os.rmdir(dp)
                except OSError:
                    pass
    return n, freed, errors


# ── 3. disk usage ────────────────────────────────────────────────────────────
def folder_sizes(root: Path, top: int = 10, max_seconds: float = 25.0) -> dict:
    deadline = time.monotonic() + max_seconds
    sizes: dict[str, int] = defaultdict(int)
    loose = 0
    biggest: list[tuple[int, str]] = []
    for p, st in _walk_files(root, skip_protected=False, deadline=deadline):
        try:
            rel = p.relative_to(root).parts
        except ValueError:
            continue
        if len(rel) == 1:
            loose += st.st_size
        else:
            sizes[rel[0]] += st.st_size
        biggest.append((st.st_size, str(p)))
        if len(biggest) > 400:
            biggest = sorted(biggest, reverse=True)[:50]
    folders = sorted(sizes.items(), key=lambda x: x[1], reverse=True)[:top]
    return {"folders": folders, "loose": loose, "files": sorted(biggest, reverse=True)[:top],
            "partial": time.monotonic() > deadline}


# ── 4. startup apps ──────────────────────────────────────────────────────────
HEAVY = ("teams", "spotify", "discord", "steam", "epic", "adobe", "creative cloud", "zoom", "skype", "dropbox", "itunes",
         "slack", "onedrive", "origin", "battle.net", "ubisoft", "whatsapp", "telegram", "msedge", "chrome", "opera",
         "utorrent", "bittorrent", "cortana", "yourphone", "phone link", "officeclicktorun", "ccleaner", "java")
KEEP = ("securityhealth", "windows security", "defender", "realtek", "nvidia", "intel", "amd", "synaptics", "touchpad",
        "ctfmon", "bluetooth", "wacom", "audio", "ethernet")


def classify_startup(name: str, command: str = "") -> tuple[str, str]:
    n = f"{name} {command}".lower()
    if any(k in n for k in KEEP):
        return "keep", "looks like a driver or security component"
    if any(k in n for k in HEAVY):
        return "disable", "usually not needed at boot; it opens fine from the Start menu"
    return "review", "unknown, check whether you use it"


def list_startup() -> list[dict]:
    """Windows only: registry Run keys (current user and machine) and the Startup folder."""
    items: list[dict] = []
    if os.name != "nt":
        return items
    import winreg
    for hive, hname in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
        try:
            k = winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Run")
        except OSError:
            continue
        i = 0
        while True:
            try:
                name, val, _t = winreg.EnumValue(k, i)
            except OSError:
                break
            i += 1
            v, why = classify_startup(name, str(val))
            items.append({"name": name, "command": str(val)[:120], "where": hname, "verdict": v, "why": why,
                          "can_disable": hname == "HKCU"})
    sf = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup"
    if sf.is_dir():
        for f in sf.iterdir():
            if f.name.lower() != "desktop.ini":
                v, why = classify_startup(f.name)
                items.append({"name": f.name, "command": str(f), "where": "StartupFolder", "verdict": v, "why": why,
                              "can_disable": True})
    return items


DISABLED_BYTES = bytes([3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
ENABLED_BYTES = bytes([2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])


def set_startup_state(item: dict, enabled: bool) -> bool:
    """Flip the same switch Task Manager uses (StartupApproved). Reversible, deletes nothing. Current-user entries only."""
    if os.name != "nt" or not item.get("can_disable"):
        return False
    import winreg
    sub = "Run" if item["where"] == "HKCU" else "StartupFolder"
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\{sub}")
    winreg.SetValueEx(key, item["name"], 0, winreg.REG_BINARY, ENABLED_BYTES if enabled else DISABLED_BYTES)
    return True


# ── 5. performance ───────────────────────────────────────────────────────────
def performance_snapshot() -> dict:
    import psutil
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    procs = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            procs.append((p.info["memory_info"].rss, p.info["name"] or "?"))
        except Exception:
            pass
    agg: dict[str, int] = defaultdict(int)
    for rss, n in procs:
        agg[n] += rss
    disks = []
    for d in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(d.mountpoint)
            disks.append({"mount": d.mountpoint, "free": u.free, "total": u.total, "pct": u.percent})
        except Exception:
            pass
    bat = getattr(psutil, "sensors_battery", lambda: None)()
    return {"cpu_pct": psutil.cpu_percent(interval=1.0), "cores": psutil.cpu_count(logical=True), "ram_pct": vm.percent,
            "ram_used": vm.used, "ram_total": vm.total, "swap_pct": sw.percent, "disks": disks,
            "uptime_h": (time.time() - psutil.boot_time()) / 3600,
            "top_mem": sorted(agg.items(), key=lambda x: x[1], reverse=True)[:5],
            "battery": None if not bat else {"pct": bat.percent, "plugged": bat.power_plugged}}


def verdicts(s: dict) -> list[str]:
    v = []
    if s["ram_pct"] >= 85:
        v.append(f"Memory is tight ({s['ram_pct']:.0f}% used). Close big apps or restart.")
    if s["cpu_pct"] >= 85:
        v.append(f"CPU is busy right now ({s['cpu_pct']:.0f}%).")
    for d in s["disks"]:
        if d["pct"] >= 90:
            v.append(f"Drive {d['mount']} is {d['pct']:.0f}% full, only {human(d['free'])} free.")
    if s["uptime_h"] > 24 * 7:
        v.append(f"This PC has not restarted for {s['uptime_h'] / 24:.0f} days. A restart often helps.")
    return v or ["Nothing alarming: memory, CPU and disk space all look healthy."]


# ── 6. suspicious files (heuristic) ──────────────────────────────────────────
DOC_EXT = r"(pdf|docx?|xlsx?|pptx?|jpe?g|png|gif|txt|mp3|mp4|zip|rar)"
EXEC_EXT = (".exe", ".scr", ".com", ".bat", ".cmd", ".vbs", ".ps1", ".js", ".jse", ".wsf", ".jar", ".msi", ".pif")
_DOUBLE = re.compile(rf"\.{DOC_EXT}\.(exe|scr|bat|cmd|com|js|vbs|ps1|pif)$", re.I)
SYSTEM_NAMES = {"svchost.exe", "lsass.exe", "csrss.exe", "explorer.exe", "winlogon.exe", "services.exe", "smss.exe", "taskmgr.exe"}
ODD_DIRS = ("temp", "roaming", "public", "downloads", "$recycle.bin", "programdata")


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    c = {ch: s.count(ch) for ch in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in c.values())


def check_file(path: Path, st) -> list[str]:
    """Reasons this file looks unusual. Empty list = nothing stands out."""
    name = path.name
    low = name.lower()
    reasons = []
    if _DOUBLE.search(low):
        reasons.append("disguised double extension (looks like a document but is a program)")
    if low in SYSTEM_NAMES and not any(x in str(path).lower().replace("/", "\\") for x in ("\\system32\\", "\\syswow64\\", "\\windows\\")):
        reasons.append("has a Windows system file's name but is not in the Windows folder")
    isexec = low.endswith(EXEC_EXT)
    in_odd = any(p in ODD_DIRS for p in (x.lower() for x in path.parts[:-1]))
    stem = path.stem
    if isexec and in_odd and len(stem) >= 10 and " " not in stem and _entropy(stem.lower()) >= 3.3 and not re.search(r"[aeiou]{1}.*[aeiou]{1}.*[aeiou]", stem.lower()):
        reasons.append("random-looking program name in an unusual folder")
    elif isexec and any(x.lower() in ("temp", "tmp") for x in path.parts[:-1]):
        reasons.append("program sitting in a temp folder")
    if isexec and getattr(st, "st_file_attributes", 0) & 2:
        reasons.append("hidden program file")
    return reasons


def scan_suspicious(roots: list[Path], max_seconds: float = 40.0, signer=None, max_sign: int = 30) -> list[dict]:
    deadline = time.monotonic() + max_seconds
    hits = []
    for r in roots:
        for p, st in _walk_files(r, skip_protected=False, deadline=deadline):
            why = check_file(p, st)
            if why:
                hits.append({"path": str(p), "size": st.st_size, "why": why, "mtime": st.st_mtime})
    if signer:
        for h in [x for x in hits if x["path"].lower().endswith((".exe", ".scr", ".msi", ".dll"))][:max_sign]:
            if signer(h["path"]) in ("NotSigned", "HashMismatch", "UnknownError"):
                h["why"].append("not digitally signed")
    hits.sort(key=lambda h: (-len(h["why"]), -h["mtime"]))
    return hits


def ps_signature(path: str) -> str:
    import subprocess
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-AuthenticodeSignature -LiteralPath $args[0]).Status.ToString()", path],
                           capture_output=True, text=True, timeout=20)
        return (r.stdout or "").strip() or "UnknownError"
    except Exception:
        return "UnknownError"
