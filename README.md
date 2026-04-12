# Ortho-Bender — Dental Orthodontic Wire Bending Machine

NXP i.MX8MP 기반 치과 교정 와이어 벤딩머신. 3D 치료 계획을 입력받아 환자 맞춤형
교정 와이어를 정밀하게 자동 생산합니다.

> **SW 개발자용 프로젝트입니다** — 하드웨어는 REST API + WebSocket 뒤에 완전히
> 추상화되어 있어, 펌웨어나 GenICam 같은 저수준을 몰라도 됩니다.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      NXP i.MX8MP SoC                         │
│                                                              │
│  ┌──────────────────────────┐  ┌───────────────────────────┐ │
│  │  Cortex-A53 x4 (Linux)   │  │   Cortex-M7 (FreeRTOS)    │ │
│  │                          │  │                           │ │
│  │  FastAPI SDK ┐           │  │  Trajectory Manager       │ │
│  │   ├─ /api/motor          │  │  (current impl)           │ │
│  │   ├─ /api/camera         │◄─┤  TMC260C-PA STEP/DIR x4   │ │
│  │   ├─ /api/bending        │  │  StallGuard2 diagnostics  │ │
│  │   ├─ /api/cam            │  │  E-STOP + Watchdog        │ │
│  │   └─ /ws/{motor,camera}  │  └───────────────────────────┘ │
│  │                          │             │ RPMsg IPC        │
│  │  React frontend ─────────┘             │                  │
│  │  VmbPy camera ◄──────── Allied Vision 1800 U-158m (USB3) │
│  │                           (current impl — 교체 투명)     │
│  │  NPU 2.3 TOPS ───────── Springback ML + Defect Detection │
│  └──────────────────────────┘                                │
└──────────────────────────────────────────────────────────────┘
```

- **A53 (Linux/Yocto)**: FastAPI SDK 백엔드, React 프론트엔드, CAM 엔진, NPU 추론, 비전
- **M7 (FreeRTOS)**: 모션 궤적 관리, TMC260C-PA STEP/DIR 제어, 안전 시스템
- **IPC**: RPMsg 기반 양방향 메시지
- **SDK**: Python FastAPI, Pydantic v2, WebSocket, VmbPy

---

## 5분 Quick Start

### 1) 백엔드 기동 (로컬 Mock — 하드웨어 없음)
```bash
cd src/app/server
pip install -r requirements.txt
OB_MOCK_MODE=true python3 -m uvicorn server.main:app --reload --port 8000
```

### 2) Health check
```bash
curl http://localhost:8000/health
# {"status":"ok"}

open http://localhost:8000/docs    # Swagger UI (OpenAPI)
```

### 3) 첫 B-code 실행 (Python)
```bash
pip install httpx
python3 src/app/sdk-examples/python/basic_bend.py --host http://localhost:8000
```

### 4) 실기기로 붙이기
```bash
# EVK (i.MX8MP) 측
OB_MOCK_MODE=false GENICAM_GENTL64_PATH=/opt/VimbaX_2026-1/cti \
  python3 -m uvicorn server.main:app --host 0.0.0.0 --port 8000

