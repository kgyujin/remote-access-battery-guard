"""Optional per-user auto-start integration for macOS launchd."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

LAUNCH_AGENT_LABEL = "com.remote-access-battery-guard"
MENUBAR_LOGIN_ITEM_LABEL = "com.remote-access-battery-guard.menubar"


def _agent_path(label: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def launch_agent_path() -> Path:
    """Return the current user's launch-agent path for the headless `run` service."""

    return _agent_path(LAUNCH_AGENT_LABEL)


def menubar_login_item_path() -> Path:
    """Return the current user's launch-agent path for the menu bar login item."""

    return _agent_path(MENUBAR_LOGIN_ITEM_LABEL)


def _install_launch_agent(label: str, arguments: list[str], *, keep_alive: bool) -> Path:
    """Write, load, and replace any existing launchd agent with the given `label`."""

    if sys.platform != "darwin":
        raise RuntimeError("launchd agents are only available on macOS.")
    plist_path = _agent_path(label)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    log_directory = Path.home() / "Library" / "Logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": label,
        "ProgramArguments": arguments,
        "RunAtLoad": True,
        "KeepAlive": keep_alive,
        # A GUI app (the menu bar app) needs "Interactive" to keep window-server
        # access; the headless loop stays "Background" so macOS can throttle it.
        "ProcessType": "Background" if keep_alive else "Interactive",
        "StandardOutPath": str(log_directory / f"{label}.log"),
        "StandardErrorPath": str(log_directory / f"{label}.error.log"),
    }
    plist_path.write_bytes(plistlib.dumps(payload))
    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", domain, str(plist_path)],
        check=False,
        capture_output=True,
        timeout=10,
    )
    loaded = subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if loaded.returncode != 0:
        raise RuntimeError(
            loaded.stderr.strip() or "launchctl could not load the agent"
        )
    return plist_path


def _uninstall_launch_agent(label: str) -> Path:
    """Unload and delete the launchd agent identified by `label`, if any."""

    if sys.platform != "darwin":
        raise RuntimeError("launchd agents are only available on macOS.")
    plist_path = _agent_path(label)
    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", domain, str(plist_path)],
        check=False,
        capture_output=True,
        timeout=10,
    )
    plist_path.unlink(missing_ok=True)
    return plist_path


def install_macos_launch_agent(config_path: Path) -> Path:
    """Install and load a launch agent that runs the headless guard (`rabg run`)."""

    return _install_launch_agent(
        LAUNCH_AGENT_LABEL,
        [
            sys.executable,
            "-m",
            "remote_access_battery_guard",
            "--config",
            str(config_path.expanduser().resolve()),
            "run",
        ],
        keep_alive=True,
    )


def uninstall_macos_launch_agent() -> Path:
    """Unload and remove the headless guard's launch agent."""

    return _uninstall_launch_agent(LAUNCH_AGENT_LABEL)


def install_macos_menubar_login_item(config_path: Path) -> Path:
    """Install and load a login item that starts the menu bar app at login."""

    return _install_launch_agent(
        MENUBAR_LOGIN_ITEM_LABEL,
        [
            sys.executable,
            "-m",
            "remote_access_battery_guard",
            "--config",
            str(config_path.expanduser().resolve()),
            "menubar",
        ],
        keep_alive=False,
    )


def uninstall_macos_menubar_login_item() -> Path:
    """Unload and remove the menu bar app's login item."""

    return _uninstall_launch_agent(MENUBAR_LOGIN_ITEM_LABEL)


def macos_menubar_login_item_installed() -> bool:
    """Return whether the menu bar app's login item is currently installed."""

    return menubar_login_item_path().exists()
