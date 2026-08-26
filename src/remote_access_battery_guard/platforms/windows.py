"""Windows backend using PowerShell/CIM and the built-in Core Audio API."""

from __future__ import annotations

import ctypes
import json
import shutil
from typing import Any

from ..commands import SubprocessRunner
from ..models import OperationResult, PowerSource, PowerStatus
from .base import AwakeHandle

_AUDIO_CONTROL_SOURCE = r"""
using System;
using System.Runtime.InteropServices;

[ComImport]
[Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
class MMDeviceEnumeratorComObject {}

enum EDataFlow { eRender = 0, eCapture = 1, eAll = 2 }
enum ERole { eConsole = 0, eMultimedia = 1, eCommunications = 2 }

[ComImport]
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator
{
    int EnumAudioEndpoints(EDataFlow dataFlow, uint stateMask, out IntPtr devices);
    int GetDefaultAudioEndpoint(EDataFlow dataFlow, ERole role, out IMMDevice endpoint);
    int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IMMDevice device);
    int RegisterEndpointNotificationCallback(IntPtr client);
    int UnregisterEndpointNotificationCallback(IntPtr client);
}

[ComImport]
[Guid("D666063F-1587-4E43-81F1-B948E807363F")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice
{
    int Activate(ref Guid iid, uint clsCtx, IntPtr activationParams,
        [MarshalAs(UnmanagedType.Interface)] out IAudioEndpointVolume endpointVolume);
    int OpenPropertyStore(uint access, out IntPtr properties);
    int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
    int GetState(out uint state);
}

[ComImport]
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume
{
    int RegisterControlChangeNotify(IntPtr notify);
    int UnregisterControlChangeNotify(IntPtr notify);
    int GetChannelCount(out uint count);
    int SetMasterVolumeLevel(float levelDb, Guid eventContext);
    int SetMasterVolumeLevelScalar(float level, Guid eventContext);
    int GetMasterVolumeLevel(out float levelDb);
    int GetMasterVolumeLevelScalar(out float level);
    int SetChannelVolumeLevel(uint channel, float levelDb, Guid eventContext);
    int SetChannelVolumeLevelScalar(uint channel, float level, Guid eventContext);
    int GetChannelVolumeLevel(uint channel, out float levelDb);
    int GetChannelVolumeLevelScalar(uint channel, out float level);
    int SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, Guid eventContext);
    int GetMute([MarshalAs(UnmanagedType.Bool)] out bool mute);
    int GetVolumeStepInfo(out uint step, out uint stepCount);
    int VolumeStepUp(Guid eventContext);
    int VolumeStepDown(Guid eventContext);
    int QueryHardwareSupport(out uint mask);
    int GetHardwareSupportMask(out uint mask);
    int GetVolumeRange(out float minDb, out float maxDb, out float incrementDb);
}

public static class AudioEndpointVolumeControl
{
    private static IAudioEndpointVolume GetEndpoint()
    {
        var enumerator = (IMMDeviceEnumerator)new MMDeviceEnumeratorComObject();
        IMMDevice device;
        Check(enumerator.GetDefaultAudioEndpoint(EDataFlow.eRender, ERole.eConsole, out device));
        var iid = typeof(IAudioEndpointVolume).GUID;
        IAudioEndpointVolume endpoint;
        Check(device.Activate(ref iid, 23, IntPtr.Zero, out endpoint));
        return endpoint;
    }

    public static float Get()
    {
        float level;
        Check(GetEndpoint().GetMasterVolumeLevelScalar(out level));
        return level;
    }

    public static void Set(float level)
    {
        Check(GetEndpoint().SetMasterVolumeLevelScalar(level, Guid.Empty));
    }

    private static void Check(int result)
    {
        if (result < 0) Marshal.ThrowExceptionForHR(result);
    }
}
"""


def _first_json_object(output: str) -> dict[str, Any] | None:
    """Normalize PowerShell's object/array JSON output to one mapping."""

    try:
        decoded = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(decoded, list):
        decoded = decoded[0] if decoded else None
    return decoded if isinstance(decoded, dict) else None


class _WindowsAwakeHandle:
    """Keep Windows from entering idle system sleep while the guard runs."""

    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_DISPLAY_REQUIRED = 0x00000002

    def __init__(self, prevent_display_sleep: bool) -> None:
        self._kernel32 = ctypes.windll.kernel32
        flags = self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED
        if prevent_display_sleep:
            flags |= self.ES_DISPLAY_REQUIRED
        if self._kernel32.SetThreadExecutionState(flags) == 0:
            raise OSError("Windows could not set the execution-state request")

    def stop(self) -> None:
        self._kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)


