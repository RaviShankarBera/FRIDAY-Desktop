# FRIDAY package: OS helpers used by several actions (flight_finder, youtube_video, game_updater).
import platform as _platform


def get_os() -> str:
    """'windows' | 'mac' | 'linux' from the machine actually running FRIDAY."""
    s = _platform.system().lower()
    if s.startswith("win"):
        return "windows"
    if s == "darwin":
        return "mac"
    return "linux"


def is_windows() -> bool:
    return get_os() == "windows"


def is_mac() -> bool:
    return get_os() == "mac"


def is_linux() -> bool:
    return get_os() == "linux"
