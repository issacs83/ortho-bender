# 시스템 아키텍처

Ortho-Bender 와이어 벤딩 머신의 전체 시스템 구조 설명. 하드웨어부터 SDK 까지
**개발자가 반드시 알아야 할 층위별 경계**를 정의한다.

---

## 1. 시스템 개요

Ortho-Bender 는 3D 치료 계획으로부터 치과 교정용 와이어를 정밀 벤딩하는
**의료용 제조 장비**다. 입력은 치아 모델 기반 3D 폴리라인, 출력은 환자
맞춤형 아치와이어다.

| 항목 | 값 |
|------|---|
| 장비 분류 | 치과 교정 와이어 벤딩 시스템 |
| 규제 | FDA Class II 510(k), IEC 62304 Class B, ISO 13485, ISO 14971 |
| 메인 SoC | NXP i.MX8MP (Cortex-A53 ×4 + Cortex-M7 + NPU 2.3 TOPS) |
| 벤딩 정밀도 | ±0.1 mm / ±0.5° (목표) |
| 지원 재질 | SS 304, NiTi, β-Ti (TMA), Cu-NiTi |
| 와이어 직경 | 0.305 mm ~ 0.508 mm (0.012" ~ 0.020") |

---

## 2. 하드웨어 블록 다이어그램

```
                      ┌─────────────────────────────────────────┐
                      │             NXP i.MX8MP SoC             │
                      │                                         │
                      │  Cortex-A53 ×4            Cortex-M7     │
                      │  (Linux/Yocto)            (FreeRTOS)    │
                      │     │                         │         │
                      │     │  RPMsg IPC              │         │
                      │     └────────────┬────────────┘         │
                      │                  │                      │
                      │  ┌───────────────┴─────────┐            │
                      │  │   Shared DDR (rproc)    │            │
                      │  └─────────────────────────┘            │
                      │                                         │
                      │  NPU 2.3 TOPS (A53 side inference)      │
                      └─────┬──────────────────────────┬────────┘
                            │                          │
                  ┌─────────┴────────┐        ┌────────┴──────┐
                  │  USB 3.0 Hub     │        │  ECSPI2 + GPIO│
                  │  (U3V Vision)    │        │  (STEP/DIR)   │
                  └─────────┬────────┘        └────────┬──────┘
                            │                          │
                  ┌─────────┴────────┐        ┌────────┴──────────┐
                  │ Allied Vision    │        │ ISO7741 Isolator  │
                  │ 1800 U-158m      │        │ (Galvanic ×2)     │
                  │ (USB3 Vision)    │        └────────┬──────────┘
                  └──────────────────┘                 │
                                                       │
                                          ┌────────────┴────────────┐
                                          │   TMC260C-PA ×4 Driver  │
                                          │   VMot = 12V            │
                                          │   StallGuard2 enabled   │
                                          └────────────┬────────────┘
                                                       │
                          ┌──────────┬─────────────────┼──────────┬──────────┐
                          │          │                 │          │          │
                      ┌───┴───┐  ┌───┴───┐        ┌────┴──┐  ┌────┴──┐       │
                      │ FEED  │  │ BEND  │        │ROTATE │  │ LIFT  │   E-STOP (HW)
                      │ Motor │  │ Motor │        │ Motor │  │ Motor │   → DRV_ENN
                      └───────┘  └───────┘        └───────┘  └───────┘
                       (Axis 0)   (Axis 1)         (Axis 2)   (Axis 3)
                       Phase 1    Phase 1          Phase 2    Phase 2
```

### 2.1 주요 하드웨어 구성요소

| 구성 | 부품 | 역할 |
|------|------|------|
| 메인 SoC | NXP i.MX8MP | A53 ×4 + M7 + NPU 2.3T, 이기종 멀티코어 |
| 모터 드라이버 | Trinamic TMC260C-PA ×4 | STEP/DIR, StallGuard2, VMot 12V |
| 스테퍼 모터 ×4 | NEMA 17 (FEED/BEND/ROTATE/LIFT) | 1.8°/step, 1/256 마이크로스텝 |
| 카메라 | Allied Vision Alvium 1800 U-158m | 1456×1088 모노크롬, USB3 Vision |
| 격리 IC | TI ISO7741 ×2 | A53-모터측 갈바닉 격리 (갤/디지털) |
| 안전 | 하드웨어 E-STOP 버튼 | DRV_ENN 라인 직접 차단 |
| 전원 | SMPS 24V/3.3A → 12V/5A | 메인 로드 12V VMot |
| 스토리지 | eMMC 16 GB | Yocto 이미지 + DB |

