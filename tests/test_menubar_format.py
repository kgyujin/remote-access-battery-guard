from remote_access_battery_guard.controller import ControllerResult
from remote_access_battery_guard.menubar_format import (
    format_status_text,
    format_title,
    threshold_presets,
)
from remote_access_battery_guard.models import PowerSource, PowerStatus


def test_threshold_presets_include_defaults_sorted() -> None:
    assert threshold_presets(20) == [10, 15, 20, 25, 30]


def test_threshold_presets_add_custom_value() -> None:
    assert threshold_presets(18) == [10, 15, 18, 20, 25, 30]


def test_format_title_shows_off_glyph_when_disabled() -> None:
    title = format_title(62, enabled=False, guard_active=False)

    assert "62%" in title
    assert title.startswith("⏻")


def test_format_title_shows_guard_glyph_when_active() -> None:
    title = format_title(15, enabled=True, guard_active=True)

    assert "15%" in title
    assert title.startswith("\U0001f6e1")


def test_format_title_shows_idle_glyph_when_enabled_but_not_active() -> None:
    title = format_title(80, enabled=True, guard_active=False)

    assert title.startswith("\U0001f50b")


def test_format_title_handles_unknown_percent() -> None:
    assert "--" in format_title(None, enabled=True, guard_active=False)


def _result(percent: int | None, charging: bool | None) -> ControllerResult:
    return ControllerResult(
        action="idle",
        status=PowerStatus(percent=percent, charging=charging, source=PowerSource.BATTERY),
    )


def test_format_status_text_reports_disabled_state() -> None:
    text = format_status_text(_result(50, False), enabled=False, guard_active=False)

    assert "가드 꺼짐" in text
    assert "50%" in text


def test_format_status_text_reports_active_state() -> None:
    text = format_status_text(_result(12, False), enabled=True, guard_active=True)

    assert "가드 작동 중" in text


def test_format_status_text_reports_idle_state_while_enabled() -> None:
    text = format_status_text(_result(90, True), enabled=True, guard_active=False)

    assert "가드 대기 중" in text
    assert "충전 중" in text


def test_format_status_text_handles_unknown_power() -> None:
    text = format_status_text(_result(None, None), enabled=True, guard_active=False)

    assert "알 수 없음" in text
    assert "전원 상태 알 수 없음" in text
