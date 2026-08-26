"""Reconcile power state with safe, reversible remote-availability settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from .models import (
    DeviceSnapshot,
    GuardConfig,
    OperationResult,
    PowerSource,
    PowerStatus,
)
from .platforms.base import AwakeHandle, PlatformBackend
from .state import SnapshotStore


@dataclass
class ControllerResult:
    """A single reconciliation outcome suitable for CLI or JSON output."""

    action: str
    status: PowerStatus
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    brightness: float | None = None
    volume: int | None = None

    @property
    def success(self) -> bool:
        return not self.errors

    def to_mapping(self) -> dict[str, object]:
        return {
            "action": self.action,
            "success": self.success,
            "power": {
                "percent": self.status.percent,
                "charging": self.status.charging,
                "source": self.status.source.value,
            },
            "settings": {
                "brightness": self.brightness,
                "volume": self.volume,
            },
            "messages": self.messages,
            "errors": self.errors,
        }


class GuardController:
    """Apply the guard only while the battery policy says it is appropriate."""

    def __init__(
        self,
        backend: PlatformBackend,
        config: GuardConfig,
        snapshot_store: SnapshotStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.backend = backend
        self.config = config
        self.snapshot_store = snapshot_store
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.snapshot = snapshot_store.load()
        self.awake_handle: AwakeHandle | None = None
        self.controls_applied = False

    @property
    def active(self) -> bool:
        return self.snapshot is not None

    def reconcile(self) -> ControllerResult:
        """Read power state and activate/deactivate the guard as needed."""

        try:
            status = self.backend.read_power_status()
        except Exception as error:
            return ControllerResult(
                action="error",
                status=PowerStatus(
                    percent=None, charging=None, source=PowerSource.UNKNOWN
                ),
                errors=[f"Could not read power status: {error}"],
            )
        eligible, reason = self.config.is_eligible(status)
        if eligible:
            return self._activate(status, reason)
        return self._deactivate(status, reason)

    def status(self) -> ControllerResult:
        """Return current power and guard state without changing host settings."""

        try:
            status = self.backend.read_power_status()
        except Exception as error:
            return ControllerResult(
                action="error",
                status=PowerStatus(
                    percent=None, charging=None, source=PowerSource.UNKNOWN
                ),
                errors=[f"Could not read power status: {error}"],
            )
        action = "active" if self.active else "idle"
        brightness = self.backend.get_brightness()
        volume = self.backend.get_volume()
        messages = [
            f"Platform: {self.backend.name}",
            f"Guard state: {action}",
            "Guard disabled at or below "
            f"{self.config.disable_guard_at_or_below_percent}% battery.",
        ]
        messages.append(
            f"Current brightness: {brightness:.3f}."
            if brightness is not None
            else "Current brightness: unavailable."
        )
        messages.append(
            f"Current output volume: {volume}%."
            if volume is not None
            else "Current output volume: unavailable."
        )
        if self.snapshot:
            messages.append("A pre-guard snapshot is stored for restoration.")
        return ControllerResult(
            action=action,
            status=status,
            messages=messages,
            brightness=brightness,
            volume=volume,
        )

    def restore(self) -> ControllerResult:
        """Restore captured settings and release the sleep-prevention request."""

        status = self._read_status_for_restore()
        if self.snapshot is None:
            self._stop_awake()
            return ControllerResult(
                action="idle",
                status=status,
                messages=["No saved settings were found; nothing to restore."],
            )
        result = ControllerResult(action="restored", status=status)
        restoration_failed = self._restore_snapshot(self.snapshot, result)
        self._stop_awake()
        if not restoration_failed:
            self.snapshot = None
            self.controls_applied = False
            self.snapshot_store.clear()
            result.messages.append("Saved settings restored and state cleared.")
        else:
            result.errors.append(
                "Some settings could not be restored; the snapshot was kept for retry."
            )
        return result

    def _activate(self, status: PowerStatus, reason: str) -> ControllerResult:
        result = ControllerResult(action="active", status=status, messages=[reason])
        if self.snapshot is None:
            self.snapshot = DeviceSnapshot(
                brightness=self.backend.get_brightness(),
                volume=self.backend.get_volume(),
                captured_at=self.clock().astimezone(timezone.utc).isoformat(),
            )
            self.snapshot_store.save(self.snapshot)
            result.messages.append("Current settings captured for restoration.")
        if not self.controls_applied:
            self._set_guard_controls(result)
            self.controls_applied = not result.errors
        if self.config.keep_awake and self.awake_handle is None:
            try:
                self.awake_handle = self.backend.start_awake(
                    self.config.prevent_display_sleep
                )
                result.messages.append("Idle system sleep prevention is active.")
            except Exception as error:
                result.errors.append(f"Could not keep the host awake: {error}")
        return result

    def _deactivate(self, status: PowerStatus, reason: str) -> ControllerResult:
        if self.snapshot is None:
            self._stop_awake()
            return ControllerResult(action="idle", status=status, messages=[reason])
        result = ControllerResult(action="restoring", status=status, messages=[reason])
        restoration_failed = self._restore_snapshot(self.snapshot, result)
        self._stop_awake()
        if not restoration_failed:
            self.snapshot = None
            self.controls_applied = False
            self.snapshot_store.clear()
            result.action = "idle"
            result.messages.append("Saved settings restored after guard deactivation.")
        else:
            result.errors.append(
                "Some settings could not be restored; the snapshot was kept for retry."
            )
        return result

    def _set_guard_controls(self, result: ControllerResult) -> None:
        if self.snapshot and self.snapshot.brightness is None:
            result.messages.append(
                "Brightness could not be read; it was left unchanged so it can be restored safely."
            )
        else:
            brightness_result = self._safe_operation(
                lambda: self.backend.set_brightness(self.config.brightness_level),
                "brightness",
            )
            self._append_operation(result, brightness_result)
        if self.snapshot and self.snapshot.volume is None:
            result.messages.append(
                "Volume could not be read; it was left unchanged so it can be restored safely."
            )
        else:
            volume_result = self._safe_operation(
                lambda: self.backend.set_volume(self.config.volume_level),
                "volume",
            )
            self._append_operation(result, volume_result)

    def _restore_snapshot(
        self,
        snapshot: DeviceSnapshot,
        result: ControllerResult,
    ) -> bool:
        restoration_failed = False
        if snapshot.brightness is not None:
            brightness_result = self._safe_operation(
                lambda: self.backend.set_brightness(snapshot.brightness),
                "brightness restoration",
            )
            self._append_operation(result, brightness_result)
            restoration_failed |= not brightness_result.success
        else:
            result.messages.append(
                "Brightness was not readable; it was left unchanged during restore."
            )
        if snapshot.volume is not None:
            volume_result = self._safe_operation(
                lambda: self.backend.set_volume(snapshot.volume),
                "volume restoration",
            )
            self._append_operation(result, volume_result)
            restoration_failed |= not volume_result.success
        else:
            result.messages.append(
                "Volume was not readable; it was left unchanged during restore."
            )
        return restoration_failed

    @staticmethod
    def _safe_operation(
        operation: Callable[[], OperationResult], label: str
    ) -> OperationResult:
        try:
            return operation()
        except Exception as error:
            return OperationResult(False, f"{label} failed: {error}")

    @staticmethod
    def _append_operation(result: ControllerResult, operation: OperationResult) -> None:
        target = result.messages if operation.success else result.errors
        target.append(operation.message)

    def _stop_awake(self) -> None:
        if self.awake_handle is None:
            return
        try:
            self.awake_handle.stop()
        finally:
            self.awake_handle = None

    def release_awake(self) -> None:
        """Release sleep prevention without altering saved display settings."""

        self._stop_awake()

    def _read_status_for_restore(self) -> PowerStatus:
        try:
            return self.backend.read_power_status()
        except Exception:
            return PowerStatus(percent=None, charging=None, source=PowerSource.UNKNOWN)
