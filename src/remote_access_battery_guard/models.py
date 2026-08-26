"""Shared domain models for power state, configuration, and saved settings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PowerSource(StrEnum):
    """Power source reported by the host operating system."""

    BATTERY = "battery"
    AC = "ac"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PowerStatus:
    """A normalized, side-effect-free snapshot of the current power state."""

    percent: int | None
    charging: bool | None
    source: PowerSource

    def __post_init__(self) -> None:
        if self.percent is not None and not 0 <= self.percent <= 100:
            raise ValueError("Battery percentage must be between 0 and 100")


@dataclass(frozen=True)
class DeviceSnapshot:
    """Settings captured before the guard changes the host."""

    brightness: float | None
    volume: int | None
    captured_at: str

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "DeviceSnapshot":
        brightness = payload.get("brightness")
        volume = payload.get("volume")
        if brightness is not None:
            brightness = float(brightness)
        if volume is not None:
            volume = int(volume)
        return cls(
            brightness=brightness,
            volume=volume,
            captured_at=str(payload.get("captured_at", "")),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "brightness": self.brightness,
            "volume": self.volume,
            "captured_at": self.captured_at,
        }


@dataclass(frozen=True)
class OperationResult:
    """Result of one host operation, including a user-facing explanation."""

    success: bool
    message: str


@dataclass
class GuardConfig:
    """Validated runtime settings for the battery guard."""

    poll_interval_seconds: int = 30
    disable_guard_at_or_below_percent: int = 20
    apply_on_ac_power: bool = False
    restore_on_exit: bool = True
    keep_awake: bool = True
    prevent_display_sleep: bool = False
    brightness_level: float = 0.0
    volume_level: int = 0
    brightness_fallback: str = "keys"
    state_file: str | None = None

    def __post_init__(self) -> None:
        if self.poll_interval_seconds < 5:
            raise ValueError("poll_interval_seconds must be at least 5")
        if not 0 <= self.disable_guard_at_or_below_percent <= 100:
            raise ValueError(
                "disable_guard_at_or_below_percent must be between 0 and 100"
            )
        if not 0.0 <= self.brightness_level <= 1.0:
            raise ValueError("brightness_level must be between 0.0 and 1.0")
        if not 0 <= self.volume_level <= 100:
            raise ValueError("volume_level must be between 0 and 100")
        if self.brightness_fallback not in {"keys", "none"}:
            raise ValueError("brightness_fallback must be 'keys' or 'none'")

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "GuardConfig":
        known_fields = {
            "poll_interval_seconds",
            "disable_guard_at_or_below_percent",
            "apply_on_ac_power",
            "restore_on_exit",
            "keep_awake",
            "prevent_display_sleep",
            "brightness_level",
            "volume_level",
            "brightness_fallback",
            "state_file",
        }
        unknown_fields = sorted(set(payload) - known_fields)
        if unknown_fields:
            raise ValueError(
                f"Unknown configuration field(s): {', '.join(unknown_fields)}"
            )
        return cls(**payload)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "poll_interval_seconds": self.poll_interval_seconds,
            "disable_guard_at_or_below_percent": self.disable_guard_at_or_below_percent,
            "apply_on_ac_power": self.apply_on_ac_power,
            "restore_on_exit": self.restore_on_exit,
            "keep_awake": self.keep_awake,
            "prevent_display_sleep": self.prevent_display_sleep,
            "brightness_level": self.brightness_level,
            "volume_level": self.volume_level,
            "brightness_fallback": self.brightness_fallback,
            "state_file": self.state_file,
        }

    def is_eligible(self, status: PowerStatus) -> tuple[bool, str]:
        """Return whether applying the guard is safe and useful right now."""

        if status.percent is None:
            return False, "Battery percentage is unavailable; guard is disabled safely."
        if status.percent <= self.disable_guard_at_or_below_percent:
            return (
                False,
                "Battery is at or below the safety threshold; guard is disabled.",
            )
        if status.source is PowerSource.UNKNOWN or status.charging is None:
            return False, "Charging state is unavailable; guard is disabled safely."
        if not self.apply_on_ac_power and (
            status.source is PowerSource.AC or status.charging is True
        ):
            return False, "AC power is connected; battery-only guard is idle."
        return True, "Battery guard is eligible."
