"""Pure logic for installing a GitHub repo safely: parsing, path rules, inspection, plan, risk flags.

Nothing here runs repo code. The only things ever executed (by actions/install_repo.py) are the argv lists
that appear in the plan the user heard and approved.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_URL = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:[/#?].*)?$")
_SHORT = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?$")


def parse_repo(text: str) -> tuple[str, str] | None:
    """'owner/name' or a github.com URL -> (owner, name). Anything else (other hosts, ssh, local paths) -> None."""
    t = (text or "").strip()
    m = _URL.match(t) or (_SHORT.match(t) if "://" not in t and "@" not in t and "\\" not in t else None)
    if not m or m.group(2) in (".", "..") or m.group(1) in (".", ".."):
        return None
    return m.group(1), m.group(2)


_BLOCKED_PARTS = ("windows", "program files", "program files (x86)", "programdata", "system32", "appdata")


def check_location(folder: str, own_dir: Path | None = None) -> tuple[bool, str, Path | None]:
    """The install folder must be absolute, not a system location, and not FRIDAY's own folder."""
    if not folder or not folder.strip():
        return False, "No install folder given.", None
    p = Path(os.path.expandvars(os.path.expanduser(folder.strip())))
    if not p.is_absolute():
        return False, "The install folder must be a full path such as D:\\Apps.", None
    parts = [x.lower() for x in p.parts]
    if len(p.parts) <= 1:
        return False, "Please pick a folder, not the root of a drive.", None
    if any(x in _BLOCKED_PARTS for x in parts):
        return False, "I won't install into a Windows or program-files folder.", None
    if own_dir is not None:
        try:
            p.resolve().relative_to(own_dir.resolve())
            return False, "I won't install inside FRIDAY's own folder.", None
        except ValueError:
            pass
    return True, "", p


def read_install_section(readme: str, limit: int = 1500) -> str:
    """The README part about installing, for the user to read. Never executed."""
    if not readme:
        return ""
    lines = readme.splitlines()
    for i, ln in enumerate(lines):
        if re.match(r"#{1,4}\s*.*(install|setup|getting started|quick ?start|usage)", ln, re.I):
            return "\n".join(lines[i:i + 40])[:limit]
    return ""


_PIP_REFUSE = re.compile(r"^\s*(--?(extra-)?index-url|-i\b|--find-links|-f\b|--trusted-host)", re.I)
_PIP_FLAG = re.compile(r"(git\+|https?://|^\s*-e\b|^\s*--editable)", re.I)


def analyse_requirements(text: str) -> dict:
    refuse, flags, n = [], [], 0
    for ln in (text or "").splitlines():
        s = ln.split("#")[0].strip()
        if not s:
            continue
        if _PIP_REFUSE.search(s):
            refuse.append(s[:80])
        elif _PIP_FLAG.search(s):
            flags.append(s[:80])
        elif not s.startswith("-"):
            n += 1
    return {"count": n, "refuse": refuse, "flags": flags}


_LIFECYCLE = ("preinstall", "install", "postinstall", "prepare", "prepublish")


def analyse_package_json(text: str) -> dict:
    try:
        d = json.loads(text)
    except Exception:
        return {"scripts": {}, "deps": 0}
    sc = {k: v for k, v in (d.get("scripts") or {}).items() if k in _LIFECYCLE}
    return {"scripts": sc, "deps": len(d.get("dependencies") or {}) + len(d.get("devDependencies") or {}),
            "start": (d.get("scripts") or {}).get("start")}


def detect_kind(files: set[str]) -> list[str]:
    kinds = []
    if files & {"requirements.txt", "pyproject.toml", "setup.py", "setup.cfg"}:
        kinds.append("python")
    if "package.json" in files:
        kinds.append("node")
    for f, k in (("cargo.toml", "rust"), ("go.mod", "go"), ("dockerfile", "docker"), ("docker-compose.yml", "docker"),
                 ("makefile", "make"), ("cmakelists.txt", "cmake")):
        if f in {x.lower() for x in files}:
            kinds.append(k)
    return kinds


def venv_python(target: Path) -> str:
    return str(target / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))


def build_plan(target: Path, files: dict[str, str], sys_python: str | None = None) -> dict:
    """files: name -> content for the setup files found at the repo root. Returns
    {commands:[{argv,cwd,why}], warnings:[], manual:[], kinds:[]}. Only supported, contained steps become commands."""
    py = sys_python or sys.executable
    names = set(files)
    plan = {"commands": [], "warnings": [], "manual": [], "kinds": detect_kind(names)}
    if "python" in plan["kinds"]:
        plan["commands"].append({"argv": [py, "-m", "venv", ".venv"], "cwd": str(target),
                                 "why": "create an isolated Python environment inside the project"})
        vpy = venv_python(target)
        if "requirements.txt" in files:
            a = analyse_requirements(files["requirements.txt"])
            if a["refuse"]:
                plan["warnings"].append("requirements.txt points pip at custom package servers "
                                        f"({', '.join(a['refuse'][:2])}), which can swap in malicious packages. "
                                        "I will not run that file.")
                plan["manual"].append("Review requirements.txt yourself before installing it.")
            else:
                plan["commands"].append({"argv": [vpy, "-m", "pip", "install", "-r", "requirements.txt"],
                                         "cwd": str(target), "why": f"install {a['count']} Python packages into that environment"})
                if a["flags"]:
                    plan["warnings"].append("It installs some packages straight from web links or editable paths: "
                                            + ", ".join(a["flags"][:3]) + ".")
        elif names & {"pyproject.toml", "setup.py"}:
            plan["commands"].append({"argv": [vpy, "-m", "pip", "install", "."], "cwd": str(target),
                                     "why": "build and install the project from its own build script"})
            plan["warnings"].append("This runs the project's own build code (setup.py or pyproject build backend).")
    if "node" in plan["kinds"] and "package.json" in files:
        a = analyse_package_json(files["package.json"])
        plan["commands"].append({"argv": ["npm", "install", "--ignore-scripts"], "cwd": str(target),
                                 "why": f"install {a['deps']} JavaScript packages without running their install scripts"})
        if a["scripts"]:
            plan["warnings"].append("The project defines install-time scripts that I will NOT run: "
                                    + ", ".join(f"{k}: {v[:60]}" for k, v in a["scripts"].items()))
            plan["manual"].append("Some packages may need those install scripts; run them yourself only if you trust the project.")
    for k in plan["kinds"]:
        if k in ("rust", "go", "docker", "make", "cmake"):
            plan["manual"].append(f"This is a {k} project. I don't build those automatically; follow its README.")
    if not plan["kinds"]:
        plan["manual"].append("I found no standard setup file (requirements.txt, package.json...). Follow the README.")
    return plan


