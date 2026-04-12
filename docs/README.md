# Ortho-Bender 문서 허브

이 문서는 Ortho-Bender 프로젝트의 **기술 문서 관문**입니다. 이 한 장만 읽어도 시스템 구성을 이해할 수 있고, 필요에 따라 상세 문서로 이동할 수 있도록 구성되었습니다.

---

## 1. 프로젝트 개요

Ortho-Bender는 교정 치료 계획을 정밀하게 굽힌 와이어로 변환하는 **치과 교정용 자동 와이어 밴딩 머신**입니다. NXP i.MX8MP SoC 기반의 듀얼-코어 아키텍처(Cortex-A53 × 4 + Cortex-M7)를 사용하여, 실시간 모션 제어와 고수준 애플리케이션(GUI, NPU 추론, CAD/CAM)을 분리합니다.

| 항목 | 값 |
|------|-----|
| SoC | NXP i.MX8MP (A53 × 4 @ 1.8GHz + M7 @ 800MHz + NPU 2.3T) |
| Linux | Yocto kirkstone, kernel 5.15 |
| M7 RTOS | FreeRTOS + 자체 trajectory manager |
| 모터 드라이버 | TMC260C-PA × 4 (STEP/DIR + SPI 설정, StallGuard2) |
| 카메라 | Allied Vision Alvium 1800 U-158m (USB3 Vision, Vimba X) |
| 백엔드 | Python FastAPI + uvicorn, REST + WebSocket |
| 프론트엔드 | React + Vite SPA (대시보드, FastAPI가 정적 서빙) |
| 규제 | FDA Class II (510k), IEC 62304 Class B, ISO 13485, ISO 14971 |

---

## 2. 아키텍처 한눈에 보기

```
┌───────────────────────────── i.MX8MP SoC ─────────────────────────────┐
│                                                                        │
│  ┌─ Cortex-A53 × 4 (Linux) ─────────┐   ┌─ Cortex-M7 (FreeRTOS) ────┐  │
│  │                                  │   │                           │  │
│  │  FastAPI (uvicorn :8000)         │   │  Trajectory Manager 100Hz │  │
│  │  ├─ /api/system  /api/motor      │   │  TMC260C-PA STEP/DIR × 4  │  │
│  │  ├─ /api/camera  /api/bending    │◀▶│  StallGuard2 Diag 200Hz   │  │
│  │  ├─ /api/simulation  /api/wifi   │   │  Safety: E-STOP + WDT     │  │
│  │  └─ /ws/*  (WebSocket streams)   │   │  HW DRV_ENN kill line     │  │
│  │                                  │   │                           │  │
│  │  HAL: RPMsg / GStreamer / wpa_cli│   │  M7 GPT timer → step pulse│  │
│  └──────────────────────────────────┘   └───────────────────────────┘  │
│                                                                        │
│  NPU 2.3T: Springback ML + Defect Detection                            │
└────────────────────────────────────────────────────────────────────────┘
          ▲                         ▲
          │ HTTP/WS                 │ HW I/O
          │                         │
     외부 앱 (Python/JS/C++)    모터·카메라·센서
```

상세: [architecture/01_ARCHITECTURE.md](architecture/01_ARCHITECTURE.md)

### 핵심 원칙

1. **개발자는 하드웨어를 직접 만지지 않는다.** 모든 상호작용은 HTTP + WebSocket을 경유한다.
2. **Mock 모드로 하드웨어 없이 개발 가능.** `OB_MOCK_MODE=1` 환경 변수.
3. **안전 경로는 이중화.** SW(M7 ISR) + HW(DRV_ENN 라인).
4. **A53은 시퀀스, M7은 실시간.** A53이 B-code를 해석해 M7에 궤적 명령을 전송하면, M7이 스텝 펄스를 생성.

---

## 3. 핵심 컴포넌트