class WindowsBackend:
    """Control laptop power, display brightness, output volume, and sleep state."""

    name = "Windows"

    def __init__(self, *, runner: SubprocessRunner | Any | None = None) -> None:
        self.runner = runner or SubprocessRunner()
        self.powershell = (
            shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
        )

    def _run_powershell(self, script: str):
        return self.runner.run(
            [
                self.powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ]
        )

    def read_power_status(self) -> PowerStatus:
        script = (
            "Get-CimInstance Win32_Battery | Select-Object -First 1 "
            "EstimatedChargeRemaining,BatteryStatus | ConvertTo-Json -Compress"
        )
        output = self._run_powershell(script)
        if output.returncode != 0:
            raise RuntimeError(
                output.stderr.strip() or "PowerShell could not read battery status"
            )
        battery = _first_json_object(output.stdout)
        if not battery:
            return PowerStatus(percent=None, charging=None, source=PowerSource.UNKNOWN)
        percent_value = battery.get("EstimatedChargeRemaining")
        status_value = battery.get("BatteryStatus")
        try:
            percent = int(percent_value) if percent_value is not None else None
        except (TypeError, ValueError):
            percent = None
        try:
            battery_status = int(status_value) if status_value is not None else None
        except (TypeError, ValueError):
            battery_status = None
        charging_statuses = {2, 3, 6, 7, 8, 9, 11}
        charging = (
            battery_status in charging_statuses if battery_status is not None else None
        )
        if charging is True:
            source = PowerSource.AC
        elif charging is False:
            source = PowerSource.BATTERY
        else:
            source = PowerSource.UNKNOWN
        return PowerStatus(percent=percent, charging=charging, source=source)

    def get_brightness(self) -> float | None:
        script = (
            "Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness "
            "| Select-Object -First 1 CurrentBrightness | ConvertTo-Json -Compress"
        )
        output = self._run_powershell(script)
        if output.returncode != 0:
            return None
        monitor = _first_json_object(output.stdout)
        if not monitor:
            return None
        try:
            return max(0.0, min(1.0, int(monitor["CurrentBrightness"]) / 100))
        except (KeyError, TypeError, ValueError):
            return None

    def set_brightness(self, level: float) -> OperationResult:
        if not 0.0 <= level <= 1.0:
            return OperationResult(False, "Brightness must be between 0.0 and 1.0.")
        brightness = round(level * 100)
        script = (
            "$monitor = Get-CimInstance -Namespace root/WMI "
            "-ClassName WmiMonitorBrightnessMethods | Select-Object -First 1; "
            "if ($null -eq $monitor) { throw 'WMI brightness control is unavailable.' }; "
            f"Invoke-CimMethod -InputObject $monitor -MethodName WmiSetBrightness "
            f"-Arguments @{{Timeout=0; Brightness={brightness}}}"
        )
        output = self._run_powershell(script)
        if output.returncode == 0:
            return OperationResult(True, f"Brightness set to {level:.3f}.")
        return OperationResult(
            False, output.stderr.strip() or "Windows could not set brightness."
        )

    def get_volume(self) -> int | None:
        script = (
            f"Add-Type -TypeDefinition @'\n{_AUDIO_CONTROL_SOURCE}\n'@; "
            "[AudioEndpointVolumeControl]::Get()"
        )
        output = self._run_powershell(script)
        if output.returncode != 0:
            return None
        try:
            return max(0, min(100, round(float(output.stdout.strip()) * 100)))
        except ValueError:
            return None

    def set_volume(self, level: int) -> OperationResult:
        if not 0 <= level <= 100:
            return OperationResult(False, "Volume must be between 0 and 100.")
        scalar_level = level / 100
        script = (
            f"Add-Type -TypeDefinition @'\n{_AUDIO_CONTROL_SOURCE}\n'@; "
            f"[AudioEndpointVolumeControl]::Set([single]{scalar_level:.4f})"
        )
        output = self._run_powershell(script)
        if output.returncode == 0:
            return OperationResult(True, f"Output volume set to {level}%.")
        return OperationResult(
            False, output.stderr.strip() or "Windows could not set volume."
        )

    def start_awake(self, prevent_display_sleep: bool) -> AwakeHandle | None:
        return _WindowsAwakeHandle(prevent_display_sleep)
