"""Optional per-user auto-start integration for macOS launchd."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

LAUNCH_AGENT_LABEL = "com.remote-access-battery-guard"


def launch_agent_path() -> Path:
    """Return the current user's launch-agent path."""

    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


def install_macos_launch_agent(config_path: Path) -> Path:
    """Install and load a launch agent for the currently installed CLI."""

    if sys.platform != "darwin":
        raise RuntimeError("The macOS launch agent is only available on macOS.")
    plist_path = launch_agent_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    log_directory = Path.home() / "Library" / "Logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            sys.executable,
            "-m",
            "remote_access_battery_guard",
            "--config",
            str(config_path.expanduser().resolve()),
            "run",
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "StandardOutPath": str(log_directory / f"{LAUNCH_AGENT_LABEL}.log"),
        "StandardErrorPath": str(log_directory / f"{LAUNCH_AGENT_LABEL}.error.log"),
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


def uninstall_macos_launch_agent() -> Path:
    """Unload and remove the launch agent created by this project."""

    if sys.platform != "darwin":
        raise RuntimeError("The macOS launch agent is only available on macOS.")
    plist_path = launch_agent_path()
    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", domain, str(plist_path)],
        check=False,
        capture_output=True,
        timeout=10,
    )
    plist_path.unlink(missing_ok=True)
    return plist_path
