"""Small subprocess abstraction used by platform backends and unit tests."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class CommandOutput:
    """Captured output from a local command."""

    returncode: int
    stdout: str
    stderr: str


class SubprocessRunner:
    """Run short, local inspection/configuration commands with a timeout."""

    def run(self, command: Sequence[str], timeout: float = 10.0) -> CommandOutput:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
        return CommandOutput(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
