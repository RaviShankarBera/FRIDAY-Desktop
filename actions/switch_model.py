"""switch_model: change which free model FRIDAY's agent uses ("Friday, switch to NVIDIA")."""
from __future__ import annotations


def switch_model(parameters: dict, player=None) -> str:
    from core import providers
    name = str((parameters or {}).get("provider", "")).strip()
    if not name:
        st = providers.status()
        return "Models: " + ", ".join(f"{providers.SPECS[k].label} ({v})" for k, v in st.items())
    return providers.set_active(name)


TOOL = {
    "name": "switch_model",
    "description": ("Switch the active AI model provider for FRIDAY's agent tasks (gemini or nvidia). "
                    "Call with no provider to list them. Paid providers are never used in free-only mode."),
    "parameters": {"type": "OBJECT", "properties": {
        "provider": {"type": "STRING", "description": "gemini or nvidia."}}},
    "handler": switch_model,
}
