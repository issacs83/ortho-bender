# kc_test → i.MX8MP 포팅 계획

## 목적
- kc_test(Windows)를 i.MX8MP-EVK에서 돌려 **하드웨어 검증** (시리얼 통신 + 카메라)
- 최소 변경 포팅 (Quick & Dirty) - 구조 변경 없음
- 이후 ortho-bender 아키텍처(A53+M7, RPMsg)로 완전 새로 개발 예정
- `src/app/`, `src/shared/` 등 기존 아키텍처 코드는 건드리지 않음

## kc_test 원본 분석 요약

### 시스템 개요
- "Bender 2 (B2)" 치과 와이어 벤딩 머신 테스트 프로그램
- Windows Console App (MSVC v142, Visual Studio)
- PC에서 USB-Serial로 외부 MCU 보드 제어 + USB 카메라 비전

### 소스 파일 (kc_test/opencvbuffering/)
| 파일 | 역할 |
|------|------|
| kctestmain.cpp | 메인. 카메라 스레드 + 모터 스레드 + UI 루프 |
| stub.h | 전체 API 헤더. mc*(모터명령), ml*(모터로직), LED, 센서, 통신 |
| stub.cpp | 핵심 구현. 시리얼 프로토콜, 모터 명령/로직, LED 효과, 통신 관리 (1626줄) |
| serial.h/cpp | wjwwood/serial 라이브러리 (크로스플랫폼, MIT) |
| win.h/cpp | serial 라이브러리 Windows 구현 |
| list_ports_win.cpp | Windows COM 포트 열거 (SetupAPI) |
| v8stdint.h | 정수 타입 정의 (Windows용 stdint 대체) |

### 스레드 구조
- Main Thread: 카메라 프레임 표시 + 이미지 안정성 검사
- GrabThread: 카메라 연속 캡처 → g_camera_buffer (Queue<Mat>)
- MotorThread: MCU 핸드셰이크 → 초기화 → 벤딩 시퀀스

### 4축 모터
- BENDER (0x01): 와이어 벤딩 ±90° 회전
- FEEDER (0x02): 와이어 급송 mm 단위
- LIFTER (0x03): 핀 업/다운 (리트랙션)
- CUTTER (0x04): 와이어 절단

### 5개 센서
- [0] Bending, [1] Feeding#1, [2] Feeding#2, [3] Retraction, [4] Cutter

### 시리얼 통신 프로토콜
- 물리: USB-to-Serial, 19200 baud, 8N1, No flow control
- 패킷: [STX 0x5B][CMD 1B][DATA nB][CRC16 2B][ETX 0x5D]
- CRC: CRC-16/Modbus (룩업 테이블)
- ACK: CMD + 0x10, 프로토콜 에러 시 0xB8
- 자동탐색: 모든 COM 포트 스캔 + Hello(0xA7) 핸드셰이크

### 명령어 (주요)
| CMD | 코드 | 설명 |
|-----|------|------|
| INIT | 0x50 | 모터 홈 초기화 |
| MOVEVEL | 0x53 | 속도 모드 이동 (id,dir,step[4],acc[3],max[3],dec[3]) |
| MOVEABS | 0x54 | 절대위치 이동 |
| STOP | 0x55 | 즉시 정지 |
| SETBRIGHTNESS | 0x57 | LED 밝기/색상 |
| GETSENSORSTATE | 0xA5 | 센서 상태 조회 |
| HELLO | 0xA7 | 핸드셰이크 |

### 단위 변환
- Resolution: res값 0~8 → 마이크로스텝 256~1 (256 >> res)
- DEG2STEP(deg, id) = deg / (1.8 / resolution)
- MM2DEG(mm) = mm * 3.6

### 라이브러리
- OpenCV 4.0.1 (opencv_world401)
- wjwwood/serial 0.1 (MIT, 크로스플랫폼)
- Windows API (Sleep, QPC, CreateFile, SetupAPI)
- C++11 STL (thread, mutex, atomic, queue)

### 카메라 설정
- USB 카메라, DirectShow, 640x480@30fps, Exposure=-10

## 포팅 Windows→Linux 변환 목록

| Windows | Linux 대체 |
|---------|-----------|
| `Sleep(ms)` | `std::this_thread::sleep_for(chrono::milliseconds(ms))` |
| `LARGE_INTEGER` + `QueryPerformanceCounter/Frequency` | `chrono::steady_clock` 또는 `clock_gettime(CLOCK_MONOTONIC)` |
| `sprintf_s` | `snprintf` |
| `CAP_DSHOW` | `CAP_V4L2` |
| `win.h/cpp` | `unix.h/cpp` (serial 라이브러리에 이미 존재) |
| `list_ports_win.cpp` | `list_ports_linux.cpp` (serial 라이브러리에 이미 존재) |
| `"COM%d"` | `"/dev/ttyUSB%d"` 또는 `"/dev/ttyACM%d"` |
| `#include <windows.h>` | 제거, POSIX 헤더 |

## 진행 단계

### Step 1: 개발환경 세팅
- 크로스 컴파일러 (aarch64-linux-gnu-g++) - 현재 미설치
- cmake - 현재 미설치 (sudo 불가, 수동 설치 필요)
- OpenCV 4.x (크로스 컴파일 또는 타겟 보드에서 네이티브 빌드)
- 현재 환경: Ubuntu 22.04 x86_64, g++ 11.4.0, make 4.3, git 2.34.1
- sudo 권한 없음 → 수동 설치 또는 보드에서 직접 빌드 검토

### Step 2: serial 라이브러리 Linux 소스 추가
- wjwwood/serial GitHub에서 unix.h, unix.cpp, list_ports_linux.cpp 확보
- serial.cpp 내부 #ifdef _WIN32 분기로 자동 전환됨

### Step 3: platform 치환
- platform.h 작성 (Sleep, 타이머 등 ~10개 함수 매핑)
- 변경량 약 50줄

### Step 4: stub.h/cpp 수정
- windows.h 제거, LARGE_INTEGER→chrono
- COM 포트 경로 변경

### Step 5: main.cpp 수정
- CAP_DSHOW → CAP_V4L2
- QPC 제거

### Step 6: CMakeLists.txt 작성

### Step 7: 크로스 빌드 + 보드 테스트

## 예상 소요: 2-3일

## 비고
- 모터 실제 제어는 하지 않음, 통신 부분만 구현
- 카메라는 USB 또는 MIPI 모두 가능
- i.MX8MP 보드 하나로 모두 구현 (PC + 제어보드 합친 구성)
