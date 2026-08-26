"""Durable storage for the pre-guard brightness and volume snapshot."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import DeviceSnapshot


class SnapshotStore:
    """Read and write a small local state file without exposing credentials."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()

    def load(self) -> DeviceSnapshot | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return None
            return DeviceSnapshot.from_mapping(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # A corrupt state file must never prevent the machine from booting.
            return None

    def save(self, snapshot: DeviceSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            dir=self.path.parent,
            text=True,
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as state_file:
                json.dump(snapshot.to_mapping(), state_file, indent=2)
                state_file.write("\n")
                state_file.flush()
                os.fsync(state_file.fileno())
            Path(temporary_name).replace(self.path)
        except BaseException:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
