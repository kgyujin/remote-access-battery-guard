from remote_access_battery_guard.config import load_config, save_config
from remote_access_battery_guard.models import GuardConfig, PowerSource, PowerStatus


def test_guard_stops_at_or_below_configured_battery_threshold() -> None:
    config = GuardConfig(disable_guard_at_or_below_percent=20)

    eligible, reason = config.is_eligible(
        PowerStatus(percent=20, charging=False, source=PowerSource.BATTERY)
    )

    assert eligible is False
    assert "threshold" in reason


def test_guard_is_battery_only_by_default() -> None:
    config = GuardConfig()

    eligible, reason = config.is_eligible(
        PowerStatus(percent=80, charging=True, source=PowerSource.AC)
    )

    assert eligible is False
    assert "AC" in reason


def test_guard_fails_closed_when_charging_state_is_unknown() -> None:
    config = GuardConfig()

    eligible, reason = config.is_eligible(
        PowerStatus(percent=80, charging=None, source=PowerSource.BATTERY)
    )

    assert eligible is False
    assert "unavailable" in reason


def test_unknown_fields_are_rejected() -> None:
    try:
        GuardConfig.from_mapping({"unexpected": True})
    except ValueError as error:
        assert "unexpected" in str(error)
    else:
        raise AssertionError("Unknown configuration fields must be rejected")


def test_menubar_enabled_defaults_to_true() -> None:
    config = GuardConfig()

    assert config.menubar_enabled is True


def test_save_config_round_trips_menubar_enabled(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    save_config(config_path, GuardConfig(menubar_enabled=False))

    loaded = load_config(config_path)

    assert loaded.menubar_enabled is False


def test_save_config_overwrites_existing_file(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    save_config(config_path, GuardConfig(disable_guard_at_or_below_percent=20))
    save_config(config_path, GuardConfig(disable_guard_at_or_below_percent=15))

    loaded = load_config(config_path)

    assert loaded.disable_guard_at_or_below_percent == 15
