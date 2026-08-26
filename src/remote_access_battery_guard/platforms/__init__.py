"""Select the local operating-system backend."""

from __future__ import annotations

import os
import sys

from ..models import GuardConfig
from .base import PlatformBackend
from .macos import MacOSBackend
from .windows import WindowsBackend


class PlatformNotSupportedError(RuntimeError):
    """Raised when the current operating system has no safe backend."""


def create_backend(config: GuardConfig) -> PlatformBackend:
    """Create the backend for the current host."""

    if sys.platform == "darwin":
        return MacOSBackend(brightness_fallback=config.brightness_fallback)
    if os.name == "nt":
        return WindowsBackend()
    raise PlatformNotSupportedError(
        "This release supports macOS and Windows. The current platform is read-only."
    )
