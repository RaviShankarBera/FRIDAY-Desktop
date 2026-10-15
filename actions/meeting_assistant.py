"""meeting_assistant: "Friday, start recording the meeting" ... "stop" -> transcript, summary, action items."""
from __future__ import annotations


def meeting_assistant(parameters: dict, player=None) -> str:
    from core import meeting
    from core.providers import load_config
    act = str((parameters or {}).get("action") or "").strip().lower()
    rec = meeting.recorder()
    try:
        if act in ("start", "record", "begin"):
            if rec.active:
                return f"Already recording ({rec.seconds() // 60} minutes so far)."
            rec.device = load_config().get("meeting_device") or None
            rec.start()
            return ("Recording started from your microphone. Tell everyone you are recording. "
                    "Say 'stop recording' when done.")
        if act == "status":
            return f"Recording, {rec.seconds() // 60} min {rec.seconds() % 60} sec so far." if rec.active else "Not recording."
        if act in ("stop", "end", "finish", "summary"):
            if not rec.active:
                return "I am not recording right now."
            started = rec.started_at
            pcm = rec.stop()
            res = meeting.process(pcm, started, meeting.gemini_transcribe, meeting.gemini_summarise)
            return f"Meeting saved to {res['dir']}.\n{res['summary']}"
    except ValueError as e:
        return f"Sorry, {e}"
    except Exception as e:                           # noqa: BLE001
        return f"Sorry, the meeting assistant failed: {e}"
    return "Say start or stop: 'start recording the meeting' or 'stop recording'."


TOOL = {
    "name": "meeting_assistant",
    "description": ("Records the meeting from the microphone, then transcribes it and writes a summary with decisions "
                    "and action items (saved under meetings/ on this PC). action=start, stop (returns the summary), "
                    "or status. Use for 'record this meeting', 'stop recording', 'summarise the meeting'. "
                    "Remind the user to tell participants they are being recorded."),
    "parameters": {"type": "OBJECT", "properties": {
        "action": {"type": "STRING", "description": "start | stop | status"}}, "required": ["action"]},
    "handler": meeting_assistant,
}
