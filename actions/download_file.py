"""Download a file from a direct link into the user's Downloads folder (plain HTTP, no browser)."""
from __future__ import annotations

import ipaddress
import mimetypes
import re
import socket
import urllib.parse
from pathlib import Path

MAX_BYTES = 2 * 1024 ** 3
RISKY = {".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".scr", ".jar", ".apk", ".dmg", ".pkg"}


def _safe_host(url: str) -> tuple[bool, str]:
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False, "That is not an http or https link."
    try:
        for fam, *_rest, sa in socket.getaddrinfo(u.hostname, None):
            ip = ipaddress.ip_address(sa[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, "I won't download from a local or private network address."
    except Exception:
        return False, f"I couldn't reach {u.hostname}."
    return True, ""


def _filename(url: str, headers: dict, given: str = "") -> str:
    name = given.strip()
    if not name:
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', headers.get("content-disposition", ""), re.I)
        name = urllib.parse.unquote(m.group(1)) if m else Path(urllib.parse.urlparse(url).path).name
    name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .") or "download"
    if "." not in name:
        ext = mimetypes.guess_extension((headers.get("content-type") or "").split(";")[0].strip()) or ""
        name += ext
    return name[:150]


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(1, 1000):
        p = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not p.exists():
            return p
    return path


# Official download pages. A direct link is only ever taken if its host belongs to the listed domains.
OFFICIAL = {
    "claude":   ("https://claude.com/download", ("claude.com", "claude.ai", "anthropic.com")),
    "chatgpt":  ("https://openai.com/chatgpt/download/", ("openai.com", "chatgpt.com", "oaiusercontent.com")),
    "chrome":   ("https://www.google.com/chrome/", ("google.com", "gstatic.com")),
    "firefox":  ("https://www.mozilla.org/firefox/new/", ("mozilla.org", "mozilla.net")),
    "vscode":   ("https://code.visualstudio.com/download", ("visualstudio.com", "microsoft.com", "vo.msecnd.net")),
    "visual studio code": ("https://code.visualstudio.com/download", ("visualstudio.com", "microsoft.com", "vo.msecnd.net")),
    "spotify":  ("https://www.spotify.com/download/windows/", ("spotify.com", "scdn.co")),
    "vlc":      ("https://www.videolan.org/vlc/download-windows.html", ("videolan.org",)),
    "zoom":     ("https://zoom.us/download", ("zoom.us", "zoom.com")),
    "telegram": ("https://desktop.telegram.org/", ("telegram.org",)),
    "discord":  ("https://discord.com/download", ("discord.com", "discordapp.net")),
    "slack":    ("https://slack.com/downloads/windows", ("slack.com", "slack-edge.com")),
    "notion":   ("https://www.notion.com/desktop", ("notion.com", "notion.so")),
    "obsidian": ("https://obsidian.md/download", ("obsidian.md", "github.com")),
    "7zip":     ("https://www.7-zip.org/download.html", ("7-zip.org",)),
    "python":   ("https://www.python.org/downloads/windows/", ("python.org",)),
}
INSTALLER_EXT = (".exe", ".msi", ".msix", ".msixbundle", ".appx")


def _host_ok(url: str, domains) -> bool:
    h = (urllib.parse.urlparse(url).hostname or "").lower()
    return any(h == d or h.endswith("." + d) for d in domains)


def pick_installer(html: str, page_url: str, domains, machine: str = "x64"):
    """First Windows installer link on the official page, preferring the user's CPU. Official hosts only."""
    links = re.findall(r'(?:href|src|url)=["\']([^"\']+)["\']', html or "", re.I)
    links += re.findall(r'https?://[^\s"\'<>)\\]+', html or "")
    cands = []
    for l in links:
        u = urllib.parse.urljoin(page_url, l.replace("&amp;", "&"))
        path = urllib.parse.urlparse(u).path.lower()
        if path.endswith(INSTALLER_EXT) and _host_ok(u, domains) and "mac" not in path and "linux" not in path \
                and not re.search(r"science|beta|insider|canary|nightly|preview|alpha|enterprise|admin|server", path):
            cands.append(u)
    arm = "arm" in machine.lower()
    def score(u):
        x = u.lower()
        return (("arm" in x) == arm, "x64" in x or "x86_64" in x or "win64" in x, "win" in x)
    return sorted(dict.fromkeys(cands), key=score, reverse=True)[0] if cands else None


def resolve_official(app: str):
    """(official_page, direct_installer_or_None, domains). (None, None, ()) when the official site is not known."""
    import platform
    key = re.sub(r"\b(desktop|app|application|for windows)\b", "", app.lower()).strip()
    entry = OFFICIAL.get(key)
    if not entry:
        return None, None, ()
    page, domains = entry
    direct = None
    try:
        import requests
        r = requests.get(page, timeout=20, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FRIDAY-Desktop"})
        if r.ok and _host_ok(r.url, domains):
            direct = pick_installer(r.text, r.url, domains, platform.machine())
    except Exception:
        pass
    return page, direct, domains


def download_file(parameters=None, response=None, player=None, session_memory=None) -> str:
    p = parameters or {}
    url = (p.get("url") or "").strip()
    app = (p.get("app") or "").strip()
    if app and not url:
        page, direct, _d = resolve_official(app)
        if not page:
            return (f"I don't have a verified official download site for '{app}', and I only download from official sites, "
                    f"never third-party download sites. Ask the user for the official link, or offer to search and open "
                    f"the publisher's own site so they can pick the file.")
        if not direct:
            try:
                import webbrowser; webbrowser.open(page)
            except Exception:
                pass
            return (f"The official {app} page is {page}, but it does not expose a direct installer link to automated "
                    f"downloads, so it needs a click. I opened the page in the browser. Tell the user to press the "
                    f"Windows download button there. I downloaded nothing.")
        url = direct
    if not url:
        return ("[NEED_INFO] I have NOT downloaded anything. I need a direct file link. If the user only named a "
                "file or program, use web_search to find the official download link first, then call this tool.")
    ok, why = _safe_host(url)
    if not ok:
        return f"Sorry, I did not download anything. {why}"
    try:
        import requests
        dest_dir = Path(p.get("folder") or Path.home() / "Downloads")
        dest_dir.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=30, allow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 FRIDAY-Desktop"}) as r:
            if r.status_code in (401, 403):
                return (f"Sorry, that site refused the download (HTTP {r.status_code}). It likely needs a login or a "
                        f"human check in the browser, so I did not download it.")
            r.raise_for_status()
            ok, why = _safe_host(r.url)
            if not ok:
                return f"Sorry, I did not download anything. {why}"
            ctype = (r.headers.get("content-type") or "").lower()
            if "text/html" in ctype and not p.get("filename"):
                return ("That link is a web page, not a file, so I did not download it. It probably has a download "
                        "button. I can open the page in the browser so the user can click it.")
            size = int(r.headers.get("content-length") or 0)
            if size > MAX_BYTES:
                return f"Sorry, that file is {size // 1024**2} MB, over my 2 GB limit. I did not download it."
            target = _unique(dest_dir / _filename(r.url, {k.lower(): v for k, v in r.headers.items()}, p.get("filename", "")))
            got = 0
            with open(target, "wb") as f:
                for chunk in r.iter_content(1024 * 256):
                    got += len(chunk)
                    if got > MAX_BYTES:
                        f.close(); target.unlink(missing_ok=True)
                        return "Sorry, the file grew past my 2 GB limit, so I stopped and deleted it."
                    f.write(chunk)
        if player:
            player.write_log(f"[download] {target.name}")
        warn = " I did not open it. Only run installers from sources you trust." if target.suffix.lower() in RISKY else ""
        return f"Downloaded {target.name} ({got / 1024**2:.1f} MB) to {target.parent}.{warn}"
    except Exception as e:
        return f"Sorry, the download failed: {str(e)[:150]}. Nothing was saved."


TOOL = {
    "name": "download_file",
    "description": ("Downloads a file, or an app installer from the publisher's official site (app=...), into the user's Downloads folder. Use whenever the user asks "
                    "to download something. If you only have a name, find the official link with web_search first. "
                    "Never claim a download happened unless this tool says 'Downloaded'."),
    "parameters": {"type": "OBJECT", "properties": {
        "url": {"type": "STRING", "description": "Direct link to the file (omit when using app)"},
        "app": {"type": "STRING", "description": "App name to download from its OFFICIAL site, e.g. 'Claude'. Preferred for installers."},
        "filename": {"type": "STRING", "description": "Optional file name to save as"},
    }, "required": []},
    "handler": download_file,
}
