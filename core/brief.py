"""Morning voice brief: calendar, mail, weather and news, spoken at the start of the day.

Free sources only: Google Calendar / Gmail through the user's own OAuth token (optional, local),
Open-Meteo for weather, Google News RSS for headlines. Every source is optional and fails
alone: the brief says plainly what it could not reach and never invents anything.
Nothing here sends mail or replies; mail is read-only (gmail.readonly scope).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

BASE = Path(__file__).resolve().parent.parent
GOOGLE_DIR = BASE / "config" / "google"
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly",
          "https://www.googleapis.com/auth/gmail.readonly"]

NEWS_FEEDS = {
    "India": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
    "India tech": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-IN&gl=IN&ceid=IN:en",
    "World": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-IN&gl=IN&ceid=IN:en",
}


def _get(url: str, timeout: float = 10) -> str:
    import requests
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "FRIDAY/1.0"})
    r.raise_for_status()
    return r.text


# ---- news ----
def parse_rss(xml_text: str, limit: int = 5) -> list[dict]:
    out = []
    root = ET.fromstring(xml_text)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        if title:
            out.append({"title": title, "source": src, "link": (it.findtext("link") or "").strip()})
        if len(out) >= limit:
            break
    return out


def fetch_news(fetch: Callable[[str], str] = _get, india: int = 10, world: int = 5) -> tuple[list[dict], list[dict]]:
    ind = parse_rss(fetch(NEWS_FEEDS["India"]), india)
    wld = parse_rss(fetch(NEWS_FEEDS["World"]), world)
    return ind, wld


# ---- weather ----
def fetch_weather(city: str, fetch: Callable[[str], str] = _get) -> str:
    from urllib.parse import quote
    g = json.loads(fetch(f"https://geocoding-api.open-meteo.com/v1/search?name={quote(city)}&count=1"))
    res = (g.get("results") or [None])[0]
    if not res:
        raise RuntimeError(f"city '{city}' not found")
    w = json.loads(fetch(
        f"https://api.open-meteo.com/v1/forecast?latitude={res['latitude']}&longitude={res['longitude']}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&current=temperature_2m"
        "&timezone=auto&forecast_days=1"))
    d = w["daily"]
    return (f"{res['name']}: now {round(w['current']['temperature_2m'])}°C, today {round(d['temperature_2m_min'][0])} to "
            f"{round(d['temperature_2m_max'][0])}°C, rain chance {d['precipitation_probability_max'][0]}%")


# ---- google (optional) ----
def _google_creds():
    tok = GOOGLE_DIR / "token.json"
    if not tok.exists():
        raise RuntimeError("Google is not connected on this PC")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    c = Credentials.from_authorized_user_file(str(tok), SCOPES)
    if c.expired and c.refresh_token:
        c.refresh(Request())
        tok.write_text(c.to_json(), encoding="utf-8")
    return c


def connect_google() -> str:
    """One-time OAuth in the browser. Needs config/google/client_secret.json (your own free Google Cloud OAuth client)."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    cs = GOOGLE_DIR / "client_secret.json"
    if not cs.exists():
        return ("Put your Google OAuth 'Desktop app' client file at config/google/client_secret.json first "
                "(console.cloud.google.com, enable Gmail + Calendar APIs, free).")
    creds = InstalledAppFlow.from_client_secrets_file(str(cs), SCOPES).run_local_server(port=0)
    (GOOGLE_DIR / "token.json").write_text(creds.to_json(), encoding="utf-8")
    return "Google connected. Read-only: calendar and mail."


def fetch_calendar(now: dt.datetime | None = None) -> list[dict]:
    from googleapiclient.discovery import build
    now = (now or dt.datetime.now().astimezone())
    end = now.replace(hour=23, minute=59, second=59)
    svc = build("calendar", "v3", credentials=_google_creds(), cache_discovery=False)
    items = svc.events().list(calendarId="primary", timeMin=now.isoformat(), timeMax=end.isoformat(),
                              singleEvents=True, orderBy="startTime", maxResults=10).execute().get("items", [])
    out = []
    for e in items:
        s = e.get("start", {})
        out.append({"title": e.get("summary", "(no title)"), "start": s.get("dateTime") or s.get("date", "")})
    return out