| 영역 | 역할 | 주요 문서 |
|------|------|-----------|
| **SDK 백엔드** | FastAPI REST/WS. 개발자용 유일 인터페이스 | [sdk/01_SDK_GUIDE.md](sdk/01_SDK_GUIDE.md) |
| **API 레퍼런스** | 모든 엔드포인트 스키마 + 에러 코드 | [sdk/02_API_REFERENCE.md](sdk/02_API_REFERENCE.md) |
| **하드웨어 추상화** | 카메라/모터 교체 투명성 | [architecture/02_HARDWARE_ABSTRACTION.md](architecture/02_HARDWARE_ABSTRACTION.md) |
| **M7 펌웨어** | FreeRTOS + TMC 궤적 제어 | [hardware/03_M7_FREERTOS_EXPERIMENTS.md](hardware/03_M7_FREERTOS_EXPERIMENTS.md) |
| **CAD/CAM 엔진** | 3D curve → B-code + 스프링백 보정 | [algorithm/01_CAD_CAM_GUIDE.md](algorithm/01_CAD_CAM_GUIDE.md) |
| **B-code 포맷** | 저수준 명령 시퀀스 명세 | [algorithm/02_BCODE_SPEC.md](algorithm/02_BCODE_SPEC.md) |
| **와이어 재료** | NiTi/SS/Beta-Ti/CuNiTi 특성 + 계수 | [algorithm/03_WIRE_MATERIALS.md](algorithm/03_WIRE_MATERIALS.md) |
| **카메라 파이프라인** | Vimba X → GStreamer → OpenCV | [hardware/01_EVK_CAMERA_BRINGUP.md](hardware/01_EVK_CAMERA_BRINGUP.md) |
| **부팅 플로우** | U-Boot → Kernel → systemd → M7 load | [architecture/03_BOOTFLOW.md](architecture/03_BOOTFLOW.md) |
| **이관 패키지** | 개발자 handover kit | [handover/README.md](handover/README.md) |

---

## 4. 폴더 구조 맵

```
docs/
├── README.md                               ← 이 문서
│
├── handover/                               개발자 인수인계 패키지
│   ├── README.md                           · 읽는 순서 + 체크리스트
│   ├── 00_QUICK_START_CARD.md              · 1페이지 퀵 카드 (인쇄용)
│   ├── 01_INITIAL_SETUP.md                 · 전원 투입 → 첫 동작 (~5분)
│   ├── 02_SDK_DEVELOPER_GUIDE.md           · SDK 사용법 + API 요약
│   └── 03_TEST_APP_GUIDE.md                · React 대시보드 + 복구 절차
│
├── sdk/                                    애플리케이션 개발자용
│   ├── 01_SDK_GUIDE.md                     · SDK 메인 가이드 (페르소나별)
│   ├── 02_API_REFERENCE.md                 · REST/WS 전체 엔드포인트 스키마
│   ├── 03_MOCK_MODE.md                     · 하드웨어 없이 개발하기
│   ├── 04_DEPLOYMENT.md                    · EVK 배포 / systemd / 운영
│   └── 05_TROUBLESHOOTING.md               · FAQ + 알려진 문제
│
├── architecture/                           시스템 설계 / 부팅 / 이식
│   ├── 01_ARCHITECTURE.md                  · 전체 구조 + 계층 경계
│   ├── 02_HARDWARE_ABSTRACTION.md          · HAL 계층 + 하드웨어 독립성
│   ├── 03_BOOTFLOW.md                      · U-Boot → Kernel → M7 로드
│   └── 04_PORTING.md                       · 타 보드 이식 가이드
│
├── hardware/                               EVK bring-up + 실험 노트
│   ├── 01_EVK_CAMERA_BRINGUP.md            · Allied Vision 카메라 bring-up
│   ├── 02_EVK_REMOTEPROC.md                · A53↔M7 remoteproc 내부
│   └── 03_M7_FREERTOS_EXPERIMENTS.md       · FreeRTOS 실험 노트
│
├── algorithm/                              CAM / B-code / 재료
│   ├── 01_CAD_CAM_GUIDE.md                 · CAD/CAM + OpenCV 통합
│   ├── 02_BCODE_SPEC.md                    · B-code 포맷 명세 + 예제
│   └── 03_WIRE_MATERIALS.md                · 재질 특성 + 스프링백 계수표
│
└── project/                                제품 계획
    └── 01_ROADMAP.md                       · 개발 로드맵 + 마일스톤
```

---

## 5. 역할별 권장 학습 경로

### 5.1 SW 개발자 (SDK 사용자)

보드에 연결해서 API로 모터를 움직이거나 카메라 프레임을 받고 싶은 개발자.

1. [handover/00_QUICK_START_CARD.md](handover/00_QUICK_START_CARD.md) — 보드에 붙기
2. [handover/01_INITIAL_SETUP.md](handover/01_INITIAL_SETUP.md) — 첫 연결 확인
3. [sdk/01_SDK_GUIDE.md](sdk/01_SDK_GUIDE.md) — SDK 메인 가이드
4. [sdk/02_API_REFERENCE.md](sdk/02_API_REFERENCE.md) — 엔드포인트 스키마
5. [sdk/03_MOCK_MODE.md](sdk/03_MOCK_MODE.md) — 장비 없이 개발
6. [sdk/05_TROUBLESHOOTING.md](sdk/05_TROUBLESHOOTING.md) — 막혔을 때

