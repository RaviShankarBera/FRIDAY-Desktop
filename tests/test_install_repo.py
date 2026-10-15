import json
import os
import subprocess
from pathlib import Path

import pytest

from core import confirm, interactive
from core import repo_install as ri


def test_parse_repo():
    assert ri.parse_repo("https://github.com/psf/requests") == ("psf", "requests")
    assert ri.parse_repo("github.com/psf/requests.git") == ("psf", "requests")
    assert ri.parse_repo("psf/requests") == ("psf", "requests")
    assert ri.parse_repo("https://github.com/psf/requests/tree/main") == ("psf", "requests")
    for bad in ["https://evil.com/psf/requests", "git@github.com:psf/requests.git", "../x", "C:\\a\\b", "", "https://github.com/..//x", "file:///etc/passwd"]:
        assert ri.parse_repo(bad) is None, bad


def test_check_location(tmp_path):
    assert ri.check_location(str(tmp_path))[0]
    assert not ri.check_location("relative/dir")[0]
    assert not ri.check_location("C:\\Windows\\System32\\x" if os.name == "nt" else "/")[0]
    assert not ri.check_location("/")[0]
    assert not ri.check_location(str(Path(__file__).resolve().parent.parent / "sub"), Path(__file__).resolve().parent.parent)[0]
    assert not ri.check_location("/x/Program Files/y")[0]


def test_requirements_and_package_analysis():
    a = ri.analyse_requirements("requests==2.0\n# c\n--extra-index-url http://evil\ngit+https://x/y.git\n-e .\nnumpy\n")
    assert a["count"] == 2 and a["refuse"] and len(a["flags"]) == 2
    pj = ri.analyse_package_json(json.dumps({"scripts": {"postinstall": "node x.js", "start": "node a"}, "dependencies": {"a": "1"}}))
    assert pj["scripts"] == {"postinstall": "node x.js"} and pj["deps"] == 1


def test_plan_python_and_node(tmp_path):
    t = tmp_path / "proj"
    plan = ri.build_plan(t, {"requirements.txt": "requests\n", "package.json": json.dumps({"scripts": {"postinstall": "evil"}})}, "py")
    argvs = [c["argv"] for c in plan["commands"]]
    assert ["py", "-m", "venv", ".venv"] in argvs and ["npm", "install", "--ignore-scripts"] in argvs
    assert any("pip" in a and "-r" in a for a in argvs)
    assert plan["warnings"] and "NOT run" in plan["warnings"][0]
    assert all(c["cwd"] == str(t) for c in plan["commands"])


def test_plan_refuses_custom_index_and_flags_build(tmp_path):
    t = tmp_path / "p"
    bad = ri.build_plan(t, {"requirements.txt": "--index-url http://evil/simple\nfoo\n"}, "py")
    assert not any("pip" in c["argv"] for c in bad["commands"]) and bad["warnings"] and bad["manual"]
    py = ri.build_plan(t, {"pyproject.toml": "[project]"}, "py")
    assert any(c["argv"][-2:] == ["install", "."] for c in py["commands"]) and "build code" in py["warnings"][0]
    other = ri.build_plan(t, {}, "py")
    assert other["commands"] == [] and other["manual"]
    rust = ri.build_plan(t, {"Cargo.toml": ""}, "py")
    assert rust["commands"] == [] and "rust" in rust["manual"][0]


def test_env_has_no_secrets():
    env = ri.clean_env({"PATH": "/bin", "GEMINI_API_KEY": "secret", "ELEVENLABS_API_KEY": "s", "HOME": "/h", "TOKEN": "x"})
    assert "GEMINI_API_KEY" not in env and "TOKEN" not in env and env["PATH"] == "/bin"


def test_trust_flags():
    assert "could not check" in ri.trust_flags(None)[0]
    f = ri.trust_flags({"archived": True, "stargazers_count": 2, "license": None})
    assert len(f) == 3
    assert ri.trust_flags({"stargazers_count": 5000, "license": {"k": 1}}) == []