def fetch_mail(limit: int = 5) -> list[dict]:
    from googleapiclient.discovery import build
    svc = build("gmail", "v1", credentials=_google_creds(), cache_discovery=False)
    ids = svc.users().messages().list(userId="me", q="is:unread newer_than:1d category:primary",
                                      maxResults=limit).execute().get("messages", [])
    out = []
    for m in ids:
        h = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                       metadataHeaders=["From", "Subject"]).execute()
        hd = {x["name"]: x["value"] for x in h["payload"]["headers"]}
        out.append({"from": re.sub(r"<.*?>", "", hd.get("From", "")).strip().strip('"'), "subject": hd.get("Subject", "")})
    return out


def _hm(iso: str) -> str:
    try:
        return dt.datetime.fromisoformat(iso).strftime("%I:%M %p").lstrip("0")
    except Exception:
        return "all day"


def build_brief(sources: dict[str, Callable], now: dt.datetime | None = None, name: str = "") -> str:
    """sources: calendar/mail/weather/news callables. Returns the spoken text. Plain template, no LLM,
    so it is accurate by construction (numbers and headlines are copied, not paraphrased)."""
    now = now or dt.datetime.now()
    parts = [f"Good morning{(' ' + name) if name else ''}. It is {now.strftime('%A, %d %B')}."]
    missing = []

    def run(key):
        try:
            return sources[key]()
        except Exception as e:                       # noqa: BLE001
            missing.append(f"{key} ({str(e)[:50]})")
            return None

    if "weather" in sources and (w := run("weather")):
        parts.append("Weather. " + w + ".")
    if "calendar" in sources and (cal := run("calendar")) is not None:
        if cal:
            parts.append("Today you have " + "; ".join(f"{e['title']} at {_hm(e['start'])}" for e in cal[:6]) + ".")
        else:
            parts.append("Your calendar is clear for the rest of today.")
    if "mail" in sources and (ml := run("mail")) is not None:
        if ml:
            parts.append(f"{len(ml)} unread in your inbox. Latest: " +
                         "; ".join(f"{m['from']}, {m['subject']}" for m in ml[:3]) + ".")
        else:
            parts.append("No new unread mail.")
    if "news" in sources and (nw := run("news")):
        ind, wld = nw
        if ind:
            parts.append("India. " + " ".join(f"{i}. {n['title']}." for i, n in enumerate(ind, 1)))
        if wld:
            parts.append("World. " + " ".join(f"{i}. {n['title']}." for i, n in enumerate(wld, 1)))
    if missing:
        parts.append("I could not reach: " + ", ".join(missing) + ".")
    return " ".join(parts)


def default_sources(cfg: dict) -> dict[str, Callable]:
    src: dict[str, Callable] = {"news": fetch_news}
    if cfg.get("home_city"):
        src["weather"] = lambda: fetch_weather(cfg["home_city"])
    if (GOOGLE_DIR / "token.json").exists():
        src["calendar"] = fetch_calendar
        src["mail"] = fetch_mail
    else:
        src["calendar"] = lambda: (_ for _ in ()).throw(RuntimeError("Google not connected, say 'connect google'"))
    return src


def should_auto_brief(cfg: dict, now: dt.datetime, state_path: Path | None = None) -> bool:
    """True once per day, after brief_hour (default 6), if auto brief is enabled in config (default off)."""
    if not cfg.get("morning_brief_auto", False):
        return False
    if now.hour < int(cfg.get("brief_hour", 6)):
        return False
    p = state_path or (BASE / "config" / "bridge_state.json")
    try:
        st = json.loads(p.read_text())
    except Exception:
        st = {}
    return st.get("last_brief") != now.strftime("%Y-%m-%d")


def mark_briefed(now: dt.datetime, state_path: Path | None = None) -> None:
    p = state_path or (BASE / "config" / "bridge_state.json")
    try:
        st = json.loads(p.read_text())
    except Exception:
        st = {}
    st["last_brief"] = now.strftime("%Y-%m-%d")
    p.write_text(json.dumps(st))
