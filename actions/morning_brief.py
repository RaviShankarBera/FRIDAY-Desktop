"""morning_brief: spoken daily briefing - weather, calendar, unread mail, India + world news."""
from __future__ import annotations


def morning_brief(parameters: dict, player=None) -> str:
    from core import brief
    from core.providers import load_config
    cfg = load_config()
    if str((parameters or {}).get("action", "")).lower() == "connect_google":
        try:
            return brief.connect_google()
        except Exception as e:                       # noqa: BLE001
            return f"Sorry, Google connect failed: {e}"
    text = brief.build_brief(brief.default_sources(cfg), name=cfg.get("user_title") or "")
    brief.mark_briefed(__import__("datetime").datetime.now())
    return text


TOOL = {
    "name": "morning_brief",
    "description": ("Gives the morning briefing: date, weather for the saved home city, today's calendar, unread "
                    "mail headlines, top India and world news. Use for 'morning brief', 'daily brief', 'what's "
                    "today'. Read the returned text aloud as written; do not add facts. "
                    "action=connect_google starts the one-time read-only Google sign-in."),
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "description": "'brief' (default) or 'connect_google'."}}},
    "handler": morning_brief,
}