### 2.2 축 구성 (Phase 기반 개발)

| Phase | 축 | 기능 | M7 GPIO |
|-------|---|------|---------|
| Phase 1 | Axis 0: FEED | 와이어 직선 이송 | STEP/DIR/EN |
| Phase 1 | Axis 1: BEND | 벤딩 아암 회전 (θ) | STEP/DIR/EN |
| Phase 2 | Axis 2: ROTATE | 와이어 축방향 회전 (β) | STEP/DIR/EN |
| Phase 2 | Axis 3: LIFT | 핀치 롤러 상/하 | STEP/DIR/EN |

현재 Phase 1 구현 우선 (2축), Phase 2 는 기구 수령 후.

---

## 3. 소프트웨어 스택

### 3.1 전체 계층도

```
┌────────────────────────────────────────────────────────────┐
│  외부 개발자 / 프론트엔드 / Python / cURL                    │  ← 유일한 SW 경계
├────────────────────────────────────────────────────────────┤
│  REST API (/api/*)      │   WebSocket (/ws/*)              │
├─────────────────────────┴──────────────────────────────────┤
│           FastAPI 라우터 레이어 (src/app/server/routers/)  │
│   motor │ camera │ bending │ cam │ system │ wifi          │
├────────────────────────────────────────────────────────────┤
│           서비스 레이어 (src/app/server/services/)          │
│  motor_service │ camera_service │ cam_service │ ipc_client │
├────────────────────────────────────────────────────────────┤
│  IPC 어댑터              │   카메라 어댑터                   │
│  (RPMsg / Mock)          │   (VmbPy / Mock)                 │
├─────────────────────────┬──────────────────────────────────┤
│  커널 드라이버            │   USB3 스택 + Genicam CTI        │
│  (imx_rpmsg, remoteproc) │   (VimbaUSBTL.cti)               │
├─────────────────────────┴──────────────────────────────────┤
│              A53 Linux Kernel (Yocto)                      │
│  ────────────────────── RPMsg over AMP ──────────────────  │
│              M7 FreeRTOS                                   │
├────────────────────────────────────────────────────────────┤
│  Motion Task │ Diag Task │ Safety Task │ IPC Task         │
│  (100 Hz)    │ (200 Hz)  │ (asynchro)  │ (interrupt)      │
├────────────────────────────────────────────────────────────┤
│  HAL (hal_gpio / hal_spi / hal_timer)                      │
├────────────────────────────────────────────────────────────┤
│  MCUXpresso SDK + Cortex-M7 레지스터                        │
└────────────────────────────────────────────────────────────┘
```

### 3.2 A53 Linux 스택

| 계층 | 구성 | 기술 스택 |
|------|------|----------|
| OS | Yocto Kirkstone (linux-imx 5.15) | NXP BSP + meta-ortho-bender |
| 런타임 | Python 3.10 | FastAPI + Pydantic v2 + uvicorn |
| 카메라 | VmbPy 1.2.1 | Vimba X SDK 2026-1 + Genicam CTI |
| IPC | RPMsg char dev (`/dev/rpmsg0`) | imx_rpmsg 커널 모듈 |
| (선택) GUI | Qt6 | 현장 엔지니어링 툴 (미포함, 외부 프론트) |
| NPU | eIQ + TFLite | 향후 스프링백 예측 모델 |

### 3.3 M7 FreeRTOS 스택

| 계층 | 구성 | 설명 |
|------|------|------|
| RTOS | FreeRTOS 10.4 (MCUXpresso SDK 2.13) | 4개 태스크, 우선순위 기반 |
| 드라이버 | TMC260C-PA (SPI config) | SPI 설정 + STEP/DIR 모션 |
| 타이머 | GPT1/2 | 트라페조이달 스텝 펄스 생성 |
| 통신 | RPMsg-Lite | A53 와 양방향 메시지 |
| 안전 | 워치독 WDOG3 (200 ms) | 메인 루프 피드 |
| 메모리 | TCM + OCRAM | 힙 없음 (init 후) |

