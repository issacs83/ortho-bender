# Test Bench Hardware Connection Guide

DRI0035 (TMC260C) x2 + TMC5072-BOB 모터 드라이버를 i.MX8MP EVK J21 헤더에 연결하여
테스트 벤치 진단 환경을 구성하는 가이드.

---

## 1. 구성 부품

| # | 부품 | 수량 | 역할 | 비고 |
|:-:|------|:---:|------|------|
| 1 | NXP i.MX8MP EVK | 1 | 호스트 SoC | J21 40-pin 확장 헤더 사용 |
| 2 | DFRobot DRI0035 (TMC260C) | 2 | FEED + BEND 축 드라이버 | SPI Mode 3, 20-bit datagram |
| 3 | TMC5072-BOB | 1 | ROTATE + LIFT 축 드라이버 | SPI Mode 3, 40-bit datagram |
| 4 | TXS0108E 양방향 레벨 시프터 | 1 | 3.3V (EVK) <-> 5V (DRI0035) 변환 | 8채널, 자동 방향 감지 |
| 5 | 12V DC 전원 공급기 | 1 | VMot (DRI0035, TMC5072) | 2A 이상 권장 |
| 6 | 점퍼 와이어 | ~20 | 배선 | Dupont F-F, F-M 혼용 |
| 7 | 브레드보드 (선택) | 1 | 배선 정리 | 하프사이즈 이상 |

---

## 2. 전원 도메인

```
                 12V DC PSU
                    │
        ┌───────────┼───────────┐
        │           │           │
   DRI0035 #1   DRI0035 #2  TMC5072-BOB
   (VMot 12V)   (VMot 12V)  (VS 12V)
        │           │           │
     GND ───────── GND ─────── GND ──── EVK J21 GND
```

| 전원 레일 | 전압 | 소스 | 소비처 |
|-----------|------|------|--------|
| VMot / VS | 12V | 외부 PSU | DRI0035 x2 + TMC5072-BOB 모터 구동 |
| VIO (DRI0035) | 5V | DRI0035 내부 (VMot에서 생성) | DRI0035 로직 I/O |
| VIO (TMC5072) | 3.3V | EVK J21 Pin 1 (VEXP_3V3) | TMC5072-BOB 로직 |
| EVK 3.3V | 3.3V | EVK PMIC | TXS0108E Low-side, J21 GPIO |

**주의사항**:
- DRI0035 의 VIO 는 5V 레벨 → EVK 3.3V GPIO에 직접 연결하면 **SoC 손상**
- 반드시 TXS0108E 레벨 시프터를 경유하여 SPI 신호를 연결
- TMC5072-BOB 은 3.3V 로직이므로 EVK에 직접 연결 가능

---

## 3. SPI 배선

### 3.1 Split CS Topology

```
EVK J21                   TXS0108E                 Motor Drivers
─────────                 ────────                 ─────────────
                          3.3V  5V
                           │    │
Pin 23 (SCLK) ──────── A1─┤    ├─B1 ──── DRI0035 #1 SCK
                           │    │          DRI0035 #2 SCK
Pin 19 (MOSI) ──────── A2─┤    ├─B2 ──── DRI0035 #1 SDI
                           │    │          DRI0035 #2 SDI
Pin 21 (MISO) ──────── A3─┤    ├─B3 ──── DRI0035 #1 SDO ──┐
                           │    │                           │
                           │    │          DRI0035 #2 SDO ──┤ (MISO 합류)
                           │    │                           │
Pin 24 (CS0) ──────── A4──┤    ├─B4 ──── DRI0035 #1 CSN   │
                           │    │                           │
                           │    │                           │
                           │    │                           │
Pin 37 (CS1) GPIO3_IO19 ─A5──┤    ├─B5 ── DRI0035 #2 CSN   │
                           │    │                           │
Pin 35 (CS2) GPIO3_IO20 ─A6──┤    ├─B6 ── TMC5072-BOB CSN  │
                           │    │                           │
                           └────┘                           │
                                                            │
                     (MISO는 open-drain/tristate,           │
                      active CS 드라이버만 MISO 구동)        │
```

> **TMC5072-BOB** 은 3.3V 로직이므로 TXS0108E 를 거치지 않고 EVK에 직접 연결해도 됩니다.
> 단, DRI0035 과 MISO 라인을 공유하는 경우 TXS0108E 를 경유하는 것이 안전합니다.

### 3.2 CS 할당