### 5.2 HW / BSP 엔지니어

커널·DTS·부팅·M7 펌웨어를 다루는 개발자.

1. [architecture/01_ARCHITECTURE.md](architecture/01_ARCHITECTURE.md)
2. [architecture/03_BOOTFLOW.md](architecture/03_BOOTFLOW.md)
3. [hardware/01_EVK_CAMERA_BRINGUP.md](hardware/01_EVK_CAMERA_BRINGUP.md)
4. [hardware/02_EVK_REMOTEPROC.md](hardware/02_EVK_REMOTEPROC.md)
5. [hardware/03_M7_FREERTOS_EXPERIMENTS.md](hardware/03_M7_FREERTOS_EXPERIMENTS.md)
6. [architecture/04_PORTING.md](architecture/04_PORTING.md) — 타 보드 이식

### 5.3 알고리즘 / CAM 엔지니어

3D 커브 → 와이어 궤적, 스프링백 보정, 재료 모델을 다루는 개발자.

1. [algorithm/01_CAD_CAM_GUIDE.md](algorithm/01_CAD_CAM_GUIDE.md)
2. [algorithm/02_BCODE_SPEC.md](algorithm/02_BCODE_SPEC.md)
3. [algorithm/03_WIRE_MATERIALS.md](algorithm/03_WIRE_MATERIALS.md)
4. [architecture/02_HARDWARE_ABSTRACTION.md](architecture/02_HARDWARE_ABSTRACTION.md)

### 5.4 규제 / QA / PM

FDA·IEC·ISO 대응과 제품 계획을 다루는 담당자.

1. [architecture/01_ARCHITECTURE.md](architecture/01_ARCHITECTURE.md) — § Safety
2. [project/01_ROADMAP.md](project/01_ROADMAP.md) — 마일스톤

---

## 6. 빠른 시작

### Mock 모드 (노트북에서 즉시 실행)

```bash
cd src/app/server
export OB_MOCK_MODE=1
pip install -r requirements.txt
uvicorn server.main:app --host 0.0.0.0 --port 8000
# → http://localhost:8000/docs  (Swagger UI)
```

### 실기기 (EVK 연결)

```bash
# 보드 전원 → 노트북에서 AP "Ortho-Bender-FBAD" / PW "ortho-bender" 접속
# 브라우저에서 http://192.168.4.1:8000/  또는  http://ortho-bender.local:8000/
```

자세한 이관/배포 절차: [handover/README.md](handover/README.md), [sdk/04_DEPLOYMENT.md](sdk/04_DEPLOYMENT.md)

### Yocto 이미지 빌드

```bash
KAS_BUILD_DIR=build-ortho-bender \
  kas shell kas/base.yml:kas/ortho-bender-dev.yml \
  -c "bitbake ortho-bender-image-dev"
```

### M7 펌웨어 빌드

```bash
cmake -B build-firmware -S src/firmware \
  -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake
cmake --build build-firmware
```

---

## 7. 안전 & 규제

- **FDA Class II (510(k))** — 예측 대상: SureSmile
- **IEC 62304 Software Safety Class B** (모션 크리티컬은 잠재적 Class C)
- **ISO 13485** — Quality Management System
- **ISO 14971** — Risk Management

### 안전 메커니즘

| 항목 | 구현 |
|------|------|
| E-STOP | SW GPIO ISR < 1ms + HW DRV_ENN 라인 동시 차단 (dual-path) |
| Watchdog | M7 200ms timeout, 메인 루프에서 pet |
| Stack overflow | FreeRTOS 모든 태스크 감지 활성화 |
| 모터 진단 | StallGuard2 폴링 200Hz (overtemp / short / open-load) |
| ROM check | 모든 이동 명령은 백엔드 ROM 체크 후 M7 전달 |
| 재료 안전 | NiTi는 Af 온도 이상 가열 강제, 재료 DB 기반 스프링백 보정 |

⚠️ **개발 중 안전 로직을 우회하지 마세요.** 상세: [architecture/01_ARCHITECTURE.md](architecture/01_ARCHITECTURE.md) § Safety, [project/01_ROADMAP.md](project/01_ROADMAP.md).

---

## 참고

- 루트 [`README.md`](../README.md) — 프로젝트 최상위 개요 + 빌드 커맨드
- 루트 [`CLAUDE.md`](../CLAUDE.md) — 아키텍처 요약 (개발 자동화용)
- `.claude/rules/` — 프로젝트 코딩 규칙 + 프로젝트 규칙
- `src/shared/ipc_protocol.h` — A53 ↔ M7 IPC 프로토콜 정의 (Single Source of Truth)