# 클라이언트 측
python3 basic_bend.py --host http://192.168.77.2:8000
```

---

## SW 개발자별 진입점

| Persona | 진입 문서 | 핵심 엔드포인트 |
|--------|----------|----------------|
| 🎨 **프론트엔드** | [docs/SDK_GUIDE.md §5](docs/SDK_GUIDE.md) | `/api/motor`, `/ws/motor`, `/ws/system` |
| 📐 **CAD / CAM** | [docs/CAD_CAM_GUIDE.md](docs/CAD_CAM_GUIDE.md) (+ [BCODE_SPEC](docs/BCODE_SPEC.md), [WIRE_MATERIALS](docs/WIRE_MATERIALS.md)) | `/api/cam/*`, `/api/bending/*` |
| 👁 **Vision / ML** | [docs/SDK_GUIDE.md §7](docs/SDK_GUIDE.md) | `/api/camera/*`, `/ws/camera` |
| 🛠 **DevOps / 통합** | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | systemd, 로깅, 네트워킹 |

---

## 문서 인덱스

### SDK 사용자
- [**SDK_GUIDE.md**](docs/SDK_GUIDE.md) — 메인 사용 가이드 (persona별)
- [**ARCHITECTURE.md**](docs/ARCHITECTURE.md) — 전체 시스템 구조 및 계층 경계
- [**HARDWARE_ABSTRACTION.md**](docs/HARDWARE_ABSTRACTION.md) — 카메라/모터 교체 투명성 설명
- [**CAD_CAM_GUIDE.md**](docs/CAD_CAM_GUIDE.md) — CAD/CAM + OpenCV 통합 개발 가이드 (테스트 코드 포함)
- [**API_REFERENCE.md**](docs/API_REFERENCE.md) — REST/WebSocket 전체 레퍼런스
- [**BCODE_SPEC.md**](docs/BCODE_SPEC.md) — B-code 포맷 명세
- [**WIRE_MATERIALS.md**](docs/WIRE_MATERIALS.md) — 재질 특성 + 스프링백 계수
- [**MOCK_MODE.md**](docs/MOCK_MODE.md) — 하드웨어 없이 개발
- [**TROUBLESHOOTING.md**](docs/TROUBLESHOOTING.md) — FAQ + 알려진 문제
- [**DEPLOYMENT.md**](docs/DEPLOYMENT.md) — EVK 배포 / 운영
- [**CHANGELOG.md**](CHANGELOG.md) — 버전별 변경 사항

### 하드웨어 / 시스템 (내부용)
- [docs/bootflow.md](docs/bootflow.md) — 부팅 시퀀스
- [docs/evk-camera-bringup.md](docs/evk-camera-bringup.md) — 카메라 bring-up
- [docs/evk-remoteproc-analysis.md](docs/evk-remoteproc-analysis.md) — A53↔M7 remoteproc
- [docs/m7-freertos-experiments.md](docs/m7-freertos-experiments.md) — FreeRTOS 실험 노트
- [docs/PORTING.md](docs/PORTING.md) — 보드 포팅 가이드
- [docs/ROADMAP.md](docs/ROADMAP.md) — 제품 로드맵

---

## 빌드

```bash
# M7 firmware
cmake -B build-firmware -S src/firmware \
  -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake
cmake --build build-firmware

# A53 C++ application (host test build)
cmake -B build-app -S src/app
cmake --build build-app

# Full Yocto image (EVK 플래싱용)
KAS_BUILD_DIR=build-ortho-bender kas shell kas/base.yml:kas/ortho-bender-dev.yml \
  -c "bitbake ortho-bender-image-dev"

# Frontend (개발 서버)
cd src/app/frontend
npm install && npm run dev
```

---

## Project Structure

```
src/
├── app/
│   ├── server/          FastAPI SDK 백엔드 (routers, services, models, ws)
│   ├── frontend/        React 대시보드 (Vite + TypeScript)
│   ├── cam/             C++ CAM 엔진 (production 경로)
│   ├── sdk-examples/    Python + cURL 예제
│   └── ...              GUI, PatDB, NPU, Vision
├── firmware/            M7 FreeRTOS 펌웨어 (TMC 드라이버, motion, safety)
└── shared/              A53↔M7 공유 헤더 (ipc_protocol.h)

meta-ortho-bender/        Yocto layer (recipes-bsp/, recipes-core/, ...)
kas/                      KAS build manifests
tests/                    Unit + integration tests
docs/                     프로젝트 문서
```

---

## 규제 분류

- **FDA Class II** 510(k) — predicate: SureSmile
- **IEC 62304** Software Safety Class B
- **ISO 13485** Quality Management System
- **ISO 14971** Risk Management

---

## 라이선스

Proprietary — All rights reserved. © 2026 Quarkers.