| CS | GPIO | J21 Pin | 드라이버 | SPI 프레임 |
|:--:|------|:------:|---------|-----------|
| CS0 | ECSPI2_SS0 (HW) | 24 | DRI0035 #1 (TMC260C, FEED+BEND) | 20-bit (3 bytes) |
| CS1 | GPIO3_IO19 (soft) | 37 | DRI0035 #2 (TMC260C, 예비) | 20-bit (3 bytes) |
| CS2 | GPIO3_IO20 (soft) | 35 | TMC5072-BOB (ROTATE+LIFT) | 40-bit (5 bytes) |

### 3.3 SPI 파라미터

| 파라미터 | 값 |
|---------|-----|
| Mode | 3 (CPOL=1, CPHA=1) |
| Clock | 2 MHz |
| Bit order | MSB first |
| Word size | 8 bits |
| Linux device | `/dev/spidev1.0` |

> **i.MX8MP CS_HIGH 참고**: ECSPI 커널 드라이버가 DTS cs-gpios 극성에 따라
> SPI mode readback에 `CS_HIGH` 비트(0x04)를 추가할 수 있습니다.
> 백엔드 코드가 mode 3 설정 실패 시 자동으로 mode 7 (3 + CS_HIGH)로 폴백합니다.

---

## 4. GPIO 배선

### 4.1 STEP/DIR (모터 펄스 생성)

| 기능 | J21 Pin | GPIO | 연결 대상 |
|------|:------:|------|---------|
| FEED STEP | 31 | GPIO3_IO22 | DRI0035 #1 STEP (TXS0108E 경유) |
| BEND STEP | 12 | GPIO3_IO24 | DRI0035 #1 DIR 또는 #2 STEP (TXS0108E 경유) |
| DIR (공유) | 8 | GPIO5_IO06 | DRI0035 #1 DIR (TXS0108E 경유) |

> **테스트 벤치 단순화**: spidev 백엔드의 `pulse_step()` 은 소프트웨어 GPIO 토글로
> STEP 펄스를 생성합니다. 최대 1 kHz 수준이며 프로덕션(M7 GPT 25 kHz)보다 느립니다.
> 진단 목적으로는 충분합니다.

### 4.2 전체 J21 핀 사용 요약

| J21 Pin | 기능 | 방향 | 비고 |
|:------:|------|:----:|------|
| 1 | VEXP_3V3 | PWR | TXS0108E Low-side 전원 |
| 6, 9, 14, 20, 25, 30, 34, 39 | GND | GND | 공통 접지 |
| 19 | ECSPI2_MOSI | OUT | SPI 데이터 출력 |
| 21 | ECSPI2_MISO | IN | SPI 데이터 입력 |
| 23 | ECSPI2_SCLK | OUT | SPI 클럭 |
| 24 | ECSPI2_SS0 (CS0) | OUT | DRI0035 #1 칩셀렉트 |
| 37 | GPIO3_IO19 (CS1) | OUT | DRI0035 #2 칩셀렉트 |
| 35 | GPIO3_IO20 (CS2) | OUT | TMC5072-BOB 칩셀렉트 |
| 31 | GPIO3_IO22 (FEED STEP) | OUT | STEP 펄스 |
| 12 | GPIO3_IO24 (BEND STEP) | OUT | STEP 펄스 |
| 8 | GPIO5_IO06 (DIR) | OUT | 방향 제어 |

---

## 5. 단계별 연결 절차

### 5.1 전원 OFF 상태에서 시작

1. EVK 전원 OFF
2. 12V PSU 전원 OFF
3. 모든 보드를 작업대에 배치

### 5.2 GND 연결 (최우선)

```
EVK J21 Pin 6 (GND) ──── DRI0035 #1 GND
                    ├──── DRI0035 #2 GND
                    ├──── TMC5072-BOB GND
                    └──── TXS0108E GND
```
**GND를 먼저 연결하지 않으면 레벨 시프터가 래치업될 수 있습니다.**

### 5.3 전원 연결

```
EVK J21 Pin 1 (3.3V) ──── TXS0108E VA (Low-side 3.3V)
                     └──── TMC5072-BOB VIO (3.3V)

DRI0035 #1 VIO (5V) ──── TXS0108E VB (High-side 5V)
                    └──── DRI0035 #2 VIO (5V) [보드 내부 생성, VMot 필요]

12V PSU (+) ──── DRI0035 #1 VMot
            ├──── DRI0035 #2 VMot
            └──── TMC5072-BOB VS
12V PSU (-) ──── 공통 GND
```

### 5.4 SPI + CS 배선

TXS0108E 를 경유하여:
```
EVK Pin 23 (SCLK)  → TXS A1 → B1 → DRI0035 #1 SCK, DRI0035 #2 SCK
EVK Pin 19 (MOSI)  → TXS A2 → B2 → DRI0035 #1 SDI, DRI0035 #2 SDI
EVK Pin 21 (MISO)  → TXS A3 ← B3 ← DRI0035 #1 SDO, DRI0035 #2 SDO
EVK Pin 24 (CS0)   → TXS A4 → B4 → DRI0035 #1 CSN
EVK Pin 37 (CS1)   → TXS A5 → B5 → DRI0035 #2 CSN
EVK Pin 35 (CS2)   → (직결) → TMC5072-BOB CSN [3.3V 호환]
```

