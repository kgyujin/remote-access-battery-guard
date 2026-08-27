# Remote Access Battery Guard

[![CI](https://github.com/kgyujin/remote-access-battery-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/kgyujin/remote-access-battery-guard/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![macOS](https://img.shields.io/badge/macOS-primary-000000.svg)](https://support.apple.com/macos)
[![Windows](https://img.shields.io/badge/Windows-supported-0078D4.svg)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

[한국어](README.ko.md)

Keep a MacBook or Windows laptop usable through remote tools such as Paseo, screen sharing, and drive synchronization while reducing avoidable battery drain.

## What it does

- Watches the local battery and charging state.
- On battery power above the safety threshold, lowers brightness and output volume.
- Keeps the operating system awake for remote work without forcing the display to stay on by default.
- Restores the captured brightness and volume when AC power is connected, the safety threshold is reached, or the guard exits.
- Stops applying the guard at or below a configurable battery percentage (20% by default).
- Does not open remote ports, change firewall rules, store remote credentials, or replace Paseo/screen-sharing authentication.

The guard keeps the host available; it does not provide a remote-access server. Paseo, Screen Sharing, RDP, cloud-drive clients, and their permissions must already be configured on the host.

## Platform support

| Platform | Power | Brightness | Volume | Keep awake |
| --- | --- | --- | --- | --- |
| macOS | `pmset` | Native DisplayServices, optional `brightness` utility, or brightness-key fallback | Core Audio, then `osascript` fallback | `caffeinate` |
| Windows 10/11 | PowerShell/CIM | WMI monitor brightness | Windows Core Audio through PowerShell | `SetThreadExecutionState` |

macOS is the primary target. The guard first uses the local DisplayServices/Core Audio APIs. For displays where those APIs are unavailable, install the optional [`brightness`](https://github.com/nriley/brightness) command:

```sh
brew install brightness
```

If both native control and the optional command are unavailable, the backend can lower brightness with macOS brightness keys when Accessibility permission is granted. The main guard intentionally leaves unreadable brightness unchanged so that it never applies a setting it cannot restore safely.

## Install

Runtime dependencies are Python standard-library only. Python 3.11 or newer is required.

```sh
git clone https://github.com/kgyujin/remote-access-battery-guard.git
cd remote-access-battery-guard
python3 -m venv .venv
source .venv/bin/activate       # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .
rabg init-config
```

The config is stored in the platform user config directory. The starter file is also available as [`config.example.json`](config.example.json).

## Use

```sh
rabg status --json
rabg run
```

`rabg run` polls every 30 seconds by default. It applies the guard only while the machine is on battery and above the safety threshold. Press `Ctrl+C` to restore the saved settings and exit.

Useful commands:

```sh
rabg apply       # reconcile once; settings remain until restore/run changes policy
rabg restore     # restore the saved pre-guard settings
rabg status      # human-readable status
```

If a run is interrupted before restoration, start the program again or run `rabg restore`. The snapshot is kept until restoration succeeds.

### Configuration

The important safety setting is inclusive: `disable_guard_at_or_below_percent: 20` means the guard is inactive at 20% and below. If the battery reaches that level while the guard is active, the saved settings are restored and sleep prevention is released.

```json
{
  "poll_interval_seconds": 30,
  "disable_guard_at_or_below_percent": 20,
  "apply_on_ac_power": false,
  "restore_on_exit": true,
  "keep_awake": true,
  "prevent_display_sleep": false,
  "brightness_level": 0.0,
  "volume_level": 0,
  "brightness_fallback": "keys",
  "state_file": null,
  "menubar_enabled": true
}
```

Use `prevent_display_sleep: true` only when the remote screen must remain visibly active. It uses more battery; the default keeps the system awake while allowing the display to sleep.

`menubar_enabled` only affects the [menu bar app](#macos-menu-bar-app): it stores the on/off toggle's last state so it's restored the next time the app starts. The headless CLI ignores it.

### Start automatically on macOS

After installing the package and creating the config, install the per-user launch agent:

```sh
rabg install-macos-service
```

Remove it with:

```sh
rabg uninstall-macos-service
```

On Windows, create a Task Scheduler task that runs `python -m remote_access_battery_guard run` at user logon. Run it as the same user who owns the remote-access session; administrator privileges are not required for the normal guard.

## macOS menu bar app

A single on/off toggle for people who would rather not run a terminal command. Requires the optional [`rumps`](https://github.com/jaredks/rumps) dependency:

```sh
python -m pip install -e ".[menubar]"
rabg menubar
```

The status bar shows the battery percentage next to a glyph (🔋 idle, 🛡️ guard currently applying, ⏻ off). Everything is one flat menu — no separate preferences window:

- **Battery Guard Enabled** — the master switch. Turning it off restores the captured brightness/volume immediately, the same as `rabg restore`.
- **Threshold submenu** — battery-percentage presets (10/15/20/25/30%) at or below which the guard stays inactive.
- **Keep awake / Also keep display awake** — the same options as `keep_awake` / `prevent_display_sleep`.
- **Start at login** — installs a separate login item for the menu bar app (independent of `install-macos-service`).

Every change is written straight to the same `config.json` the CLI reads, so `rabg status` and the menu bar app always agree. Run only one of `rabg run` (the headless launch agent) or `rabg menubar` at a time — both apply the same guard against the same state file, so running both together is redundant.

## Remote-use checklist

1. Configure Paseo, Screen Sharing/RDP, and drive synchronization independently.
2. Confirm the laptop can be reached while the display is asleep. If the remote client needs an active display, enable `prevent_display_sleep` and accept the extra battery cost.
3. Start `rabg run` before disconnecting the charger.
4. Keep the default safety threshold, or raise it if the laptop must retain more emergency battery.
5. Test `rabg restore` locally before relying on unattended operation.

## Safety notes

- The program fails closed when battery percentage cannot be read: it does not apply the guard.
- The program also leaves brightness or volume unchanged when the current value cannot be read, because an unknown value cannot be restored safely.
- Brightness and volume values are captured before the first change and kept in a small local state file; no remote credentials are written.
- A forced process kill can leave the last low-power settings in place. `rabg restore` is the recovery command.
- Keeping a computer awake still consumes battery. The default does not prevent display sleep because that is usually the largest avoidable cost.

## Development

```sh
python -m compileall -q src
python -m pytest
```

## License

MIT. See [LICENSE](LICENSE).
