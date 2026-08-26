from remote_access_battery_guard.platforms.windows import _first_json_object


def test_first_json_object_normalizes_single_object() -> None:
    assert _first_json_object('{"EstimatedChargeRemaining": 73}') == {
        "EstimatedChargeRemaining": 73
    }


def test_first_json_object_normalizes_powershell_array_output() -> None:
    assert _first_json_object(
        '[{"EstimatedChargeRemaining": 73}, {"EstimatedChargeRemaining": 72}]'
    ) == {"EstimatedChargeRemaining": 73}


def test_first_json_object_rejects_empty_or_invalid_output() -> None:
    assert _first_json_object("[]") is None
    assert _first_json_object("not json") is None
