"""Allow `python -m remote_access_battery_guard` to run the CLI."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
