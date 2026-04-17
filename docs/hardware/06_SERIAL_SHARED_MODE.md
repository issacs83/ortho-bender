# Serial Console Shared Mode — Agent + User Coexistence

**Date**: 2026-04-17
**Author**: Isaac Park

## Overview

Claude agent와 사용자가 동시에 EVK 시리얼 콘솔을 사용하는 운영 방식.
사용자는 minicom으로 모니터링하고, agent는 pyserial로 명령을 전송한다.

## How It Works

### Linux TTY Sharing

Linux에서 같은 `/dev/ttyUSBx`를 여러 프로세스가 동시에 열 수 있다:

| 동작 | 결과 |
|------|------|
| **Write** (agent -> board) | 양쪽 모두 가능. 사용자 minicom에 agent 명령이 실시간 표시 |
| **Read** (board -> host) | 먼저 읽는 프로세스가 가져감. minicom이 거의 항상 먼저 읽음 |

### Data Flow (with capture log)

```
Agent (pyserial)                    User (minicom -C /tmp/minicom.log)
     |                                   |
     |--- write("lsusb\r\n") ---------> |  (minicom 화면에 "lsusb" 표시)
     |                                   |
     |                        Board executes lsusb
     |                                   |
     |                                   |  (minicom 화면에 결과 표시)
     |                                   |  (동시에 /tmp/minicom.log 에 기록)
     |                                   |
     |--- Read /tmp/minicom.log -------> |
     |  (전체 결과 파싱 가능!)            |
```

**핵심**: minicom의 `-C` (capture) 옵션으로 모든 출력이 로그 파일에 기록된다.
Agent는 pyserial로 명령을 보내고, 로그 파일을 읽어서 결과를 파싱한다.
사용자는 minicom에서 전체 과정을 실시간 관찰한다.

## Usage Patterns

### Pattern 1: Agent Sends + Reads Log (Primary)

Agent가 pyserial로 명령을 보내고, minicom 캡처 로그에서 결과를 읽는다.

```python
import serial, time, os

LOG = '/tmp/minicom.log'

# Record log position before command
pre_size = os.path.getsize(LOG)

# Send command
ser = serial.Serial('/dev/ttyUSB2', 115200, timeout=1)
ser.write(b'lsusb\r\n')
time.sleep(2)
ser.close()

# Read new output from log
with open(LOG, 'r') as f:
    f.seek(pre_size)
    result = f.read()
print(result)
```

**Use cases:**
- 보드 상태 확인 (lsusb, dmesg, ifconfig)
- API 응답 읽기 (curl + JSON 파싱)
- 서비스 재시작 (systemctl restart ...)
- 설정 변경 (setenv, saveenv in U-Boot)
- 디버깅 명령 (cat /proc/interrupts, devmem2)

### Pattern 2: Agent Needs Response -> Use SSH

Agent가 결과를 파싱해야 하는 경우 SSH를 사용.

```python
import subprocess

result = subprocess.run(
    ['ssh', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=no',
     'root@192.168.77.2', 'curl -s http://localhost:8000/api/system/status'],
    capture_output=True, text=True
)
data = json.loads(result.stdout)
```

**Use cases:**
- API 응답 파싱
- 파일 내용 읽기 (cat + 파싱)
- 빌드 결과 확인

### Pattern 3: Board Hung -> Serial Exclusive

보드가 멈추면 SSH 불가. 사용자가 minicom을 닫고 agent가 단독 사용.

```python
# User closes minicom first
ser = serial.Serial('/dev/ttyUSB2', 115200, timeout=2)
# Full read/write access
ser.write(b'\r\n')
response = ser.read(4096)  # Now agent gets the response
```

### Pattern 4: Board Won't Boot -> FT4232H GPIO Reset

```python
from pyftdi.gpio import GpioMpsseController

nSRST, ONOFF_B = 0x20, 0x80
gpio = GpioMpsseController()
gpio.configure('ftdi://ftdi:4232:1:4/1',
               direction=(nSRST | ONOFF_B), frequency=1e6)
gpio.write(nSRST | ONOFF_B)   # both high (inactive)
time.sleep(0.1)
gpio.write(ONOFF_B)            # nSRST low (assert reset)
time.sleep(0.2)
gpio.write(nSRST | ONOFF_B)   # release
gpio.close()
```

## Hardware Setup

### FT4232H Channel Mapping

```
FT4232H (USB ID: 0403:6011)
├── Channel A  (/dev/ttyUSB0)  — JTAG TDI/TDO/TMS/TCK + GPIO reset
├── Channel B  (/dev/ttyUSB1)  — Cortex-M7 debug UART (unused by Linux)
├── Channel C  (/dev/ttyUSB2)  — A53 Linux serial console (115200 8N1)
└── Channel D  (/dev/ttyUSB3)  — Reserved
```

### Physical Connections

```
Host PC (Jetson/x86)
  └── USB cable
       └── FT4232H (on EVK board)
            ├── Channel C -> UART2 (A53 console)
            └── Channel A ADBUS -> Reset/Power GPIOs
                 ├── ADBUS4 (0x10) — RESET_B
                 ├── ADBUS5 (0x20) — nSRST (SYS_nRST)
                 ├── ADBUS6 (0x40) — IO_nRST
                 └── ADBUS7 (0x80) — ONOFF_B
```

## Benefits

| Aspect | Description |
|--------|-------------|
| **Real-time visibility** | 사용자가 agent 동작을 minicom에서 실시간 관찰 |
| **Trust** | Agent가 보드에 무엇을 하는지 투명하게 확인 가능 |
| **Debugging** | Agent 명령 실행 중 문제 발생 시 사용자가 즉시 개입 가능 |
| **No context switch** | 사용자가 별도 터미널 열 필요 없음 |

## Setup

사용자가 minicom을 캡처 모드로 시작:

```bash
minicom -D /dev/ttyUSB2 -b 115200 -C /tmp/minicom.log
```

또는 이미 열린 minicom에서 `Ctrl-A` → `L` → `/tmp/minicom.log` 입력.

## Limitations

| Limitation | Workaround |
|------------|------------|
| minicom 캡처 꺼진 상태 | SSH 사용 또는 사용자에게 `-C` 옵션 요청 |
| 양쪽 동시 write 시 충돌 | Agent가 명령 전송 전 사용자에게 알림 |
| Lock file 충돌 가능 | minicom `-o` 옵션으로 lock 비활성화 |
| 로그 파일 계속 커짐 | 세션 종료 시 `/tmp/minicom.log` 삭제 |

## Agent Rules (for .claude/rules/)

이 동작 방식은 `.claude/rules/board-access.md`에 규칙으로 정의되어 있으며,
이 프로젝트의 모든 Claude 세션/에이전트에 자동 적용된다.
