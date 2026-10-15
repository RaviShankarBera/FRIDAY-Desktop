#web_search.py
import json
import sys
from pathlib import Path

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _gemini_search(query: str) -> str:
    from google import genai

    client   = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(
        model="gemini-flash-latest",
        contents=query,
        config={"tools": [{"google_search": {}}]},
    )

    text = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            text += part.text

    text = text.strip()
    if not text:
        raise ValueError("Gemini returned an empty response.")
    return text


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title":   r.get("title",  ""),
                "snippet": r.get("body",   ""),
                "url":     r.get("href",   ""),
            })
    return results


def _ddg_news(query: str, max_results: int = 8) -> list[dict]:
    """DDG news search — returns actual articles, not website homepages."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.news(query, max_results=max_results):
                results.append({
                    "title":   r.get("title",  ""),
                    "snippet": r.get("body",   ""),
                    "url":     r.get("url",    ""),
                    "source":  r.get("source", ""),
                })
    except Exception as e:
        print(f"[WebSearch] ⚠️ DDG news() failed ({e}) — falling back to text search")
        results = _ddg_search(query, max_results=max_results)
    return results


def _rss_news(query: str, max_results: int = 8) -> list[dict]:
    """Google News RSS: free, no key, no extra package. Last-resort backend that almost always works."""
    import requests
    from urllib.parse import quote_plus
    from core.brief import parse_rss
    q = query.strip() or "top news"
    url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-IN&gl=IN&ceid=IN:en"
    r = requests.get(url, timeout=12, headers={"User-Agent": "FRIDAY/1.0"})
    r.raise_for_status()
    return [{"title": i["title"], "snippet": "", "url": i["link"], "source": i["source"]}
            for i in parse_rss(r.text, max_results)]


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   Source: {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_news(query: str, results: list[dict]) -> str:
    if not results:
        return f"No news found for: {query}"

    lines = [f"Latest news: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        if not title:
            continue
        src = f"  [{r['source']}]" if r.get("source") else ""
        lines.append(f"{i}. {title}{src}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:140]}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


# ── Briefing helper ────────────────────────────────────────────────────────────

def _gemini_headlines(n: int = 5) -> tuple[list[str], str]:
    """
    Fetches current headlines via Gemini grounded search.
    Optimised for speed: minimal prompt + strict token cap.
    Returns (headline_list, raw_text_for_display).
    """
    import re
    from google import genai

    client = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(
        model="gemini-flash-latest",
        contents=f"Current world news: {n} headlines. Numbered list, titles only.",
        config={"tools": [{"google_search": {}}]},
    )

    raw = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            raw += part.text

    headlines = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Only accept lines that begin with a number — skips preamble/closing sentences
        if not re.match(r'^[\d]+[.\)\-]', line):
            continue
        clean = re.sub(r'^[\d]+[.\)\-]\s*', '', line)
        clean = re.sub(r'^\*+\s*',          '', clean).strip()
        if clean and len(clean) > 10:
            headlines.append(clean)

    return headlines[:n], raw.strip()


# ── Modes ──────────────────────────────────────────────────────────────────────

def _search(query: str) -> str:
    """Default search — Gemini grounded, DDG fallback."""
    try:
        return _gemini_search(query)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Gemini failed ({e}) — trying DDG...")
        try:
            results = _ddg_search(query)
            if results:
                return _format_ddg(query, results)
        except Exception as e2:
            print(f"[WebSearch] ⚠️ DDG failed ({e2}) — trying Google News RSS...")
        results = _rss_news(query)
        if results:
            return _format_news(query, results)
        return f"No results found for: {query}"


def _news(query: str) -> str:
    """
    Runs Gemini grounded search, DDG news and Google News RSS in parallel.
    Returns the best valid result (Gemini/DDG get a short head start over RSS).
    Waits up to 30 s: grounded Gemini search often needs 10-20 s on a free key.
    """
    import threading
    import time

    gemini_query = f"latest news today: {query}" if query else "top world news today"
    ddg_query    = query if query else "world news today"

    results = {}
    lock = threading.Lock()
    done_evt = threading.Event()
    finished = [0]
    TOTAL = 3

    def _store(name: str, r: str) -> None:
        with lock:
            finished[0] += 1
            if r and len(r) > 60 and not r.startswith("No "):
                results.setdefault(name, r)
                done_evt.set()
            elif finished[0] >= TOTAL:
                done_evt.set()

    def _try_gemini():
        try:
            _store("gemini", _gemini_search(gemini_query))
        except Exception as e:
            print(f"[WebSearch] ⚠️ Gemini news failed ({e})")
            _store("gemini", "")

    def _try_ddg():
        try:
            _store("ddg", _format_news(ddg_query, _ddg_news(ddg_query, max_results=8)))
        except Exception as e:
            print(f"[WebSearch] ⚠️ DDG news failed ({e})")
            _store("ddg", "")

    def _try_rss():
        try:
            _store("rss", _format_news(ddg_query, _rss_news(ddg_query, max_results=8)))
        except Exception as e:
            print(f"[WebSearch] ⚠️ RSS news failed ({e})")
            _store("rss", "")

    for fn in (_try_gemini, _try_ddg, _try_rss):
        threading.Thread(target=fn, daemon=True).start()

    done_evt.wait(timeout=30.0)
    if results and "gemini" not in results and "ddg" not in results:
        time.sleep(3.0)                      # RSS landed first: give the richer sources a moment
    with lock:
        for k in ("gemini", "ddg", "rss"):
            if k in results:
                return results[k]
    return f"Sorry, I could not fetch news for: {query or 'today'}. Gemini, DuckDuckGo and Google News all failed or timed out; check the internet and the FRIDAY log."


def _trim_news(text: str, n: int) -> str:
    """Keep the first n numbered items of a news list (header and format preserved)."""
    import re
    parts = re.split(r"\n(?=\d+\. )", text)
    if len(parts) <= 1:
        return text
    return "\n".join(parts[: n + 1]) if not re.match(r"\d+\. ", parts[0]) else "\n".join(parts[:n])


def _research(query: str) -> str:
    """
    Deep dive — asks Gemini for a comprehensive answer with context.
    Falls back to a wider DDG fetch.
    """
    research_query = (
        f"Comprehensive, detailed explanation of: {query}. "
        "Include background context, key facts, current state, and important nuances."
    )
    try:
        return _gemini_search(research_query)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Research Gemini failed ({e}) — DDG fallback...")
        try:
            results = _ddg_search(query, max_results=10)
            if results:
                return _format_ddg(query, results)
        except Exception as e2:
            print(f"[WebSearch] ⚠️ Research DDG failed ({e2}) — Google News RSS fallback...")
        return _news(query)


def _price(query: str) -> str:
    """Product price lookup — searches for current market prices."""
    price_query = f"current price of {query} — how much does it cost today"
    try:
        return _gemini_search(price_query)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Price Gemini failed ({e}) — DDG fallback...")
        results = _ddg_search(f"{query} price buy", max_results=6)
        return _format_ddg(query, results)


def _compare(items: list[str], aspect: str) -> str:
    query = (
        f"Compare {', '.join(items)} in terms of {aspect}. "
        "Give specific facts and data."
    )
    try:
        return _gemini_search(query)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Gemini compare failed: {e} — falling back to DDG")

    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparison — {aspect.upper()}", "─" * 40]
    for item in items:
        lines.append(f"\n▸ {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  • {r['snippet']}")
            if r.get("url"):
                lines.append(f"    {r['url']}")
    return "\n".join(lines)


# ── Public entry point ─────────────────────────────────────────────────────────

def _google_url(query: str, news: bool = False) -> str:
    from urllib.parse import quote_plus
    return f"https://www.google.com/search?q={quote_plus(query)}" + ("&tbm=nws" if news else "")


def _open_google(query: str, news: bool = False) -> bool:
    """Open Google results for `query` in the system default browser. Never raises."""
    if not query:
        return False
    try:
        import webbrowser
        return bool(webbrowser.open(_google_url(query, news)))
    except Exception as e:
        print(f"[WebSearch] could not open default browser: {e}")
        return False


def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query  = params.get("query", "").strip()
    mode   = params.get("mode",  "search").lower().strip()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"

    if not query and not items:
        return "Please provide a search query."

    if items and mode not in ("compare",):
        mode = "compare"
    import re as _re
    if mode in ("search", "research") and _re.search(r"\b(news|headlines?|breaking)\b", query, _re.I):
        mode = "news"                        # news questions need the news pipeline, not a bare Google open

    if player:
        player.write_log(f"[Search:{mode}] {query or ', '.join(items)}")

    print(f"[WebSearch] 🔍 mode={mode!r}  query={query!r}")

    # FRIDAY shows the results in the user's DEFAULT browser: open Google with
    # the query there. A short spoken summary is still returned below.
    _open_google(query or " ".join(items), news=(mode == "news"))

    try:
        if mode == "compare" and items:
            return _compare(items, aspect)
        if mode == "news":
            out = _news(query)
            m = _re.search(r"\btop\s+(\d{1,2})\b", query, _re.I)
            return _trim_news(out, int(m.group(1))) if m else out
        if mode == "research":
            return _research(query)
        if mode == "price":
            return _price(query)
        return _search(query)

    except Exception as e:
        print(f"[WebSearch] ❌ All backends failed: {e}")
        return f"Search failed: {e}"


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "web_search",
    "description": "Searches the web: opens Google with the query in the user's default browser (results are shown there) and returns a short summary to speak. Use for ANY question about current facts, events, prices, or topics — always prefer this over guessing. For news or 'top N headlines' ALWAYS use mode 'news'. The returned text is real data: read it out as a numbered summary. If the result starts with 'Sorry', say which source failed; never say you cannot find news when the tool returned items. Modes: 'search' (default), 'news' (latest headlines on a topic), 'research' (deep comprehensive answer), 'price' (product cost lookup), 'compare' (side-by-side comparison of items).",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Search query or topic"
            },
            "mode": {
                "type": "STRING",
                "description": "search | news | research | price | compare"
            },
            "items": {
                "type": "ARRAY",
                "items": {
                    "type": "STRING"
                },
                "description": "Items to compare (compare mode)"
            },
            "aspect": {
                "type": "STRING",
                "description": "Comparison aspect: price | specs | reviews | features"
            }
        },
        "required": [
            "query"
        ]
    },
    "handler": web_search,
}
