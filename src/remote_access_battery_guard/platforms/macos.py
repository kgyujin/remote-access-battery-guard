"""macOS backend using only local system tools and an optional brightness CLI."""

from __future__ import annotations

import ctypes
import re
import shutil
import signal
import subprocess
from collections.abc import Callable
from ctypes import c_float, c_uint32
from typing import Any

from ..commands import CommandOutput, SubprocessRunner
from ..models import OperationResult, PowerSource, PowerStatus
from .base import AwakeHandle

PERCENT_PATTERN = re.compile(r"(?P<percent>\d{1,3})%")
BRIGHTNESS_PATTERN = re.compile(r"brightness\s+(?P<level>0(?:\.\d+)?|1(?:\.0+)?)", re.I)
CORE_AUDIO_PATH = "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
CORE_GRAPHICS_PATH = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
DISPLAY_SERVICES_PATH = (
    "/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices"
)


class _AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = [
        ("selector", c_uint32),
        ("scope", c_uint32),
        ("element", c_uint32),
    ]


def _fourcc(value: str) -> int:
    return int.from_bytes(value.encode("ascii"), byteorder="big")


class _CoreAudioVolume:
    """Read and set the default output volume through Apple's Core Audio HAL."""

    def __init__(self) -> None:
        library = ctypes.CDLL(CORE_AUDIO_PATH)
        self._get_property = library.AudioObjectGetPropertyData
        self._get_property.restype = ctypes.c_int32
        self._get_property.argtypes = [
            c_uint32,
            ctypes.POINTER(_AudioObjectPropertyAddress),
            c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(c_uint32),
            ctypes.c_void_p,
        ]
        self._set_property = library.AudioObjectSetPropertyData
        self._set_property.restype = ctypes.c_int32
        self._set_property.argtypes = [
            c_uint32,
            ctypes.POINTER(_AudioObjectPropertyAddress),
            c_uint32,
            ctypes.c_void_p,
            c_uint32,
            ctypes.c_void_p,
        ]

    def _default_output_device(self) -> int:
        address = _AudioObjectPropertyAddress(_fourcc("dOut"), _fourcc("glob"), 0)
        device_id = c_uint32()
        data_size = c_uint32(ctypes.sizeof(device_id))
        status = self._get_property(
            1,
            ctypes.byref(address),
            0,
            None,
            ctypes.byref(data_size),
            ctypes.byref(device_id),
        )
        if status != 0 or device_id.value == 0:
            raise OSError(
                f"Core Audio could not find a default output device ({status})."
            )
        return device_id.value

    def get(self) -> float:
        device_id = self._default_output_device()
        for element in (0, 1, 2):
            address = _AudioObjectPropertyAddress(
                _fourcc("volm"), _fourcc("outp"), element
            )
            volume = c_float()
            data_size = c_uint32(ctypes.sizeof(volume))
            status = self._get_property(
                device_id,
                ctypes.byref(address),
                0,
                None,
                ctypes.byref(data_size),
                ctypes.byref(volume),
            )
            if status == 0:
                return max(0.0, min(1.0, float(volume.value)))
        raise OSError(
            "Core Audio does not expose output volume for the default device."
        )

    def set(self, level: float) -> None:
        device_id = self._default_output_device()
        successful_writes = 0
        for element in (0, 1, 2):
            address = _AudioObjectPropertyAddress(
                _fourcc("volm"), _fourcc("outp"), element
            )
            volume = c_float(level)
            status = self._set_property(
                device_id,
                ctypes.byref(address),
                0,
                None,
                ctypes.sizeof(volume),
                ctypes.byref(volume),
            )
            if status == 0:
                successful_writes += 1
        if successful_writes == 0:
            raise OSError("Core Audio does not allow changing output volume.")


class _DisplayServicesBrightness:
    """Use macOS's local display service when the built-in display is available."""

    def __init__(self) -> None:
        graphics = ctypes.CDLL(CORE_GRAPHICS_PATH)
        graphics.CGMainDisplayID.restype = c_uint32
        self._display_id = graphics.CGMainDisplayID()
        display_services = ctypes.CDLL(DISPLAY_SERVICES_PATH)
        self._get_brightness = display_services.DisplayServicesGetBrightness
        self._get_brightness.restype = ctypes.c_int32
        self._get_brightness.argtypes = [c_uint32, ctypes.POINTER(c_float)]
        self._set_brightness = display_services.DisplayServicesSetBrightness
        self._set_brightness.restype = ctypes.c_int32
        self._set_brightness.argtypes = [c_uint32, c_float]

    def get(self) -> float:
        brightness = c_float()
        status = self._get_brightness(self._display_id, ctypes.byref(brightness))
        if status != 0:
            raise OSError(f"DisplayServices could not read brightness ({status}).")
        return max(0.0, min(1.0, float(brightness.value)))

    def set(self, level: float) -> None:
        status = self._set_brightness(self._display_id, c_float(level))
        if status != 0:
            raise OSError(f"DisplayServices could not set brightness ({status}).")


