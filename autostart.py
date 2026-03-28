from pathlib import Path
import sys

AUTOSTART_DIR = Path.home() / ".config" / "autostart"
DESKTOP_FILE = AUTOSTART_DIR / "bitcoin-widget.desktop"
SCRIPT_PATH = Path(__file__).resolve().parent / "bitcoin_widget.py"


def _desktop_content():
    python = "/usr/bin/python3"
    return f"""[Desktop Entry]
Type=Application
Name=Bitcoin Widget
Exec={python} {SCRIPT_PATH}
Icon=utilities-system-monitor
Comment=Bitcoin price in system tray
X-GNOME-Autostart-enabled=true
StartupNotify=false
"""


def enable():
    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text(_desktop_content())


def disable():
    if DESKTOP_FILE.exists():
        DESKTOP_FILE.unlink()


def is_enabled() -> bool:
    return DESKTOP_FILE.exists()


if __name__ == "__main__":
    enable()
    print(f"Autostart enabled: {DESKTOP_FILE}")
