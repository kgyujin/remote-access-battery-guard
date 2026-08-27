"""macOS menu bar app: a single on/off toggle plus in-menu settings.

The app wraps `GuardController` with a manual master switch (`self.enabled`,
persisted as `GuardConfig.menubar_enabled`). Turning it on starts a
`rumps.Timer` that reconciles on the existing poll interval, so the guard
still only *applies* while the battery/threshold policy in `GuardConfig`
says it's safe. Turning it off stops the timer and immediately restores the
captured settings, equivalent to `rabg restore`.

Requires macOS and the optional `rumps` dependency:
    python -m pip install -e ".[menubar]"
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.platform != "darwin":
    raise RuntimeError(
        "The menu bar app requires macOS (it depends on the 'rumps' package)."
    )

try:
    import rumps
except ImportError as error:  # pragma: no cover - exercised only without the extra
    raise RuntimeError(
        "The 'rumps' package is required for the menu bar app. "
        "Install it with: python -m pip install -e '.[menubar]'"
    ) from error

from .config import default_config_path, load_config, resolve_state_path, save_config
from .controller import ControllerResult, GuardController
from .menubar_format import format_status_text, format_title, threshold_presets
from .models import GuardConfig
from .platforms import create_backend
from .services import (
    install_macos_menubar_login_item,
    macos_menubar_login_item_installed,
    uninstall_macos_menubar_login_item,
)
from .state import SnapshotStore


class BatteryGuardMenuBarApp(rumps.App):
    def __init__(self, config_path: Path) -> None:
        super().__init__("Battery Guard", quit_button=None)
        self.config_path = config_path
        self.config = load_config(config_path)
        self.backend = create_backend(self.config)
        self.controller = GuardController(
            self.backend,
            self.config,
            SnapshotStore(resolve_state_path(self.config)),
        )
        self.enabled = self.config.menubar_enabled

        self.status_item = rumps.MenuItem("배터리 상태 확인 중…")
        self.enabled_item = rumps.MenuItem(
            "배터리 가드 켜짐", callback=self._toggle_enabled
        )
        self.threshold_items = {
            percent: rumps.MenuItem(
                f"{percent}% 이하에서 비활성화",
                callback=self._threshold_callback(percent),
            )
            for percent in threshold_presets(self.config.disable_guard_at_or_below_percent)
        }
        self.keep_awake_item = rumps.MenuItem(
            "항상 깨어있기 유지", callback=self._toggle_keep_awake
        )
        self.prevent_display_sleep_item = rumps.MenuItem(
            "디스플레이도 계속 켜두기", callback=self._toggle_prevent_display_sleep
        )
        self.login_item = rumps.MenuItem(
            "로그인 시 자동 실행", callback=self._toggle_login_item
        )
        self.quit_item = rumps.MenuItem("종료", callback=self._quit)

        self.menu = [
            self.status_item,
            None,
            self.enabled_item,
            None,
            ("임계값 (배터리 % 이하에서 비활성화)", list(self.threshold_items.values())),
            self.keep_awake_item,
            self.prevent_display_sleep_item,
            None,
            self.login_item,
            None,
            self.quit_item,
        ]
        self.status_item.set_callback(None)

        self.timer = rumps.Timer(self._on_tick, self.config.poll_interval_seconds)
        self._sync_menu_state()
        self._refresh()
        if self.enabled:
            self.timer.start()

    # -- config persistence -------------------------------------------------

    def _update_config(self, **changes: object) -> None:
        payload = self.config.to_mapping()
        payload.update(changes)
        self.config = GuardConfig.from_mapping(payload)
        self.controller.config = self.config
        save_config(self.config_path, self.config)

    def _sync_menu_state(self) -> None:
        self.enabled_item.state = self.enabled
        for percent, item in self.threshold_items.items():
            item.state = percent == self.config.disable_guard_at_or_below_percent
        self.keep_awake_item.state = self.config.keep_awake
        self.prevent_display_sleep_item.state = self.config.prevent_display_sleep
        self.login_item.state = macos_menubar_login_item_installed()

    # -- status rendering -----------------------------------------------------

    def _refresh(self) -> None:
        result = self.controller.reconcile() if self.enabled else self.controller.status()
        self._render(result)

    def _render(self, result: ControllerResult) -> None:
        guard_active = self.controller.active
        self.title = format_title(
            result.status.percent, enabled=self.enabled, guard_active=guard_active
        )
        self.status_item.title = format_status_text(
            result, enabled=self.enabled, guard_active=guard_active
        )

    def _on_tick(self, _timer: "rumps.Timer") -> None:
        self._refresh()

    # -- menu callbacks -------------------------------------------------------

    def _toggle_enabled(self, sender: "rumps.MenuItem") -> None:
        self.enabled = not self.enabled
        self._update_config(menubar_enabled=self.enabled)
        sender.state = self.enabled
        if self.enabled:
            self.timer.start()
        else:
            self.timer.stop()
        self._refresh()

    def _threshold_callback(self, percent: int):
        def _callback(_sender: "rumps.MenuItem") -> None:
            if percent == self.config.disable_guard_at_or_below_percent:
                return
            self._update_config(disable_guard_at_or_below_percent=percent)
            self._sync_menu_state()
            self._refresh()

        return _callback

    def _toggle_keep_awake(self, sender: "rumps.MenuItem") -> None:
        new_value = not self.config.keep_awake
        self._update_config(keep_awake=new_value)
        sender.state = new_value
        if not new_value:
            # Release any handle already held so sleep prevention stops now,
            # not only on the next reconcile.
            self.controller.release_awake()
        self._refresh()

    def _toggle_prevent_display_sleep(self, sender: "rumps.MenuItem") -> None:
        new_value = not self.config.prevent_display_sleep
        self._update_config(prevent_display_sleep=new_value)
        sender.state = new_value
        # The awake handle only picks up the new display-sleep setting when
        # it's (re)created, so drop the current one and let the next
        # reconcile start it again with the updated flag.
        self.controller.release_awake()
        self._refresh()

    def _toggle_login_item(self, sender: "rumps.MenuItem") -> None:
        try:
            if sender.state:
                uninstall_macos_menubar_login_item()
                sender.state = False
            else:
                install_macos_menubar_login_item(self.config_path)
                sender.state = True
        except (RuntimeError, OSError) as error:
            rumps.alert(title="로그인 항목 설정 실패", message=str(error))

    def _quit(self, _sender: "rumps.MenuItem") -> None:
        if self.config.restore_on_exit:
            self.controller.restore()
        else:
            self.controller.release_awake()
        rumps.quit_application()


def run_menubar_app(config_path: Path | None = None) -> None:
    """Build and run the menu bar app. Blocks until the user quits."""

    app = BatteryGuardMenuBarApp(config_path or default_config_path())
    app.run()
