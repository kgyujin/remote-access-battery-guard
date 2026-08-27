from remote_access_battery_guard.services import (
    LAUNCH_AGENT_LABEL,
    MENUBAR_LOGIN_ITEM_LABEL,
    launch_agent_path,
    macos_menubar_login_item_installed,
    menubar_login_item_path,
)

# These only check path/label construction. The install/uninstall functions
# shell out to `launchctl` and would leave a real login item on the
# developer's machine, so they are intentionally left uncovered here, the
# same as the pre-existing headless-service install/uninstall functions.


def test_menubar_login_item_uses_a_distinct_label_from_the_headless_agent() -> None:
    assert MENUBAR_LOGIN_ITEM_LABEL != LAUNCH_AGENT_LABEL
    assert menubar_login_item_path() != launch_agent_path()


def test_menubar_login_item_path_is_named_after_its_label() -> None:
    assert menubar_login_item_path().name == f"{MENUBAR_LOGIN_ITEM_LABEL}.plist"


def test_menubar_login_item_installed_is_false_when_no_plist_exists(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "remote_access_battery_guard.services.menubar_login_item_path",
        lambda: tmp_path / "missing.plist",
    )

    assert macos_menubar_login_item_installed() is False
