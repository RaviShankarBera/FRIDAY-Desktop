"""Park an action with side effects behind the on-screen confirmation, which only the user can answer.

The model never confirms anything. A tool that needs approval builds the exact action as a closure (`run`) with every
parameter already captured, and hands it to park(). park() puts a CONFIRM / CANCEL banner on the HUD (core/confirm.py) and
returns text telling the model to read the request back. The closure runs ONLY when the UI calls confirm.resolve(True),
i.e. the user pressed CONFIRM or said "yes" and the voice path forwarded it. There is no tool parameter that can approve it,
and calling the tool again just parks a new request in place of the old one.
"""
from __future__ import annotations

from typing import Callable

from core import confirm


def park(tool: str, summary: str, run: Callable[[], str], speak: Callable[[str], None] | None = None) -> str:
    """Returns the text for the model. Nothing has run when this returns."""
    if confirm.pending_title():
        return ("There is already a confirmation waiting on screen. Ask the user to answer that one first. "
                "I have NOT done this request.")

    def _run() -> str:
        result = run() or "Done."
        if speak:
            try:
                speak(str(result)[:300])
            except Exception:
                pass
        return str(result)

    title = summary if len(summary) <= 90 else summary[:87] + "..."
    out = confirm.request(key=tool, title=title, detail=summary, run=_run)
    if out.startswith("[CONFIRMATION_PENDING]"):
        return (f"[CONFIRMATION_PENDING] I have NOT done this yet. A confirmation is on the user's screen: \"{summary}\". "
                "Read that request back in one short sentence and ask them to say yes or press CONFIRM. "
                "Never say it is done and never call this tool again to 'confirm' - only the user can.")
    return out