def test_summary_is_deterministic_and_lists_commands(tmp_path):
    plan = ri.build_plan(tmp_path / "p", {"requirements.txt": "a\n"}, "py")
    s1 = ri.plan_summary("o", "n", "abcdef123", tmp_path / "p", plan, ["no license"])
    assert s1 == ri.plan_summary("o", "n", "abcdef123", tmp_path / "p", plan, ["no license"])
    assert "abcdef1" in s1 and "venv" in s1 and "no license" in s1


def _local_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "requirements.txt").write_text("")
    (src / "README.md").write_text("# Install\npip install x\n")
    for c in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"]):
        subprocess.run(["git", *c], cwd=src, check=True)
    return src


def test_install_flow_needs_info_then_readback_then_runs(tmp_path, monkeypatch):
    from actions import install_repo as ir
    confirm.bind(lambda t, d: None, lambda: None); confirm._pending = None
    r = ir.install_repo({})
    assert r.startswith("[NEED_INFO]")
    r = ir.install_repo({"repo": "psf/requests"})
    assert r.startswith("[NEED_INFO]") and "drive or folder" in r
    assert "Sorry" in ir.install_repo({"repo": "psf/requests", "location": "relative"})
    src = _local_repo(tmp_path)
    ran = []

    def fake_clone(owner, name, dest):
        subprocess.run(["git", "clone", "-q", str(src), str(dest)], check=True)
        return True, "", subprocess.run(["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr(ir, "_clone", fake_clone)
    monkeypatch.setattr(ir, "_meta", lambda o, n: {"stargazers_count": 9999, "license": {"k": 1}})
    real_run = subprocess.run
    monkeypatch.setattr(ir.subprocess, "run", lambda argv, **kw: (ran.append(argv) or subprocess.CompletedProcess(argv, 0, "", "")) if argv and "venv" in argv or (argv and "pip" in argv) else real_run(argv, **kw))
    dest = tmp_path / "apps"
    params = {"repo": "https://github.com/o/proj", "location": str(dest)}
    hold = ir.install_repo(params)
    assert hold.startswith("[CONFIRMATION_PENDING]") and "venv" in hold and not (dest / "proj").exists() and not ran
    confirm.resolve(True)
    _wait(lambda: (dest / "proj" / "requirements.txt").exists() and any("pip" in a for a in ran))
    assert (dest / "proj" / "requirements.txt").exists()
    assert any("venv" in a for a in ran) and any("pip" in a for a in ran)
    assert ir.install_repo(params).startswith("Sorry")        # already exists


def _wait(cond, t=5.0):
    import time
    end = time.time() + t
    while time.time() < end and not cond():
        time.sleep(0.02)
    return cond()


def test_trust_tier():
    assert ri.trust_tier(None) == "unknown"
    assert ri.trust_tier({"stargazers_count": 5000, "license": {"k": 1}}) == "normal"
    assert ri.trust_tier({"stargazers_count": 2, "license": None}) == "low"
    assert ri.trust_tier({"stargazers_count": 50, "license": None}) == "normal"
    assert ri.trust_tier({"stargazers_count": 5000, "license": {"k": 1}, "archived": True}) == "low"
    import datetime as dt
    new = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).isoformat()
    assert ri.trust_tier({"stargazers_count": 5000, "license": {"k": 1}, "created_at": new}) == "low"


def test_run_command_detection(tmp_path):
    a, why = ri.find_run_command({"package.json": json.dumps({"scripts": {"start": "node x"}})}, {"package.json"}, tmp_path)
    assert a == ["npm", "start"] and "package.json" in why
    a, why = ri.find_run_command({"README.md": "## Usage\n```\npython app.py --port 8000\n```\n"}, {"app.py"}, tmp_path)
    assert a[1:] == ["app.py", "--port", "8000"] and "venv" in a[0].lower() and why == "the README"
    a, _ = ri.find_run_command({}, {"main.py"}, tmp_path)
    assert a[1:] == ["main.py"]
    assert ri.find_run_command({}, {"x.txt"}, tmp_path)[0] is None
    # a README line with shell tricks is not picked up as a command
    a, _ = ri.find_run_command({"README.md": "python evil.py; rm -rf ~\n"}, set(), tmp_path)
    assert a is None


def test_validate_run_argv():
    assert ri.validate_run_argv(["npm", "start"]) and ri.validate_run_argv(["python", "app.py", "--p=1"])
    assert ri.validate_run_argv([r"D:\Apps\x\.venv\Scripts\python.exe", "main.py"])
    for bad in (["bash", "x.sh"], ["python", "a.py;", "ls"], ["python", "$(x)"], ["npm", "start&&calc"], [], ["powershell", "-c", "x"]):
        assert not ri.validate_run_argv(bad), bad


def test_sandbox_generators(tmp_path):
    from core import sandbox as sbx
    wsb = sbx.render_wsb(r"D:\Apps\proj", r"D:\Apps\.friday_sandbox\proj")
    assert "<ReadOnly>true</ReadOnly>" in wsb and wsb.count("<MappedFolder>") == 2 and "<ClipboardRedirection>Disable" in wsb
    assert "friday_out\\run.ps1" in wsb
    ps = sbx.render_ps1(["python"], True, False, ["python", "app.py"])
    assert "pip install -r requirements.txt" in ps and "python.org" in ps and ".\\.venv\\Scripts\\python.exe app.py" in ps
    assert "FRIDAY_SANDBOX_DONE" in ps and "Copy-Item" in ps
    assert "npm install --ignore-scripts" in sbx.render_ps1(["node"], False, False, None)
    with pytest.raises(ValueError):
        sbx.render_ps1(["python"], True, False, ["python", "a.py; Remove-Item C:\\ -Recurse"])
    assert "<HostFolder>D:\\a&amp;b</HostFolder>" in sbx.render_wsb("D:\\a&b", "D:\\o")
    assert sbx.available() is False and "Pro" in sbx.UNAVAILABLE_HELP        # this CI box is Linux


def test_low_trust_without_sandbox_says_so_and_run_gate(tmp_path, monkeypatch):
    from actions import install_repo as ir, run_project as rp
    confirm.bind(lambda t, d: None, lambda: None); confirm._pending = None
    src = _local_repo(tmp_path)

    def fake_clone(owner, name, dest):
        subprocess.run(["git", "clone", "-q", str(src), str(dest)], check=True)
        return True, "", subprocess.run(["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr(ir, "_clone", fake_clone)
    monkeypatch.setattr(ir, "_meta", lambda o, n: {"stargazers_count": 0, "license": None})
    r = ir.install_repo({"repo": "o/low", "location": str(tmp_path / "apps")})
    assert r.startswith("[CONFIRMATION_PENDING]") and "low-trust" in r and "cannot isolate" in r and "Windows Sandbox" in r
    confirm.resolve(False)
    # run_project: needs read-back, then runs; marker says low-trust so the warning is spoken
    proj = tmp_path / "apps" / "low"
    proj.mkdir(parents=True)
    (proj / "main.py").write_text("print('hello from project')")
    ir._write_marker(proj.parent, "low", {"tier": "low"})
    vpy = proj / ".venv" / "bin" / "python"
    vpy.parent.mkdir(parents=True)
    import sys
    os.symlink(sys.executable, vpy)
    monkeypatch.setattr(ri.os, "name", "posix")
    g = rp.run_project({"folder": str(proj), "wait": "2"})
    assert g.startswith("[CONFIRMATION_PENDING]") and "NOT isolated" in g and "main.py" in g
    confirm.resolve(True)
    log = proj / ".friday_run.log"
    assert _wait(lambda: log.exists() and "hello from project" in log.read_text())
    assert rp.run_project({"folder": str(proj / "nope")}).startswith("Sorry")
