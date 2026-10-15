"""System doctor: find duplicates, clean temp files, see what fills the disk, tame startup apps, check performance,
flag unusual files. REPORT FIRST: nothing is deleted, moved or disabled without the read-back gate and a yes."""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from core import doctor as dr
from core import interactive

REPORT_DIR = Path.home() / "FRIDAY_reports"


def _report(name: str, lines: list[str]) -> str:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    p = REPORT_DIR / f"{name}_{datetime.now():%Y%m%d_%H%M%S}.txt"
    p.write_text("\n".join(lines), encoding="utf-8")
    return str(p)


def _default_roots() -> list[Path]:
    home = Path.home()
    return [d for d in (home / "Downloads", home / "Documents", home / "Desktop", home / "Pictures", home / "Videos", home / "Music") if d.is_dir()]


def _roots(p: dict) -> list[Path]:
    raw = (p.get("path") or "").strip()
    if not raw:
        return _default_roots()
    q = Path(os.path.expandvars(os.path.expanduser(raw)))
    return [q] if q.is_dir() else []


def _trash():
    try:
        from send2trash import send2trash
        return send2trash
    except Exception:
        return None


def _log(player, text: str) -> None:
    if player:
        try:
            player.write_log(text)
        except Exception:
            pass


# ── actions ───────────────────────────────────────────────────────────────────
def _duplicates(p, player, apply: bool, speak=None) -> str:
    roots = _roots(p)
    if not roots:
        return "Sorry, I could not find that folder. Ask the user which folder to check."
    res = dr.find_duplicates(roots, min_bytes=int(float(p.get("min_mb", 1)) * (1 << 20)))
    g = res["groups"]
    if not g:
        return "No real duplicates found" + (" (the scan hit its time limit, so it may be incomplete)." if res["timed_out"] else ".")
    lines = [f"Duplicate files, {len(g)} groups, {dr.human(res['wasted'])} wasted. First line of each group is KEPT (oldest).", ""]
    by_folder: dict[str, int] = {}
    for x in g:
        lines.append(f"[{dr.human(x['size'])} each]  KEEP  {x['keep']}")
        lines += [f"                 dupe  {d}" for d in x["dupes"]]
        for d in x["dupes"]:
            by_folder[str(Path(d).parent)] = by_folder.get(str(Path(d).parent), 0) + x["size"]
    rep = _report("duplicates", lines)
    _log(player, "[doctor] duplicates report: " + rep)
    top = sorted(by_folder.items(), key=lambda kv: kv[1], reverse=True)[:5]
    summ = f"{len(g)} duplicate groups, {dr.human(res['wasted'])} reclaimable. Most in: " + "; ".join(f"{k} ({dr.human(v)})" for k, v in top)
    if not apply:
        return (f"Found {summ}. Full list with paths and sizes saved to {rep}. Nothing was changed. "
                f"Offer to move the extra copies to the Recycle Bin, keeping one of each.")
    trash = _trash()
    if trash is None:
        return "Sorry, I can't move files to the Recycle Bin because send2trash isn't installed, so I deleted nothing."
    dupes = [d for x in g for d in x["dupes"]]
    def _go() -> str:
        n, freed, errs = dr.apply_duplicates(g, trash)
        return f"Moved {n} duplicate files ({dr.human(freed)}) to the Recycle Bin; they can be restored from there." + (f" Skipped {len(errs)}." if errs else "")
    return interactive.park("system_doctor", f"Move {len(dupes)} duplicate files ({dr.human(res['wasted'])}) to the Recycle Bin, "
                            f"keeping the oldest copy of each. List {dr.digest(dupes)} is in {rep}", _go, speak)


def _temp(p, player, apply: bool, speak=None) -> str:
    roots = dr.temp_roots()
    res = dr.scan_temp(roots)
    lines = [f"Temp files older than 2 days: {len(res['files'])} files, {dr.human(res['total'])}", ""]
    lines += [f"{k}: {dr.human(v)}" for k, v in res["per_root"].items()] + [""]
    lines += [f"{dr.human(s):>10}  {f}" for f, s in res["files"]]
    rep = _report("temp_cleanup", lines)
    _log(player, "[doctor] temp report: " + rep)
    if not res["files"]:
        return "Nothing to clean: no temp files older than 2 days."
    where = "; ".join(f"{k} ({dr.human(v)})" for k, v in res["per_root"].items() if v)
    if not apply:
        return (f"I can free {dr.human(res['total'])} from {len(res['files'])} old temp files: {where}. Full list saved to {rep}. "
                f"Nothing was deleted. Offer to clean them.")
    def _go() -> str:
        n, freed, errs = dr.apply_temp(res["files"], roots)
        return f"Deleted {n} temp files and freed {dr.human(freed)}. Files in use were left alone."
    return interactive.park("system_doctor", f"Permanently delete {len(res['files'])} temp files older than 2 days ({dr.human(res['total'])}) "
                            f"from {where}. List {dr.digest([f for f, _ in res['files']])} is in {rep}", _go, speak)


