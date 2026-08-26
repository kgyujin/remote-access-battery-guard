from remote_access_battery_guard.commands import CommandOutput
from remote_access_battery_guard.models import PowerSource
from remote_access_battery_guard.platforms.macos import (
    parse_brightness_output,
    parse_pmset_battery,
)


def test_parse_pmset_battery_when_discharging() -> None:
    status = parse_pmset_battery(
        "Now drawing from 'Battery Power'\n"
        " -InternalBattery-0 (id=123)\t84%; discharging; 3:12 remaining\n"
    )

    assert status.percent == 84
    assert status.charging is False
    assert status.source is PowerSource.BATTERY


def test_parse_pmset_battery_when_connected_to_ac() -> None:
    status = parse_pmset_battery(
        "Now drawing from 'AC Power'\n"
        " -InternalBattery-0 (id=123)\t100%; charged; 0:00 remaining\n"
    )

    assert status.percent == 100
    assert status.charging is True
    assert status.source is PowerSource.AC


def test_parse_brightness_cli_output() -> None:
    output = CommandOutput(0, "display 0: brightness 0.375\n", "")

    assert parse_brightness_output(output) == 0.375