def plan_summary(owner: str, name: str, sha: str, target: Path, plan: dict, flags: list[str], isolation: str = "") -> str:
    """The exact text read back to the user. It is also the confirmation key, so it must be deterministic."""
    parts = [f"Installing {owner}/{name} (commit {sha[:7]}) into {target}"]
    if flags:
        parts.append("Trust notes: " + "; ".join(flags))
    if isolation:
        parts.append(isolation)
    for w in plan["warnings"]:
        parts.append("Warning: " + w)
    if plan["commands"]:
        parts.append("Commands: " + "; ".join(f"{' '.join(c['argv'][-4:] if 'pip' in c['argv'] else c['argv'])} to {c['why']}"
                                              for c in plan["commands"]))
    else:
        parts.append("It will only download the project, no setup commands")
    return ". ".join(parts)


_ENV_KEEP = {"PATH", "SYSTEMROOT", "COMSPEC", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH",
             "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA", "WINDIR", "LANG", "LC_ALL"}


def clean_env(env: dict | None = None) -> dict:
    """Run installs without FRIDAY's secrets (API keys etc.): keep only the basics."""
    src = os.environ if env is None else env
    out = {k: v for k, v in src.items() if k.upper() in _ENV_KEEP}
    out["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    out["GIT_TERMINAL_PROMPT"] = "0"
    return out


def trust_flags(meta: dict | None) -> list[str]:
    """Plain-language caution notes from public GitHub metadata. Empty list when nothing stands out."""
    if not meta:
        return ["I could not check the project's reputation on GitHub"]
    f = []
    if meta.get("archived"):
        f.append("archived, no longer maintained")
    if (meta.get("stargazers_count") or 0) < 10:
        f.append(f"only {meta.get('stargazers_count', 0)} stars")
    if not meta.get("license"):
        f.append("no license")
    if meta.get("created_at"):
        import datetime as dt
        try:
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(meta["created_at"].replace("Z", "+00:00"))).days
            if age < 30:
                f.append(f"created only {age} days ago")
        except Exception:
            pass
    return f


def trust_tier(meta: dict | None) -> str:
    """'low' (isolate it), 'normal', or 'unknown' (GitHub could not be checked)."""
    if not meta:
        return "unknown"
    weak = 0
    if (meta.get("stargazers_count") or 0) < 10:
        weak += 1
    if not meta.get("license"):
        weak += 1
    very_new = False
    if meta.get("created_at"):
        import datetime as dt
        try:
            very_new = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(
                meta["created_at"].replace("Z", "+00:00"))).days < 30
        except Exception:
            pass
    return "low" if (meta.get("archived") or very_new or weak >= 2) else "normal"


_RUN_OK_FIRST = {"python", "python3", "py", "npm", "node"}
_RUN_TOKEN = re.compile(r"^[A-Za-z0-9_./\\:=@+-]+$")
_README_RUN = re.compile(r"^\s*(?:[$>]\s*)?((?:python3?|py)\s+[\w./\\-]+\.py(?:\s+[\w./\\=:@+-]+)*)\s*$", re.M)


def validate_run_argv(argv: list[str]) -> bool:
    """Run commands are plain argument lists: allowed launchers only, no shell metacharacters."""
    if not argv:
        return False
    first = re.split(r"[\\/]", argv[0])[-1].lower()
    first = first[:-4] if first.endswith((".exe", ".cmd")) else first
    return first in _RUN_OK_FIRST and all(_RUN_TOKEN.match(a) for a in argv)


def find_run_command(files: dict[str, str], root_names: set[str], target: Path) -> tuple[list[str] | None, str]:
    """Best guess of how to start the project, plus where the guess came from. Needs a yes before it runs."""
    if "package.json" in files:
        sc = analyse_package_json(files["package.json"])
        try:
            scripts = json.loads(files["package.json"]).get("scripts") or {}
        except Exception:
            scripts = {}
        for k in ("start", "dev"):
            if k in scripts:
                return (["npm", "start"] if k == "start" else ["npm", "run", "dev"]), f"package.json script '{k}'"
    lower = {n.lower() for n in root_names}
    vpy = venv_python(target)
    readme = files.get("README.md") or files.get("readme.md") or ""
    m = _README_RUN.search(readme)
    if m:
        argv = m.group(1).split()
        argv[0] = vpy
        return argv, "the README"
    for f in ("main.py", "app.py", "run.py", "__main__.py"):
        if f in lower:
            return [vpy, f], f"the file {f}"
    return None, ""