M7 은 **motion scheduler** 역할. 실시간 모션 루프는 GPT 타이머 인터럽트에서
스텝 펄스를 생성하고, IPC 로 받은 B-code 시퀀스를 태스크 레벨에서 디스패치한다.

---

## 4. 모션 제어 파이프라인

3D 치료 계획 입력에서 물리적 와이어 벤딩까지의 전체 데이터 흐름.

```
┌──────────────┐
│  3D 치료계획  │   치아 모델 기반 3D 폴리라인 (N=2~512 vertices)
│  (치과의사)   │
└──────┬───────┘
       │  JSON / CSV
       ▼
┌──────────────────────────────────────────────┐
│  CAD / CAM 프론트엔드                          │
│  (React or 외부 도구)                         │
│                                              │
│  POST /api/cam/generate  (preview)           │
└──────┬───────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────┐
│  services/cam_service.py                     │
│                                              │
│  1. 폴리라인 이산화 (min_segment_mm)          │
│  2. 방향 벡터 / binormal 계산                 │
│  3. (L, β, θ) 스텝 생성                       │
│  4. 재질별 스프링백 계수 적용                  │
│                                              │
│  출력: List[(L_mm, beta_deg, theta_deg)]     │
└──────┬───────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────┐
│  POST /api/cam/execute  (또는 /api/bending)   │
└──────┬───────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────┐
│  services/ipc_client.py                      │
│                                              │
│  MSG_MOTION_EXECUTE_BCODE 메시지 빌드         │
│  struct: <HHf + N × fff                      │
│          step_count material_id diameter     │
│          + (L, β, θ) × N                     │
└──────┬───────────────────────────────────────┘
       │ /dev/rpmsg0
       ▼
┌──────────────────────────────────────────────┐
│  M7 FreeRTOS - motion_task.c                 │
│                                              │
│  1. 메시지 수신 → 큐에 적재                    │
│  2. 각 스텝마다:                              │
│     - 좌표 변환 (β → ROTATE, θ → BEND)        │
│     - 스프링백 overshoot 적용                  │
│     - TMC 마이크로스텝 수 계산                 │
│     - GPT 타이머 프로파일 설정                 │
│  3. 스텝 완료 → 다음 스텝                      │
│  4. 시퀀스 완료 → 상태 IDLE                    │
└──────┬───────────────────────────────────────┘
       │ GPIO STEP/DIR 펄스
       ▼
┌──────────────────────────────────────────────┐
│  ISO7741 갈바닉 격리                           │
└──────┬───────────────────────────────────────┘
       │ 격리된 STEP/DIR
       ▼
┌──────────────────────────────────────────────┐
│  TMC260C-PA ×4 드라이버 (VMot 12V)            │
│  - 마이크로스텝 코일 전류 생성                  │
│  - StallGuard2 로드 센싱                       │
│  - DRV_STATUS 폴백 피드백                      │
└──────┬───────────────────────────────────────┘
       │ 코일 전류
       ▼
┌──────────────────────────────────────────────┐
│  NEMA 17 스테퍼 모터 ×4 → 와이어 벤딩          │
└──────────────────────────────────────────────┘
```

### 4.1 파이프라인 타이밍

| 단계 | 소요 시간 | 비고 |
|------|----------|------|
| CAM 이산화 | < 50 ms | Python 순수 연산 |
| REST → IPC 큐잉 | < 10 ms | 네트워크 + RPMsg |
| M7 수신 → 첫 스텝 | < 20 ms | 태스크 스위칭 포함 |
| 단일 스텝 실행 | 200~800 ms | 스프링백 포함 (경험치) |
| 상태 업데이트 → A53 | < 10 ms | RPMsg `MSG_STATUS_MOTION` |

---

## 5. SDK 계층 경계

**외부 SW 개발자가 하드웨어에 직접 접근하지 않는다.** 모든 상호작용은
FastAPI 백엔드를 통해서만 이루어진다.

### 5.1 허용되는 인터페이스

