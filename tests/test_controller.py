from __future__ import annotations

from datetime import datetime, timezone

from remote_access_battery_guard.controller import GuardController
from remote_access_battery_guard.models import (
    DeviceSnapshot,
    GuardConfig,
    OperationResult,
    PowerSource,
    PowerStatus,
)
from remote_access_battery_guard.state import SnapshotStore


class FakeAwakeHandle:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class FakeBackend:
    name = "fake"

    def __init__(self, status: PowerStatus) -> None:
        self.status = status
        self.brightness = 0.65
        self.volume = 42
        self.brightness_calls: list[float] = []
        self.volume_calls: list[int] = []
        self.awake_handles: list[FakeAwakeHandle] = []

    def read_power_status(self) -> PowerStatus:
        return self.status

    def get_brightness(self) -> float:
        return self.brightness

    def set_brightness(self, level: float) -> OperationResult:
        self.brightness_calls.append(level)
        self.brightness = level
        return OperationResult(True, f"brightness={level}")

    def get_volume(self) -> int:
        return self.volume

    def set_volume(self, level: int) -> OperationResult:
        self.volume_calls.append(level)
        self.volume = level
        return OperationResult(True, f"volume={level}")

    def start_awake(self, prevent_display_sleep: bool) -> FakeAwakeHandle:
        handle = FakeAwakeHandle()
        self.awake_handles.append(handle)
        return handle


class UnreadableSettingsBackend(FakeBackend):
    def get_brightness(self) -> None:
        return None

    def get_volume(self) -> None:
        return None


def make_controller(tmp_path, backend: FakeBackend) -> GuardController:
    config = GuardConfig(poll_interval_seconds=5)
    store = SnapshotStore(tmp_path / "state.json")
    return GuardController(
        backend,
        config,
        store,
        clock=lambda: datetime(2026, 8, 26, tzinfo=timezone.utc),
    )


def test_reconcile_applies_controls_and_keeps_remote_host_awake(tmp_path) -> None:
    backend = FakeBackend(
        PowerStatus(percent=80, charging=False, source=PowerSource.BATTERY)
    )
    controller = make_controller(tmp_path, backend)

    result = controller.reconcile()

    assert result.success
    assert result.action == "active"
    assert backend.brightness_calls == [0.0]
    assert backend.volume_calls == [0]
    assert len(backend.awake_handles) == 1
    assert controller.snapshot == DeviceSnapshot(
        brightness=0.65,
        volume=42,
        captured_at="2026-08-26T00:00:00+00:00",
    )

    controller.reconcile()
    assert backend.brightness_calls == [0.0]
    assert backend.volume_calls == [0]
    assert len(backend.awake_handles) == 1


def test_reconcile_does_not_apply_below_safety_threshold(tmp_path) -> None:
    backend = FakeBackend(
        PowerStatus(percent=20, charging=False, source=PowerSource.BATTERY)
    )
    controller = make_controller(tmp_path, backend)

    result = controller.reconcile()

    assert result.success
    assert result.action == "idle"
    assert backend.brightness_calls == []
    assert backend.volume_calls == []
    assert backend.awake_handles == []
    assert controller.snapshot is None


def test_reconcile_leaves_unreadable_settings_unchanged(tmp_path) -> None:
    backend = UnreadableSettingsBackend(
        PowerStatus(percent=80, charging=False, source=PowerSource.BATTERY)
    )
    controller = make_controller(tmp_path, backend)

    result = controller.reconcile()

    assert result.success
    assert backend.brightness_calls == []
    assert backend.volume_calls == []
    assert len(backend.awake_handles) == 1


def test_reconcile_restores_settings_when_battery_reaches_threshold(tmp_path) -> None:
    backend = FakeBackend(
        PowerStatus(percent=80, charging=False, source=PowerSource.BATTERY)
    )
    controller = make_controller(tmp_path, backend)
    controller.reconcile()
    backend.status = PowerStatus(percent=20, charging=False, source=PowerSource.BATTERY)

    result = controller.reconcile()

    assert result.success
    assert result.action == "idle"
    assert backend.brightness_calls == [0.0, 0.65]
    assert backend.volume_calls == [0, 42]
    assert backend.awake_handles[0].stopped
    assert controller.snapshot is None
    assert not (tmp_path / "state.json").exists()


def test_restore_keeps_snapshot_when_a_setting_cannot_be_restored(tmp_path) -> None:
    backend = FakeBackend(
        PowerStatus(percent=80, charging=False, source=PowerSource.BATTERY)
    )
    controller = make_controller(tmp_path, backend)
    controller.reconcile()

    def failed_volume(_level: int) -> OperationResult:
        return OperationResult(False, "volume unavailable")

    backend.set_volume = failed_volume
    result = controller.restore()

    assert result.success is False
    assert controller.snapshot is not None
    assert (tmp_path / "state.json").exists()
