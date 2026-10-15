"""Windows Sandbox support: availability check and generators for the .wsb config and the in-sandbox script.

Windows Sandbox is a disposable, isolated Windows. It exists on Windows 10/11 Pro, Enterprise and Education only,
and the optional feature must be switched on. Everything here is pure text generation except available() and launch().
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

PY_URL = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
NODE_URL = "https://nodejs.org/dist/v20.18.0/node-v20.18.0-x64.msi"
GUEST_HOME = r"C:\Users\WDAGUtilityAccount\Desktop"
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_./\\:=@+-]+$")


def exe_path() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsSandbox.exe"


def available() -> bool:
    return os.name == "nt" and exe_path().exists()


UNAVAILABLE_HELP = ("Windows Sandbox isn't available on this PC. It needs Windows 10 or 11 Pro, Enterprise or Education "
                    "with the 'Windows Sandbox' optional feature turned on (Turn Windows features on or off, then restart).")


def safe_args(argv: list[str]) -> bool:
    return bool(argv) and all(_SAFE_TOKEN.match(a) for a in argv)


def render_wsb(repo_dir: str, out_dir: str, script_name: str = "run.ps1") -> str:
    """Config: networking on (needed to download Python and packages), repo mounted READ-ONLY, one writable out folder."""
    return f"""<Configuration>
  <VGpu>Disable</VGpu>
  <Networking>Enable</Networking>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <PrinterRedirection>Disable</PrinterRedirection>
  <AudioInput>Disable</AudioInput>
  <VideoInput>Disable</VideoInput>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>{escape(repo_dir)}</HostFolder>
      <SandboxFolder>{GUEST_HOME}\\repo_src</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>{escape(out_dir)}</HostFolder>
      <SandboxFolder>{GUEST_HOME}\\friday_out</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell -NoProfile -ExecutionPolicy Bypass -File {GUEST_HOME}\\friday_out\\{script_name}</Command>
  </LogonCommand>
</Configuration>
"""


def render_ps1(kinds: list[str], has_requirements: bool, has_pyproject: bool, run_argv: list[str] | None = None) -> str:
    """The in-sandbox script. Every command is fixed text; only run_argv (validated) is variable."""
    if run_argv is not None and not safe_args(run_argv):
        raise ValueError("unsafe run command")
    L = ["$ErrorActionPreference = 'Continue'",
         f"$out = '{GUEST_HOME}\\friday_out'", "Start-Transcript -Path \"$out\\log.txt\" -Force | Out-Null",
         f"Copy-Item '{GUEST_HOME}\\repo_src' 'C:\\work' -Recurse -Force", "Set-Location C:\\work"]
    if "python" in kinds:
        L += [f"Invoke-WebRequest '{PY_URL}' -OutFile \"$env:TEMP\\py.exe\"",
              "Start-Process \"$env:TEMP\\py.exe\" -ArgumentList '/quiet','InstallAllUsers=1','PrependPath=1' -Wait",
              "$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine')",
              "python -m venv .venv"]
        if has_requirements:
            L.append(".\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        elif has_pyproject:
            L.append(".\\.venv\\Scripts\\python.exe -m pip install .")
    if "node" in kinds:
        L += [f"Invoke-WebRequest '{NODE_URL}' -OutFile \"$env:TEMP\\node.msi\"",
              "Start-Process msiexec -ArgumentList '/i',\"$env:TEMP\\node.msi\",'/qn' -Wait",
              "$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine')",
              "npm install --ignore-scripts"]
    if run_argv:
        a = list(run_argv)
        if a[0].lower() in ("python", "python3", "py"):
            a[0] = ".\\.venv\\Scripts\\python.exe"
        L.append("Write-Output 'RUNNING: " + " ".join(a) + "'")
        L.append("& " + " ".join(a))
    L += ["Write-Output 'FRIDAY_SANDBOX_DONE'", "Stop-Transcript | Out-Null"]
    return "\r\n".join(L) + "\r\n"


def launch(wsb_path: Path) -> tuple[bool, str]:
    if not available():
        return False, UNAVAILABLE_HELP
    try:
        subprocess.Popen([str(exe_path()), str(wsb_path)])
        return True, ""
    except Exception as e:
        return False, f"Could not start Windows Sandbox: {str(e)[:150]}"