| 개발자 유형 | 접근 경로 |
|------------|----------|
| 프론트엔드 (React/Vue) | REST + WebSocket (브라우저 fetch / ws) |
| CAD/CAM 개발자 | REST (Python `httpx`, cURL) |
| 비전/ML 개발자 | WebSocket `/ws/camera` + REST `/api/camera` |
| DevOps / 운영 | REST `/api/system`, SSH 로그 |

### 5.2 금지되는 접근

- ❌ `/dev/rpmsg0` 직접 읽기/쓰기 → `services/ipc_client.py` 만 접근
- ❌ VmbPy 직접 호출 → `services/camera_service.py` 만 접근
- ❌ GPIO / SPI / sysfs → M7 펌웨어 수정 없이 불가능
- ❌ TMC 레지스터 SPI 직접 쓰기 → M7 만 수행

이 경계 덕분에 **하드웨어가 바뀌어도 SDK API 는 유지**된다.

---

## 6. 데이터 흐름 시나리오

### 6.1 벤딩 실행 시나리오

```
Client              FastAPI             ipc_client         M7          TMC
  │                    │                    │              │            │
  │ POST /bending      │                    │              │            │
  ├───────────────────>│                    │              │            │
  │                    │ execute_bcode()    │              │            │
  │                    ├───────────────────>│              │            │
  │                    │                    │ RPMsg write  │            │
  │                    │                    ├─────────────>│            │
  │                    │                    │              │ Step N=1   │
  │                    │                    │              ├───────────>│
  │ 200 OK (즉시 반환)  │                    │              │            │
  │<───────────────────┤                    │              │            │
  │                    │                    │              │            │
  │ GET /status (폴링)  │                    │              │            │
  ├───────────────────>│ get_status()       │              │            │
  │                    ├───────────────────>│ RPMsg read   │            │
  │                    │                    ├─────────────>│            │
  │                    │                    │<─────────────┤ {step:1}   │
  │                    │<───────────────────┤              │            │
  │<───────────────────┤ {current_step:1}   │              │            │
  │                    │                    │              │ Step N=2   │
  │                    │                    │              ├───────────>│
  │ GET /status        │                    │              │            │
  ...                                                                    
  │                    │                    │              │ DONE       │
  │ GET /status        │                    │              │            │
  │<───────────────────┤ {running:false}    │              │            │
```

### 6.2 카메라 라이브 스트림 시나리오

```
Client              FastAPI             VmbPy         Camera
  │                    │                  │              │
  │ WS /ws/camera      │                  │              │
  ├───────────────────>│                  │              │
  │                    │ accept_frame()   │              │
  │                    ├─────────────────>│              │
  │                    │                  │ capture_img  │
  │                    │                  ├─────────────>│
  │                    │                  │<─────────────┤
  │                    │<─────────────────┤ ndarray      │
  │                    │ JPEG encode      │              │
  │<───────────────────┤ binary frame     │              │
  │ (10 Hz 반복)        │                  │              │
```

---

## 7. 안전 아키텍처

의료 기기 Class B 소프트웨어의 핵심은 **다중 경로 안전**이다.

### 7.1 E-STOP 이중 경로

```
┌──────────────┐          ┌──────────────────┐
│  E-STOP 버튼  │─────┬───>│  M7 GPIO ISR     │  (Software, <1 ms)
│   (물리)      │     │    │  → motion_stop() │
└──────────────┘     │    └──────────────────┘
                     │
                     └───>┌──────────────────┐
                          │  DRV_ENN 라인     │  (Hardware, <10 μs)
                          │  → 드라이버 Off   │
                          └──────────────────┘
```

| 경로 | 응답 시간 | 효과 |
|------|----------|------|
| 하드웨어 (DRV_ENN) | < 10 μs | TMC 출력단 즉시 Off, 전류 차단 |
| 소프트웨어 (ISR) | < 1 ms | 모션 큐 플러시 + 상태 ALARM |

둘 중 어느 경로라도 단독으로 모션을 중단할 수 있다.

### 7.2 워치독

- M7 워치독 타이머: **200 ms** 타임아웃
- `motion_task` 메인 루프에서 주기적 피드
- 펌웨어 행 → 리셋 → A53 remoteproc 재시작 감지 → mock fallback

