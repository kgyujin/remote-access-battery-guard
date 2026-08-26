"""Interfaces shared by operating-system backends."""

from __future__ import annotations

from typing import Protocol

from ..models import OperationResult, PowerStatus


class AwakeHandle(Protocol):
    """Handle for a host sleep-prevention request."""

    def stop(self) -> None:
        """Release the sleep-prevention request."""


class PlatformBackend(Protocol):
    """Operations the controller needs from a host operating system."""

    name: str

    def read_power_status(self) -> PowerStatus:
        """Read normalized power state."""

    def get_brightness(self) -> float | None:
        """Read brightness as a 0.0–1.0 fraction when available."""

    def set_brightness(self, level: float) -> OperationResult:
        """Set brightness as a 0.0–1.0 fraction."""

    def get_volume(self) -> int | None:
        """Read output volume as a 0–100 percentage when available."""

    def set_volume(self, level: int) -> OperationResult:
        """Set output volume as a 0–100 percentage."""

    def start_awake(self, prevent_display_sleep: bool) -> AwakeHandle | None:
        """Prevent idle system sleep for the lifetime of the returned handle."""
