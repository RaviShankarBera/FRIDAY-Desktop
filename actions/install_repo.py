"""Install a GitHub repo conversationally and safely. See core/repo_install.py for the rules.

Flow: repo -> where to install -> inspect (shallow clone to a temp folder, nothing executed) -> read back the exact
plan -> user says yes -> clone to the folder -> run ONLY the planned commands (no shell, no FRIDAY secrets) -> report.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from core import interactive
from core import repo_install as ri
from core import sandbox as sbx
import json

SETUP_FILES = ("requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "package.json", "README.md", "readme.md")
OWN_DIR = Path(__file__).resolve().parent.parent


def _git(args: list[str], cwd: str | None = None, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.hooksPath=NUL" if __import__("os").name == "nt" else "core.hooksPath=/dev/null",
                           "-c", "protocol.file.allow=never", *args],
                          cwd=cwd, capture_output=True, text=True, timeout=timeout, env=ri.clean_env())


def _clone(owner: str, name: str, dest: Path) -> tuple[bool, str, str]:
    r = _git(["clone", "--depth", "1", "--no-tags", "--", f"https://github.com/{owner}/{name}.git", str(dest)])
    if r.returncode != 0:
        return False, (r.stderr or "clone failed").strip()[-200:], ""
    sha = _git(["rev-parse", "HEAD"], cwd=str(dest)).stdout.strip()
    return True, "", sha


def _meta(owner: str, name: str) -> dict | None:
    try:
        import requests
        r = requests.get(f"https://api.github.com/repos/{owner}/{name}", timeout=10,
                         headers={"Accept": "application/vnd.github+json", "User-Agent": "FRIDAY-Desktop"})
        return r.json() if r.ok else None
    except Exception:
        return None


def _read_files(root: Path) -> dict[str, str]:
    out = {}
    for f in SETUP_FILES:
        p = root / f
        if p.is_file() and p.stat().st_size < 400_000:
            out[f] = p.read_text(errors="replace")
    return out


def drives() -> list[str]:
    """Windows drives with free space, so the question can offer real choices."""
    try:
        import psutil
        res = []
        for d in psutil.disk_partitions(all=False):
            if "cdrom" in d.opts.lower() or not d.fstype:
                continue
            res.append(f"{d.mountpoint.rstrip(chr(92))} ({shutil.disk_usage(d.mountpoint).free // 1024**3} GB free)")
        return res
    except Exception:
        return []


def _write_marker(base: Path, name: str, data: dict) -> None:
    d = base / ".friday_installs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def read_marker(target: Path) -> dict:
    try:
        return json.loads((target.parent / ".friday_installs" / f"{target.name}.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def install_repo(parameters=None, response=None, player=None, session_memory=None, speak=None) -> str:
    p = parameters or {}
    parsed = ri.parse_repo(p.get("repo", ""))
    if not parsed:
        return ("[NEED_INFO] I have NOT done anything. I need a GitHub repository as 'owner/name' or a github.com link. "
                "Only GitHub is supported. Ask the user which repo.")
    owner, name = parsed
    if not (p.get("location") or "").strip():
        opts = ", ".join(drives()) or "C: or D:"
        return (f"[NEED_INFO] I have NOT done anything. Ask ONE short question: which drive or folder should {owner}/{name} "
                f"be installed on? Available: {opts}. A project folder named '{name}' will be created inside it.")
    ok, why, base = ri.check_location(p["location"], OWN_DIR)
    if not ok:
        return f"Sorry, I did not install anything. {why} Ask the user for a different folder."
    target = base / name
    if target.exists() and any(target.iterdir()):
        return f"Sorry, {target} already exists and is not empty, so I did not touch it. Ask the user for another folder."

    tmp = Path(tempfile.mkdtemp(prefix="friday_inspect_"))
    try:
        ok, err, sha = _clone(owner, name, tmp / name)
        if not ok:
            return f"Sorry, I could not download {owner}/{name}: {err}. Nothing was installed."
        files = _read_files(tmp / name)
        plan = ri.build_plan(target, files)
        meta = _meta(owner, name)
        flags = ri.trust_flags(meta)
        tier = ri.trust_tier(meta)
        readme_part = ri.read_install_section(files.get("README.md") or files.get("readme.md") or "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    use_sbx = tier == "low" and str(p.get("sandbox", "auto")).lower() != "no" and sbx.available() and any(k in plan["kinds"] for k in ("python", "node"))
    if tier == "low" and use_sbx:
        iso = "This project looks low-trust, so I will set it up inside Windows Sandbox, a disposable isolated Windows, and nothing will be installed on your PC"
    elif tier == "low":
        iso = ("This project looks low-trust and I cannot isolate it (" + ("Windows Sandbox does not support this project type"
               if sbx.available() else sbx.UNAVAILABLE_HELP) + "). Continuing runs its setup directly on your PC")
    else:
        iso = ""
    summary = ri.plan_summary(owner, name, sha, target, plan, flags, iso)
    def _go() -> str:
        base.mkdir(parents=True, exist_ok=True)
        ok, err, sha2 = _clone(owner, name, target)
        if not ok:
            return f"Sorry, the download failed: {err}. Nothing was installed."
        if sha2 != sha:
            shutil.rmtree(target, ignore_errors=True)
            return "The project changed while I was preparing, so I stopped and deleted it. Ask again to get a fresh read-back."
        _write_marker(base, name, {"tier": tier, "sandboxed": use_sbx, "repo": f"{owner}/{name}", "target": str(target)})
        if use_sbx:
            files2 = _read_files(target)
            out = base / ".friday_sandbox" / name
            out.mkdir(parents=True, exist_ok=True)
            (out / "run.ps1").write_text(sbx.render_ps1(plan["kinds"], "requirements.txt" in files2,
                                                        bool({"pyproject.toml", "setup.py"} & set(files2))), encoding="utf-8")
            (out / "friday.wsb").write_text(sbx.render_wsb(str(target), str(out)), encoding="utf-8")
            ok2, why2 = sbx.launch(out / "friday.wsb")
            if not ok2:
                return f"Downloaded {owner}/{name} to {target} but could not start Windows Sandbox: {why2}"
            return (f"Downloaded {owner}/{name} to {target} (read-only copy; nothing from it ran on this PC). A Windows Sandbox window "
                    f"opened and is installing it in isolation, which takes a few minutes. Its log appears at {out / 'log.txt'}. "
                    f"The sandbox and everything in it vanish when closed. Tell the user to watch that window.")
        done, failed = [], None
        for c in plan["commands"]:
            if speak:
                speak(f"Now: {c['why']}.")
            try:
                r = subprocess.run(c["argv"], cwd=c["cwd"], capture_output=True, text=True, timeout=1200, env=ri.clean_env())
            except Exception as e:
                failed = (c, str(e)[:200]); break
            if r.returncode != 0:
                failed = (c, (r.stderr or r.stdout)[-300:]); break
            done.append(c["why"])
        lines = [f"Downloaded {owner}/{name} to {target}."]
        if done:
            lines.append("Done: " + "; ".join(done) + ".")
        if failed:
            lines.append(f"Stopped at: {failed[0]['why']}. Error: {failed[1].strip()[-200:]}")
        if plan["manual"]:
            lines.append("Needs you: " + " ".join(plan["manual"]))
        lines.append("I did not run the project. If the user wants it started, call run_project with folder=" + str(target) + ".")
        return " ".join(lines)

    note = " (The README's own install steps are NOT run.)" if readme_part else ""
    return interactive.park("install_repo", summary + note, _go, speak)

TOOL = {
    "name": "install_repo",
    "description": ("Installs a GitHub project: asks where, downloads it, reads its setup files, builds an isolated environment "
                    "and installs dependencies, after reading the exact plan back. Never runs the project itself or any README "
                    "script. Use whenever the user asks to install, set up or clone a GitHub repo."),
    "parameters": {"type": "OBJECT", "properties": {
        "repo": {"type": "STRING", "description": "'owner/name' or a github.com URL"},
        "location": {"type": "STRING", "description": "Full folder path to install into, e.g. D:\\Apps. Ask the user; never guess."},
        "sandbox": {"type": "STRING", "description": "Leave empty. 'no' only if the user explicitly refuses Windows Sandbox."},
    }, "required": ["repo"]},
    "handler": install_repo,
}
