"""Start an installed project, after reading the exact command back. Low-trust projects start in Windows Sandbox."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from core import interactive
from core import repo_install as ri
from core import sandbox as sbx


def _files(root: Path) -> dict[str, str]:
    out = {}
    for f in ("package.json", "README.md", "readme.md", "requirements.txt", "pyproject.toml", "setup.py"):
        p = root / f
        if p.is_file() and p.stat().st_size < 400_000:
            out[f] = p.read_text(errors="replace")
    return out


def run_project(parameters=None, response=None, player=None, session_memory=None, speak=None) -> str:
    from actions.install_repo import read_marker
    p = parameters or {}
    folder = (p.get("folder") or "").strip()
    if not folder:
        return "[NEED_INFO] I have NOT started anything. Ask which installed project to run (its folder)."
    target = Path(folder)
    if not target.is_dir():
        return f"Sorry, {target} is not a folder, so I started nothing."
    files = _files(target)
    names = {x.name for x in target.iterdir()}
    argv, source = ri.find_run_command(files, names, target)
    if not argv:
        return ("I could not find how to start this project (no start script, no main.py or app.py, no python command in the "
                "README). I started nothing. Ask the user for the exact command, or point them to the README.")
    if not ri.validate_run_argv(argv):
        return f"Sorry, the start command from {source} contains something I won't run: {' '.join(argv)[:100]}. I started nothing."
    marker = read_marker(target)
    tier = marker.get("tier", "unknown")
    use_sbx = tier == "low" and sbx.available() and str(p.get("sandbox", "auto")).lower() != "no"
    shown = " ".join(argv)
    if tier == "low" and use_sbx:
        where = "inside Windows Sandbox, isolated from your PC"
    elif tier == "low":
        where = "directly on your PC. This project looks low-trust and Windows Sandbox is not available, so it is NOT isolated"
    else:
        where = "on your PC"
    def _go() -> str:
        if use_sbx:
            out = target.parent / ".friday_sandbox" / target.name
            out.mkdir(parents=True, exist_ok=True)
            kinds = ri.detect_kind(set(files))
            (out / "run.ps1").write_text(sbx.render_ps1(kinds, "requirements.txt" in files, bool({"pyproject.toml", "setup.py"} & set(files)), argv),
                                         encoding="utf-8")
            (out / "friday.wsb").write_text(sbx.render_wsb(str(target), str(out)), encoding="utf-8")
            ok, why = sbx.launch(out / "friday.wsb")
            return (f"Started '{shown}' in Windows Sandbox; watch that window. Log: {out / 'log.txt'}." if ok else why)

        if argv[0].lower().startswith(str(target).lower()) and not Path(argv[0]).exists():
            return "The project's environment is missing. Install it first with install_repo, then run it. I started nothing."
        log = target / ".friday_run.log"
        with open(log, "wb") as lf:
            proc = subprocess.Popen(argv, cwd=str(target), stdout=lf, stderr=subprocess.STDOUT, env=ri.clean_env(),
                                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            time.sleep(float(p.get("wait", 6)))
        code = proc.poll()
        tail = log.read_text(errors="replace")[-300:].strip()
        if code is None:
            return f"Started '{shown}' (process {proc.pid}) and it is still running. Log: {log}."
        if code == 0:
            return f"'{shown}' ran and finished normally. Output: {tail or 'none'}"
        return f"'{shown}' stopped with error code {code}. Last output: {tail or 'none'}"

    return interactive.park("run_project", f"Run '{shown}' from {source} in {target}, {where}", _go, speak)

TOOL = {
    "name": "run_project",
    "description": ("Starts a project installed with install_repo. Finds the start command (npm start, main.py, README), "
                    "reads it back for a yes, then runs it; low-trust projects run in Windows Sandbox."),
    "parameters": {"type": "OBJECT", "properties": {
        "folder": {"type": "STRING", "description": "Full path of the installed project folder"},
        "sandbox": {"type": "STRING", "description": "Leave empty."},
    }, "required": ["folder"]},
    "handler": run_project,
}