def _disk(p, player) -> str:
    roots = _roots(p) if (p.get("path") or "").strip() else [Path(os.path.abspath(os.sep)) if os.name != "nt" else Path(os.environ.get("SystemDrive", "C:") + "\\")]
    if not roots:
        return "Sorry, I could not find that folder."
    r = roots[0]
    res = dr.folder_sizes(r)
    du = shutil.disk_usage(r)
    lines = [f"{r}: {dr.human(du.used)} used of {dr.human(du.total)}, {dr.human(du.free)} free", "", "Biggest folders:"]
    lines += [f"{dr.human(s):>10}  {n}" for n, s in res["folders"]] + ["", "Biggest files:"] + [f"{dr.human(s):>10}  {f}" for s, f in res["files"]]
    rep = _report("disk_usage", lines)
    top = ", ".join(f"{n} {dr.human(s)}" for n, s in res["folders"][:5])
    return (f"{r} has {dr.human(du.free)} free of {dr.human(du.total)}. Biggest folders: {top}." +
            (" The scan hit its time limit so these are partial." if res["partial"] else "") + f" Full report: {rep}.")


def _startup(p, player) -> str:
    items = dr.list_startup()
    if not items:
        return ("I can only read startup apps on Windows." if os.name != "nt" else "I found no startup apps.")
    lines = [f"[{i['verdict'].upper():7}] {i['name']}  ({i['where']})  {i['why']}\n          {i['command']}" for i in items]
    rep = _report("startup", lines)
    dis = [i['name'] for i in items if i['verdict'] == 'disable']
    return (f"{len(items)} startup apps. Worth disabling: {', '.join(dis) or 'none obvious'}. Everything else is either a driver/security "
            f"item to keep or needs your judgement. Full list: {rep}. Disabling is reversible. Nothing was changed.")


def _set_startup(p, player, enable: bool, speak=None) -> str:
    name = (p.get("name") or "").strip()
    if not name:
        return "[NEED_INFO] Ask which startup app."
    match = [i for i in dr.list_startup() if i["name"].lower() == name.lower()] or \
            [i for i in dr.list_startup() if name.lower() in i["name"].lower()]
    if len(match) != 1:
        return f"I found {len(match)} startup entries matching '{name}', so I changed nothing. Ask which one."
    it = match[0]
    if not it["can_disable"]:
        return f"{it['name']} is a machine-wide entry; changing it needs administrator rights, so I left it alone."
    if it["verdict"] == "keep" and not enable:
        pass  # still allowed, but the read-back warns
    verb = "Enabling" if enable else "Disabling"
    note = " It looks like a driver or security component, so this is not recommended." if it["verdict"] == "keep" and not enable else ""
    def _go() -> str:
        return f"{verb[:-3]}ed {it['name']} at startup. Takes effect next sign-in." if dr.set_startup_state(it, enable) else "Sorry, that did not work."
    return interactive.park("system_doctor", f"{verb} the startup app {it['name']}. This is reversible.{note}", _go, speak)


def _perf(p, player) -> str:
    s = dr.performance_snapshot()
    disks = "; ".join(f"{d['mount']} {dr.human(d['free'])} free ({d['pct']:.0f}% full)" for d in s["disks"])
    top = ", ".join(f"{n} {dr.human(r)}" for n, r in s["top_mem"])
    return (f"CPU {s['cpu_pct']:.0f}% on {s['cores']} threads. Memory {s['ram_pct']:.0f}% used "
            f"({dr.human(s['ram_used'])} of {dr.human(s['ram_total'])}). Disks: {disks}. Up {s['uptime_h']:.0f} hours. "
            f"Biggest memory users: {top}. " + " ".join(dr.verdicts(s)))