### 5.5 STEP/DIR 배선 (선택, 모터 구동 테스트 시)

```
EVK Pin 31 (FEED STEP)  → TXS A6 → B6 → DRI0035 #1 STEP
EVK Pin 12 (BEND STEP)  → TXS A7 → B7 → DRI0035 #1 DIR (또는 #2 STEP)
EVK Pin 8  (DIR)        → TXS A8 → B8 → DRI0035 DIRECTION
```

### 5.6 전원 투입 순서

1. EVK 전원 ON (3.3V 레일 활성)
2. 12V PSU ON (VMot 활성)
3. SSH 접속 후 서비스 상태 확인:
   ```bash
   ssh root@192.168.77.2
   systemctl status ortho-bender-sdk
   journalctl -u ortho-bender-sdk -n 30
   ```

---

## 6. 소프트웨어 검증

### 6.1 서비스 환경 확인

```bash
# OB_MOTOR_BACKEND=spidev 확인
grep MOTOR_BACKEND /etc/systemd/system/ortho-bender-sdk.service
```

### 6.2 SPI 디바이스 확인

```bash
ls -l /dev/spidev1.*
# /dev/spidev1.0 존재 확인
```

### 6.3 GPIO 칩 확인

```bash
ls -l /dev/gpiochip*
# gpiochip0 ~ gpiochip4 존재 확인
# GPIO3 = gpiochip2, GPIO5 = gpiochip4
```

### 6.4 API 진단 테스트

```bash
# 백엔드 모드 확인
curl -s http://192.168.77.2:8000/api/motor/diag/backend | python3 -m json.tool

# SPI 통신 테스트
curl -s http://192.168.77.2:8000/api/motor/diag/spi-test | python3 -m json.tool

# TMC260C #0 레지스터 덤프
curl -s http://192.168.77.2:8000/api/motor/diag/dump/tmc260c_0 | python3 -m json.tool

# TMC5072 GCONF 읽기
curl -s http://192.168.77.2:8000/api/motor/diag/register/tmc5072/0x00 | python3 -m json.tool
```

### 6.5 프론트엔드 진단 UI

브라우저에서 `http://192.168.77.2:8000/` 접속:
- **Diagnostics** 탭 → SPI Test 버튼으로 연결 확인
- **StallGuard Chart** → TMC260C 실시간 SG2 값 모니터링
- **Register Inspector** → 드라이버 선택 + 주소 입력으로 레지스터 직접 조작

---

## 7. 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| SPI test 전부 fail | SPI 배선 미연결 또는 CS 미연결 | SCLK/MOSI/MISO/CS 배선 점검 |
| SPI test timeout | VMot 12V 미인가 → TMC 비활성 | 12V PSU 전원 확인 |
| `ImportError: spidev` | python3-spidev 미설치 | `pip3 install spidev` |
| `ImportError: gpiod` | python3-gpiod 미설치 | `pip3 install gpiod` (libgpiod 2.x 필요) |
| `OSError: mode 0x7` | i.MX8MP ECSPI CS_HIGH | 자동 폴백 처리됨 (경고 로그만 출력) |
| CS1/CS2 통신 안 됨 | GPIO soft CS 핀 미연결 | J21 Pin 37 (CS1), Pin 35 (CS2) 확인 |
| TMC260C 응답 0xFFFFF | SDO 라인 풀업 부재 | DRI0035 SDO → TXS0108E → MISO 배선 확인 |
| `backend: "mock"` 표시 | OB_MOTOR_BACKEND 미설정 | systemd 환경변수에 `OB_MOTOR_BACKEND=spidev` 추가 |

---

## 8. 참조 문서

| 문서 | 내용 |
|------|------|
| [j21-pin-assignment.md](j21-pin-assignment.md) | J21 40-pin 완전 핀맵 + dtsi 재매핑 지시서 |
| [adapter-board-spec.md](adapter-board-spec.md) | 쪽보드 전기 사양 전체 |
| [motor-control-architecture.md](../architecture/motor-control-architecture.md) | SPI 프로토콜 + Split CS 토폴로지 상세 |
| [02_API_REFERENCE.md](../sdk/02_API_REFERENCE.md) | 전체 REST + WebSocket API 레퍼런스 |
| [04_DEPLOYMENT.md](../sdk/04_DEPLOYMENT.md) | EVK 배포 + spidev 백엔드 설정 |
