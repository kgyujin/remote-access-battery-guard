"""Load, validate, and persist the user's battery-guard configuration."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .models import GuardConfig

APP_DIRECTORY_NAME = "remote-access-battery-guard"
CONFIG_FILE_NAME = "config.json"
STATE_FILE_NAME = "state.json"


def default_config_directory() -> Path:
    """Return the platform-appropriate per-user configuration directory."""

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIRECTORY_NAME
    if os.name == "nt":
        app_data = os.environ.get("APPDATA")
        return (
            Path(app_data) / APP_DIRECTORY_NAME
            if app_data
            else Path.home() / APP_DIRECTORY_NAME
        )
    config_home = os.environ.get("XDG_CONFIG_HOME")
    return (
        Path(config_home) / APP_DIRECTORY_NAME
        if config_home
        else Path.home() / ".config" / APP_DIRECTORY_NAME
    )


def default_config_path() -> Path:
    return default_config_directory() / CONFIG_FILE_NAME


def default_state_path() -> Path:
    return default_config_directory() / STATE_FILE_NAME


def load_config(path: Path | None = None) -> GuardConfig:
    """Load JSON configuration, using safe defaults when no file exists."""

    config_path = (path or default_config_path()).expanduser()
    if not config_path.exists():
        return GuardConfig()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Configuration root must be a JSON object")
    return GuardConfig.from_mapping(payload)


def resolve_state_path(config: GuardConfig) -> Path:
    """Resolve an optional state path without requiring a config file."""

    if config.state_file:
        return Path(config.state_file).expanduser()
    return default_state_path()


def save_config(path: Path, config: GuardConfig) -> None:
    """Persist a validated configuration, overwriting any existing file."""

    config_path = path.expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.to_mapping(), indent=2) + "\n",
        encoding="utf-8",
    )


def write_default_config(path: Path, *, overwrite: bool = False) -> None:
    """Create a readable starter config and refuse accidental overwrites."""

    config_path = path.expanduser()
    if config_path.exists() and not overwrite:
        raise FileExistsError(f"Configuration already exists: {config_path}")
    save_config(config_path, GuardConfig())