### 7.3 TMC260C-PA DRV_STATUS 폴링

모든 모션 사이클(200 Hz)마다:
- 과열 경고 (`otpw`) → 속도 제한
- 과열 차단 (`ot`) → 즉시 정지 + ALARM
- 단락 (`s2ga/s2gb`) → 즉시 정지 + ALARM
- 오픈 로드 (`ola/olb`) → WARN

### 7.4 StallGuard2 기반 홈잉

홈 센서 없이 모터 부하로 엔드스톱 감지:
- 홈잉 속도로 접근
- `sg_result` 가 `SGT` 임계값 미만 → 엔드스톱 확정
- 축별 캘리브레이션 값은 `machine_config.h` 에 저장

### 7.5 소프트웨어 리미트

B-code 실행 전 검증:
- `L_mm` ∈ [0.5, 200]
- `beta_deg` ∈ [-360, 360]
- `theta_deg` ∈ [0, 180]
- 누적 이송 길이 ≤ 재질별 최대치
- 단계 수 ≤ 128

---

## 8. 전원 및 접지 계통

```
AC 입력 (100~240V)
    │
    ▼
┌─────────┐
│ SMPS 1  │  24V / 3.3A → 메인 컨트롤러
└────┬────┘
     │
     ├───> A53 Linux SoC (PMIC 변환)
     │     - 3.3V / 1.8V / 1.2V / VDDQ 1.1V
     │
     ▼
┌─────────┐
│ SMPS 2  │  12V / 5A → 모터 전원 (VMot)
└────┬────┘
     │
     │    ↑↑↑ 갈바닉 격리 경계 ↑↑↑
     │    (ISO7741 ×2 for STEP/DIR/EN 신호)
     │
     ▼
┌──────────────┐
│ TMC260C-PA ×4 │
└──────┬───────┘
       │
       ▼
    스테퍼 모터 ×4
```

- **GND 분리**: GND_A (로직) vs GND_M (모터). 격리 IC 에서 통과.
- **서지 보호**: VMot 입력에 TVS 다이오드 + 인덕터 L-C 필터
- **접지**: 섀시 접지 단일점, 케이블 쉴드 섀시 접지

---

## 9. 통신 프로토콜

| 프로토콜 | 경로 | 목적 |
|---------|------|------|
| **RPMsg** | A53 `/dev/rpmsg0` ↔ M7 | 모션 명령 / 상태 / 진단 |
| **USB3 Vision (U3V)** | SoC USB 3.0 ↔ 카메라 | 영상 획득 (1456×1088 @ 40 fps max) |
| **SPI** | M7 ECSPI2 ↔ TMC260C-PA | 드라이버 레지스터 설정 |
| **I²C** | 각종 | EEPROM, 온도 센서, PMIC |
| **GPIO** | M7 ↔ TMC STEP/DIR/EN | 실시간 모션 펄스 |
| **UART** | M7 디버그 `/dev/ttyLP5` | 시리얼 로그 |
| **HTTP/WS** | A53 0.0.0.0:8000 | 외부 SDK 인터페이스 |
| **mDNS/SSDP** | 향후 | 네트워크 디스커버리 (Phase 2) |

### 9.1 RPMsg 메시지 타입 (src/shared/ipc_protocol.h)

| 메시지 | 방향 | 페이로드 |
|--------|------|---------|
| `MSG_MOTION_EXECUTE_BCODE` | A53 → M7 | `<HHf` 헤더 + N × `<fff` 스텝 |
| `MSG_MOTION_STOP` | A53 → M7 | 없음 |
| `MSG_MOTION_HOME` | A53 → M7 | `uint8_t axis_mask` |
| `MSG_MOTION_RESET` | A53 → M7 | `uint8_t axis_mask` |
| `MSG_STATUS_MOTION` | M7 → A53 | `<B4f4fHHB` state+pos×4+vel×4+steps+mask |
| `MSG_ALARM` | M7 → A53 | alarm_code + timestamp |

---

## 10. 배포 토폴로지

### 10.1 개발 환경