def parse_pmset_battery(output: str) -> PowerStatus:
    """Parse `pmset -g batt` output without depending on localized UI text."""

    header = next(
        (line for line in output.splitlines() if "Now drawing from" in line), ""
    )
    if "AC Power" in header:
        source = PowerSource.AC
    elif "Battery Power" in header:
        source = PowerSource.BATTERY
    else:
        source = PowerSource.UNKNOWN

    detail_line = next((line for line in output.splitlines() if "%" in line), "")
    percent_match = PERCENT_PATTERN.search(detail_line)
    percent = int(percent_match.group("percent")) if percent_match else None
    normalized_detail = detail_line.lower()
    if "discharging" in normalized_detail:
        charging: bool | None = False
    elif "charging" in normalized_detail or "charged" in normalized_detail:
        charging = True
    elif source is PowerSource.AC:
        charging = True
    else:
        charging = None
    return PowerStatus(percent=percent, charging=charging, source=source)


class _CaffeinateHandle:
    """Own a `caffeinate` process until the controller releases it."""

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self._process = process

    def stop(self) -> None:
        if self._process.poll() is not None:
            return
        self._process.send_signal(signal.SIGTERM)
        try:
            self._process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=3)


class MacOSBackend:
    """Control battery and output settings on macOS."""

    name = "macOS"

    def __init__(
        self,
        *,
        runner: SubprocessRunner | Any | None = None,
        brightness_fallback: str = "keys",
        brightness_binary: str | None = None,
        process_factory: Callable[..., subprocess.Popen[str]] | None = None,
    ) -> None:
        self.runner = runner or SubprocessRunner()
        self.brightness_fallback = brightness_fallback
        self.brightness_binary = brightness_binary or shutil.which("brightness")
        self.process_factory = process_factory or subprocess.Popen
        self._display_services: _DisplayServicesBrightness | None = None
        self._core_audio: _CoreAudioVolume | None = None

    def _native_brightness(self) -> _DisplayServicesBrightness:
        if self._display_services is None:
            self._display_services = _DisplayServicesBrightness()
        return self._display_services

    def _native_audio(self) -> _CoreAudioVolume:
        if self._core_audio is None:
            self._core_audio = _CoreAudioVolume()
        return self._core_audio

    def read_power_status(self) -> PowerStatus:
        output = self.runner.run(["pmset", "-g", "batt"])
        if output.returncode != 0:
            raise RuntimeError(
                output.stderr.strip() or "pmset could not read power status"
            )
        return parse_pmset_battery(output.stdout)

    def get_brightness(self) -> float | None:
        try:
            return self._native_brightness().get()
        except (OSError, AttributeError):
            pass
        if not self.brightness_binary:
            return None
        output = self.runner.run([self.brightness_binary, "-l"])
        if output.returncode != 0:
            return None
        match = BRIGHTNESS_PATTERN.search(output.stdout)
        if not match:
            return None
        return max(0.0, min(1.0, float(match.group("level"))))

    def set_brightness(self, level: float) -> OperationResult:
        if not 0.0 <= level <= 1.0:
            return OperationResult(False, "Brightness must be between 0.0 and 1.0.")
        try:
            self._native_brightness().set(level)
            return OperationResult(True, f"Brightness set to {level:.3f}.")
        except (OSError, AttributeError):
            pass
        if self.brightness_binary:
            output = self.runner.run([self.brightness_binary, f"{level:.3f}"])
            if output.returncode == 0:
                return OperationResult(True, f"Brightness set to {level:.3f}.")
            return OperationResult(
                False,
                output.stderr.strip() or "The brightness utility failed.",
            )
        if self.brightness_fallback == "keys" and level == 0.0:
            script = (
                'tell application "System Events"\n'
                "  repeat 20 times\n"
                "    key code 145\n"
                "  end repeat\n"
                "end tell"
            )
            output = self.runner.run(["osascript", "-e", script])
            if output.returncode == 0:
                return OperationResult(
                    True,
                    "Brightness lowered with macOS brightness keys; exact restoration "
                    "requires the optional `brightness` utility.",
                )
            return OperationResult(
                False,
                output.stderr.strip()
                or "macOS could not send brightness keys; Accessibility permission may be needed.",
            )
        return OperationResult(
            False,
            "Brightness control is unavailable. Install the optional `brightness` utility "
            "or set brightness_fallback to `keys` with a target of 0.0.",
        )

    def get_volume(self) -> int | None:
        try:
            return round(self._native_audio().get() * 100)
        except (OSError, AttributeError):
            pass
        output = self.runner.run(
            ["osascript", "-e", "output volume of (get volume settings)"]
        )
        if output.returncode != 0:
            return None
        try:
            return max(0, min(100, int(output.stdout.strip())))
        except ValueError:
            return None

    def set_volume(self, level: int) -> OperationResult:
        if not 0 <= level <= 100:
            return OperationResult(False, "Volume must be between 0 and 100.")
        try:
            self._native_audio().set(level / 100)
            return OperationResult(True, f"Output volume set to {level}%.")
        except (OSError, AttributeError):
            pass
        output = self.runner.run(
            ["osascript", "-e", f"set volume output volume {level}"]
        )
        if output.returncode == 0:
            return OperationResult(True, f"Output volume set to {level}%.")
        return OperationResult(
            False, output.stderr.strip() or "macOS could not set volume."
        )

    def start_awake(self, prevent_display_sleep: bool) -> AwakeHandle | None:
        flags = ["-i"]
        if prevent_display_sleep:
            flags.insert(0, "-d")
        process = self.process_factory(
            ["caffeinate", *flags],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        return _CaffeinateHandle(process)


def parse_brightness_output(output: CommandOutput) -> float | None:
    """Parse helper kept public for focused backend tests."""

    match = BRIGHTNESS_PATTERN.search(output.stdout)
    return float(match.group("level")) if match else None
