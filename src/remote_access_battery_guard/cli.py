"""Command-line interface for the remote-access battery guard."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import subprocess
import time
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import (
    default_config_path,
    load_config,
    resolve_state_path,
    write_default_config,
)
from .controller import ControllerResult, GuardController
from .platforms import create_backend
from .services import install_macos_launch_agent, uninstall_macos_launch_agent
from .state import SnapshotStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rabg",
        description=(
            "Keep a remote-ready computer awake while battery, brightness, and "
            "volume are minimized."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="JSON config path (default: platform user config directory)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Show power and guard status")
    status_parser.add_argument("--json", action="store_true", help="Print JSON")

    subparsers.add_parser("apply", help="Apply the guard once if policy allows")
    subparsers.add_parser("restore", help="Restore the saved pre-guard settings")

    run_parser = subparsers.add_parser("run", help="Monitor power continuously")
    run_parser.add_argument(
        "--once",
        action="store_true",
        help="Reconcile once and exit; useful for service checks",
    )

    init_parser = subparsers.add_parser(
        "init-config", help="Create a starter JSON config"
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing config file",
    )
    subparsers.add_parser(
        "install-macos-service", help="Install and load a macOS launch agent"
    )
    subparsers.add_parser(
        "uninstall-macos-service", help="Unload and remove the macOS launch agent"
    )
    subparsers.add_parser(
        "menubar",
        help="Run the macOS menu bar app (requires: pip install -e '.[menubar]')",
    )
    return parser


def _print_result(result: ControllerResult, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(result.to_mapping(), indent=2))
        return
    power = result.status
    percent = f"{power.percent}%" if power.percent is not None else "unknown"
    print(
        f"{result.action}: platform power={power.source.value}, "
        f"battery={percent}, charging={power.charging}"
    )
    for message in result.messages:
        print(f"- {message}")
    for error in result.errors:
        print(f"! {error}", file=sys.stderr)


def _controller(config_path: Path) -> GuardController:
    config = load_config(config_path)
    backend = create_backend(config)
    return GuardController(backend, config, SnapshotStore(resolve_state_path(config)))


def _run_loop(controller: GuardController, *, once: bool) -> int:
    stop_requested = False
    result: ControllerResult | None = None
    cleanup_result: ControllerResult | None = None

    def request_stop(_signal_number: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    previous_handlers = {
        signal.SIGINT: signal.signal(signal.SIGINT, request_stop),
        signal.SIGTERM: signal.signal(signal.SIGTERM, request_stop),
    }
    try:
        while True:
            result = controller.reconcile()
            _print_result(result)
            if once or stop_requested:
                break
            time.sleep(controller.config.poll_interval_seconds)
    finally:
        for signal_number, previous_handler in previous_handlers.items():
            signal.signal(signal_number, previous_handler)
        if controller.config.restore_on_exit and not once:
            cleanup_result = controller.restore()
            if cleanup_result.action != "idle" or cleanup_result.messages:
                _print_result(cleanup_result)
        else:
            controller.release_awake()
    success = (
        result is not None
        and result.success
        and (cleanup_result is None or cleanup_result.success)
    )
    return 0 if success else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = args.config.expanduser()
    try:
        if args.command == "init-config":
            write_default_config(config_path, overwrite=args.force)
            print(f"Created config: {config_path}")
            return 0
        if args.command == "install-macos-service":
            path = install_macos_launch_agent(config_path)
            print(f"Installed and loaded: {path}")
            return 0
        if args.command == "uninstall-macos-service":
            path = uninstall_macos_launch_agent()
            print(f"Removed: {path}")
            return 0
        if args.command == "menubar":
            from .menubar import run_menubar_app

            run_menubar_app(config_path)
            return 0
        controller = _controller(config_path)
        if args.command == "status":
            result = controller.status()
            _print_result(result, as_json=args.json)
            return 0 if result.success else 1
        if args.command == "restore":
            result = controller.restore()
            _print_result(result)
            return 0 if result.success else 1
        if args.command == "apply":
            result = controller.reconcile()
            _print_result(result)
            controller.release_awake()
            return 0 if result.success else 1
        if args.command == "run":
            return _run_loop(controller, once=args.once)
    except (
        FileExistsError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    parser.error("Unknown command")
    return 2