```
┌────────────────────┐       USB Ethernet      ┌──────────────────┐
│  개발자 노트북      │  ──────────────────────> │   i.MX8MP EVK    │
│  (Linux/macOS)    │  192.168.77.1 / .2       │                  │
│                    │                          │  FastAPI :8000   │
│  React Vite :5173  │                          │  M7 FreeRTOS     │
│    └ proxy /api    │                          │  VmbPy Camera    │
└────────────────────┘                          └──────────────────┘
                                                         │
                                                   USB3  │
                                                         ▼
                                                ┌──────────────────┐
                                                │ Allied Vision    │
                                                │ 1800 U-158m      │
                                                └──────────────────┘
```

### 10.2 Mock 모드 (하드웨어 없음)

```
┌────────────────────┐
│  개발자 노트북      │
│                    │
│  FastAPI :8000     │  OB_MOCK_MODE=true
│   ├ mock IPC       │  ← /dev/rpmsg0 없이 동작
│   └ mock Camera    │  ← VmbPy 없이 합성 프레임
│                    │
│  React Vite :5173  │  ← 실제와 동일한 API envelope
└────────────────────┘
```

모든 기능이 정상 동작하며, 유일한 차이는 모션 타이밍이 시뮬레이션 되는 것뿐이다.

### 10.3 양산 토폴로지 (향후)

- 로컬 운영: LAN + Kiosk 단말 → 백엔드 포트 8000 로컬 제한
- 원격 관리: mTLS 기반 reverse tunnel → cloud management
- OTA: A/B 파티션 + dm-verity
- 로그 수집: syslog → 중앙 수집 서버

---

## 11. 계층별 소유권 / 책임

| 계층 | 언어 | 변경 주체 | 테스트 방법 |
|------|------|----------|------------|
| React Frontend | TypeScript | 프론트엔드 개발자 | Vitest + Playwright |
| SDK Examples | Python/cURL | 외부 개발자 | pytest + mock mode |
| FastAPI Routers | Python | 백엔드 개발자 | pytest + httpx |
| Services | Python | 백엔드 개발자 | pytest + mock adapters |
| IPC / Camera Adapters | Python | 플랫폼 팀 | 단위 + 실기기 |
| RPMsg Kernel | C | BSP 팀 | dmesg + 스코프 |
| M7 FreeRTOS | C | 펌웨어 팀 | SWD 디버거 + HIL |
| HAL | C | 펌웨어 팀 | 단위 + 로직 분석기 |
| 하드웨어 | — | 회로/기구 팀 | 실측 + EMC 챔버 |

변경 블러스트 반경을 최소화하기 위해 **경계면은 고정**하고, 각 팀은 자기
계층 내에서만 수정한다.

---

## 12. 확장 지점

향후 기능 추가 시 권장 확장 지점:

| 기능 | 확장 지점 |
|------|----------|
| 신규 와이어 재질 | `services/cam_service.py` `_SPRINGBACK_FACTOR` + `docs/WIRE_MATERIALS.md` |
| 새 모션 커맨드 | `ipc_protocol.h` 메시지 추가 + M7 motion_task |
| 신규 카메라 | `services/camera_service.py` 어댑터 클래스 구현 |
| NPU 추론 | `services/inference_service.py` (신규) + FastAPI 라우터 |
| 인증/ 권한 | FastAPI Middleware + JWT (현재 없음, Phase 2) |
| 데이터베이스 | `models/` + SQLAlchemy (현재 파일 기반 config) |
| 다국어 UI | 프론트엔드 i18n (한국어/영어/일본어) |

---

## 13. 관련 문서

- [SDK_GUIDE.md](SDK_GUIDE.md) — SDK 사용 가이드
- [API_REFERENCE.md](API_REFERENCE.md) — REST/WS 엔드포인트 레퍼런스
- [BCODE_SPEC.md](BCODE_SPEC.md) — B-code 포맷 명세
- [WIRE_MATERIALS.md](WIRE_MATERIALS.md) — 재질별 특성
- [DEPLOYMENT.md](DEPLOYMENT.md) — 배포 및 운영
- [MOCK_MODE.md](MOCK_MODE.md) — 하드웨어 없이 개발
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — 문제 해결
- [ROADMAP.md](ROADMAP.md) — 개발 로드맵

---

**문서 버전**: 1.0 — 2026-04-12
**작성자**: Isaac, Park
