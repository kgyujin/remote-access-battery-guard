"""Text and preset logic for the macOS menu bar app, kept free of GUI imports.

Separating this from `menubar.py` lets the formatting and threshold-preset
logic run in tests on every platform, since `rumps` (PyObjC) only installs
and imports on macOS.
"""

from __future__ import annotations

from .controller import ControllerResult

DEFAULT_THRESHOLD_PRESETS: tuple[int, ...] = (10, 15, 20, 25, 30)


def threshold_presets(current_percent: int) -> list[int]:
    """Return the sorted preset list, adding the current value if it's custom."""

    return sorted(set(DEFAULT_THRESHOLD_PRESETS) | {current_percent})


def format_title(percent: int | None, *, enabled: bool, guard_active: bool) -> str:
    """Format the menu bar's glyph + battery percentage."""

    battery = f"{percent}%" if percent is not None else "--"
    if not enabled:
        return f"⏻ {battery}"
    if guard_active:
        return f"\U0001f6e1 {battery}"
    return f"\U0001f50b {battery}"


def format_status_text(
    result: ControllerResult, *, enabled: bool, guard_active: bool
) -> str:
    """Format the non-clickable status line shown at the top of the menu."""

    power = result.status
    battery = f"{power.percent}%" if power.percent is not None else "알 수 없음"
    if power.charging is True:
        charging = "충전 중"
    elif power.charging is False:
        charging = "배터리 사용 중"
    else:
        charging = "전원 상태 알 수 없음"
    if not enabled:
        state = "가드 꺼짐"
    elif guard_active:
        state = "가드 작동 중"
    else:
        state = "가드 대기 중"
    return f"배터리 {battery} · {charging} · {state}"