def _suspicious(p, player) -> str:
    home = Path.home()
    roots = _roots(p) if (p.get("path") or "").strip() else [d for d in (
        home / "Downloads", home / "Desktop", Path(os.environ.get("TEMP", "/tmp")), home / "AppData/Roaming", Path("C:/Users/Public")) if d.is_dir()]
    hits = dr.scan_suspicious(roots, signer=dr.ps_signature if os.name == "nt" else None)
    if not hits:
        return "Nothing unusual stood out in " + ", ".join(str(r) for r in roots) + ". " + dr.CAVEAT
    lines = [dr.CAVEAT, ""] + [f"{dr.human(h['size']):>10}  {h['path']}\n            " + "; ".join(h["why"]) for h in hits]
    rep = _report("suspicious_files", lines)
    top = "; ".join(f"{Path(h['path']).name}: {h['why'][0]}" for h in hits[:3])
    return f"{len(hits)} files look unusual. Top: {top}. Full list: {rep}. I changed nothing. {dr.CAVEAT}"


def _ps(cmd: str, timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=timeout)


def _defender(p, player, speak=None) -> str:
    if os.name != "nt":
        return "Windows Defender scans are only available on Windows."
    try:
        if _ps("Get-Command Start-MpScan -ErrorAction Stop | Out-Null; 'ok'").stdout.strip() != "ok":
            return "Windows Defender scanning isn't available here (another antivirus may be in charge). Open Windows Security instead."
    except Exception:
        return "I could not reach Windows Defender. Open Windows Security to scan."
    path = (p.get("path") or "").strip()
    desc = f"a Windows Defender custom scan of {path}" if path else "a Windows Defender quick scan"
    cmd = f"Start-MpScan -ScanType CustomScan -ScanPath '{path}'" if path else "Start-MpScan -ScanType QuickScan"
    if path and ("'" in path or ";" in path or not Path(path).exists()):
        return "Sorry, that path isn't valid for a scan."

    def _go() -> str:
        subprocess.Popen(["powershell", "-NoProfile", "-Command", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Started {desc}. Ask me for the scan results in a few minutes, or open Windows Security."
    return interactive.park("system_doctor", f"Start {desc}. It runs in the background and may slow the PC for a few minutes", _go, speak)


def _defender_results(p, player) -> str:
    if os.name != "nt":
        return "Only available on Windows."
    r = _ps("Get-MpThreatDetection | Select-Object -First 5 ThreatID,ProcessName,InitialDetectionTime | ConvertTo-Json -Compress")
    out = (r.stdout or "").strip()
    return ("Windows Defender lists no recent threat detections." if not out else f"Windows Defender recent detections: {out[:400]}. Open Windows Security to act on them.")


def system_doctor(parameters=None, response=None, player=None, session_memory=None, speak=None) -> str:
    p = parameters or {}
    a = (p.get("action") or "").strip().lower()
    try:
        return {
            "duplicates": lambda: _duplicates(p, player, False, speak),
            "delete_duplicates": lambda: _duplicates(p, player, True, speak),
            "temp_report": lambda: _temp(p, player, False, speak),
            "clean_temp": lambda: _temp(p, player, True, speak),
            "disk_usage": lambda: _disk(p, player),
            "startup": lambda: _startup(p, player),
            "disable_startup": lambda: _set_startup(p, player, False, speak),
            "enable_startup": lambda: _set_startup(p, player, True, speak),
            "performance": lambda: _perf(p, player),
            "suspicious": lambda: _suspicious(p, player),
            "defender_scan": lambda: _defender(p, player, speak),
            "defender_results": lambda: _defender_results(p, player),
        }[a]()
    except KeyError:
        return "[NEED_INFO] Unknown system_doctor action. Use: duplicates, delete_duplicates, temp_report, clean_temp, disk_usage, startup, disable_startup, enable_startup, performance, suspicious, defender_scan, defender_results."
    except Exception as e:
        return f"Sorry, the {a} check failed: {str(e)[:150]}. Nothing was changed."


TOOL = {
    "name": "system_doctor",
    "description": ("PC health checks. Report first, nothing is changed without a read-back and a yes. Actions: duplicates "
                    "(report real duplicate files), delete_duplicates, temp_report (what cleanup would free), clean_temp, "
                    "disk_usage (what fills the drive), startup (boot-slowing apps), disable_startup/enable_startup (name), "
                    "performance (CPU/RAM/disk), suspicious (heuristic unusual-file flags, NOT antivirus), defender_scan, "
                    "defender_results. Always report first, offer the change second."),
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "description": "one of the actions above"},
        "path": {"type": "STRING", "description": "Optional folder. Default: Downloads, Documents, Desktop, Pictures (duplicates); the system drive (disk_usage)."},
        "name": {"type": "STRING", "description": "Startup app name for disable_startup/enable_startup"},
        "min_mb": {"type": "STRING", "description": "Minimum file size in MB for duplicates (default 1)"},
    }, "required": ["action"]},
    "handler": system_doctor,
}
