# Remote Access Battery Guard

[![CI](https://github.com/kgyujin/remote-access-battery-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/kgyujin/remote-access-battery-guard/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![macOS](https://img.shields.io/badge/macOS-primary-000000.svg)](https://support.apple.com/macos)
[![Windows](https://img.shields.io/badge/Windows-supported-0078D4.svg)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

[English](README.md)

Paseo, 화면 공유, 드라이브 동기화처럼 원격으로 사용하는 맥북/윈도우 노트북을 연결 가능한 상태로 유지하면서 불필요한 배터리 소모를 줄이는 프로그램입니다.

## 하는 일

- 현재 배터리 잔량과 충전 상태를 감시합니다.
- 배터리로 동작하고 안전 기준보다 잔량이 높을 때 화면 밝기와 출력 음량을 낮춥니다.
- 기본값에서는 화면을 계속 켜 두지 않고 운영체제의 유휴 절전만 막아 원격 작업을 유지합니다.
- 충전기를 연결하거나 안전 기준에 도달하거나 프로그램을 종료하면 저장해 둔 밝기와 음량을 복구합니다.
- 설정한 배터리 이하에서는 가드를 적용하지 않습니다. 기본값은 20% 이하입니다.
- 원격 포트/방화벽/인증 설정을 바꾸거나 원격 자격 증명을 저장하지 않습니다.

이 도구는 노트북을 원격 사용에 적합한 상태로 유지할 뿐, 원격 접속 서버를 제공하지 않습니다. Paseo, 화면 공유/RDP, 클라우드 드라이브 클라이언트와 권한은 노트북에 미리 설정되어 있어야 합니다.

## 플랫폼 지원

| 플랫폼 | 배터리 | 밝기 | 음량 | 절전 방지 |
| --- | --- | --- | --- | --- |
| macOS | `pmset` | 네이티브 DisplayServices, 선택적 `brightness` 유틸리티 또는 밝기 키 폴백 | Core Audio, 이후 `osascript` 폴백 | `caffeinate` |
| Windows 10/11 | PowerShell/CIM | WMI 모니터 밝기 | PowerShell을 통한 Windows Core Audio | `SetThreadExecutionState` |

맥을 우선 지원합니다. 먼저 macOS의 로컬 DisplayServices/Core Audio API를 사용합니다. 이 API를 사용할 수 없는 디스플레이에서는 선택적 [`brightness`](https://github.com/nriley/brightness) 명령을 설치하세요.

```sh
brew install brightness
```

네이티브 제어와 선택적 명령을 모두 사용할 수 없으면 백엔드가 접근성 권한으로 macOS 밝기 키를 여러 번 누를 수 있습니다. 다만 메인 가드는 복구할 수 없는 설정을 적용하지 않기 위해 현재 밝기를 읽지 못하면 밝기를 그대로 둡니다.

## 설치

실행 시 필요한 외부 패키지는 없고 Python 표준 라이브러리만 사용합니다. Python 3.11 이상이 필요합니다.

```sh
git clone https://github.com/kgyujin/remote-access-battery-guard.git
cd remote-access-battery-guard
python3 -m venv .venv
source .venv/bin/activate       # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .
rabg init-config
```

설정은 운영체제별 사용자 설정 폴더에 저장됩니다. 시작 설정은 [`config.example.json`](config.example.json)에서도 확인할 수 있습니다.

## 사용법

```sh
rabg status --json
rabg run
```

`rabg run`은 기본 30초마다 상태를 확인합니다. 배터리로 동작하고 안전 기준보다 잔량이 높을 때만 설정을 적용합니다. `Ctrl+C`로 종료하면 저장된 밝기와 음량을 복구합니다.

자주 쓰는 명령:

```sh
rabg apply       # 한 번 조정; restore 또는 run의 정책 변경 전까지 설정 유지
rabg restore     # 적용 전 설정 복구
rabg status      # 사람이 읽기 쉬운 상태 출력
```

복구 전에 프로그램이 강제 종료되었다면 다시 실행하거나 `rabg restore`를 실행하세요. 복구가 성공할 때까지 스냅샷을 보존합니다.

### 설정

`disable_guard_at_or_below_percent: 20`은 20%를 포함해 그 이하에서 가드가 꺼진다는 뜻입니다. 가드가 동작 중 배터리가 그 수준에 도달하면 저장된 설정을 복구하고 절전 방지를 해제합니다.

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
  "state_file": null
}
```

원격 화면이 실제로 계속 켜져 있어야 하는 경우에만 `prevent_display_sleep: true`를 사용하세요. 배터리를 더 사용하며, 기본값은 시스템을 깨어 있게 하되 화면 절전은 허용합니다.

### macOS 로그인 시 자동 실행

패키지를 설치하고 설정을 만든 뒤 사용자 전용 launch agent를 설치합니다.

```sh
rabg install-macos-service
```

삭제하려면 다음을 실행합니다.

```sh
rabg uninstall-macos-service
```

Windows에서는 작업 스케줄러에서 `python -m remote_access_battery_guard run`을 사용자 로그인 시 실행하도록 등록하세요. 원격 세션을 소유한 동일 사용자로 실행하면 되며, 일반적인 가드 동작에는 관리자 권한이 필요하지 않습니다.

## 원격 사용 전 확인

1. Paseo, 화면 공유/RDP, 드라이브 동기화를 각각 설정합니다.
2. 화면이 절전 상태여도 원격 클라이언트가 접속되는지 확인합니다. 접속에 활성 화면이 필요하면 `prevent_display_sleep`을 켜고 추가 배터리 소모를 감수합니다.
3. 충전기를 분리하기 전에 `rabg run`을 시작합니다.
4. 기본 안전 기준을 유지하거나, 비상용 배터리를 더 남겨야 하면 기준을 높입니다.
5. 무인 동작에 의존하기 전에 로컬에서 `rabg restore`를 시험합니다.

## 안전 관련 참고

- 배터리 잔량을 읽지 못하면 안전을 위해 설정을 적용하지 않습니다.
- 현재 밝기나 음량을 읽지 못해 안전하게 복구할 수 없으면 해당 설정을 그대로 둡니다.
- 첫 변경 전에 밝기와 음량을 저장하고 작은 로컬 상태 파일에 기록합니다. 원격 자격 증명은 저장하지 않습니다.
- 프로세스를 강제 종료하면 낮아진 설정이 남을 수 있습니다. 복구 명령은 `rabg restore`입니다.
- 컴퓨터를 깨어 있게 유지하는 것 자체는 배터리를 사용합니다. 기본값에서 화면 절전을 허용하는 이유는 화면이 보통 가장 큰 추가 소모원이기 때문입니다.

## 개발

```sh
python -m compileall -q src
python -m pytest
```

## 라이선스

MIT. [LICENSE](LICENSE)를 확인하세요.
