# Changelog

Ortho-Bender 프로젝트의 주요 변경 사항. [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) 형식을 따릅니다.

버전 규칙: `MAJOR.MINOR.PATCH` (SemVer)

---

## [Unreleased] — 2026-04-12

### Added
- **SDK 백엔드 (FastAPI)**
  - `src/app/server/` 디렉토리 신규 — Python FastAPI + Pydantic v2 기반 REST + WebSocket SDK
  - 엔드포인트: `/api/motor`, `/api/camera`, `/api/bending`, `/api/cam`, `/api/system`, `/api/wifi`
  - WebSocket: `/ws/motor` (10 Hz), `/ws/camera`, `/ws/system`
  - Mock 모드 (`OB_MOCK_MODE=true`) — 하드웨어 없이 풀 스택 개발 지원
  - 자동 폴백: IPC / 카메라 각각 독립적으로 mock 폴백

- **3D 커브 → B-code CAM 서비스**
  - `src/app/server/services/cam_service.py` — 순수 Python 이산화/torsion/스프링백 보정
  - `/api/cam/generate` (프리뷰) + `/api/cam/execute` (생성 + 디스패치)
  - 입력 정점 2~512 개, 출력 최대 128 스텝, 재질별 보정 계수 자동 적용

- **Mock B-code 시뮬레이션**
  - `ipc_client.py` 에 `_simulate_bcode` 추가 — step-by-step position/velocity 실시간 갱신
  - `/ws/motor` 10 Hz 스트림으로 프론트엔드 게이지 애니메이션 검증 가능

- **React 프론트엔드 뼈대**
  - `src/app/frontend/` — Vite + TypeScript + React
  - dev proxy (`/api`, `/ws`) 로 EVK 백엔드와 직접 연동

- **Python SDK 예제**
  - `basic_bend.py` — 3-step 벤딩 튜토리얼
  - `cam_from_curve.py` — 3D 폴리라인 → B-code → 실행
  - `camera_stream.py` — REST 스냅샷 + WebSocket 라이브 스트림
  - `curl/api_examples.sh` — cURL 요리책

- **문서 (Tier 1 SDK 문서 세트)**
  - `README.md` — 프로젝트 얼굴 전면 개편, 5분 퀵스타트 + persona 진입점
  - `docs/SDK_GUIDE.md` — 메인 사용 가이드
  - `docs/API_REFERENCE.md` — 전체 REST/WS 레퍼런스 + 에러 코드 카탈로그
  - `docs/BCODE_SPEC.md` — B-code 포맷 명세 + 좌표계 + 예제
  - `docs/WIRE_MATERIALS.md` — 4개 재질 특성 + 스프링백 계수표
  - `docs/DEPLOYMENT.md` — EVK 배포 / 운영 / systemd
  - `docs/MOCK_MODE.md` — 하드웨어 없이 개발하기
  - `docs/TROUBLESHOOTING.md` — FAQ + 긴급 복구

- **TMC 드라이버 변종**
  - `tmc5072.c/.h`, `tmc5130.c/.h` 신규 — TMC260C-PA (기본) 외 추가 드라이버 호환성
  - `hal_gpio.h`, `hal_spi.h` HAL 리팩토링

- **Device Tree 개편**
  - `imx8mp-ortho-bender-{camera,motors,sensors,m7,wifi}.dtsi` 정리/분할
  - `fragments/` 디렉토리 — 선택적 기능 오버레이

### Changed
- **bending 라우터 진행률 추적 개선**
  - `bending_execute` 가 백그라운드 태스크를 생성하여 motor status 를 10 Hz 폴링
  - `_state.current_step` 이 실시간으로 갱신되어 `/api/bending/status` 가 정확한 진행률 반환

- **camera_service CTI 경로 기본값**
  - `/opt/VimbaX_2026-1/cti` 로 업데이트 (EVK VimbaX 설치 위치)

- **프로젝트 규칙 정리**
  - SDK 아키텍처 섹션 추가 (FastAPI 백엔드가 유일한 SW 인터페이스)
  - 카메라 프로토콜 U3V 명시 (UVC 아님)
  - TMC260C-PA STEP/DIR + M7 GPT timer 구동 모델 명문화

### Fixed
- **Mock IPC B-code 헤더 파싱 버그**
  - `MSG_MOTION_EXECUTE_BCODE` 페이로드 offset 이 잘못되어 59899-step 가비지가 생성되던 문제 수정
  - 올바른 offset (0~1=step_count, 8+=steps) 로 교정

- **bending 시퀀스 완료 상태 전이**
  - RUNNING → IDLE 전이 시 `_state.running = false` 가 누락되던 문제 수정

### Security
- 민감 정보 스캔: API 키 / 패스워드 / 토큰 하드코딩 없음 확인 (배포 전)

### Known Issues
- 실기기 `pydantic` 은 `zoneinfo` shim 필요 (Yocto Python 3.10 stdlib 부재)
- `OpenCV` 가 EVK 에 기본 설치되지 않음 → 없을 시 VmbPy 프레임이 JPEG 인코딩 되지 않음
- WiFi 라우터는 NetworkManager 설정 저장만 구현, 실제 연결 로직은 Phase 2

---

## [0.2.0] — 2026-03 (이전 작업, 커밋만 존재)

### Added
- VmbPy 기반 Allied Vision 1800 U-158m 카메라 백엔드 (`c113823`)
- RPMsg 자동 디스커버리 (`c113823`)
- M7 RPMsg IPC 부팅 실패 수정 + TMC260C-PA 마이그레이션 (`f217959`)
- KC test recipe cherry-pick, motor_sim deadlock 수정 (`afebb05`)
- Virtual test environment + 웹 대시보드 + 모션 시각화 (`80cb3f5`)
- wire_materials / cam_engine 단위 테스트 (`59efe09`)

---

## [0.1.0] — 초기 스켈레톤

### Added
- NXP i.MX8MP 기본 Yocto 빌드 (kas + meta-ortho-bender)
- M7 FreeRTOS firmware 스켈레톤 + TMC 드라이버 초안
- A53 Qt6 GUI 스켈레톤
- OV5640 MIPI CSI 카메라 bring-up 가이드
- EVK 커넥터 매핑 + PWDN GPIO 문서

---

## 버전 정책

- **MAJOR**: API envelope 변경, endpoint 제거, breaking IPC 프로토콜
- **MINOR**: 신규 endpoint, 신규 재질, 신규 드라이버, 신규 문서 세트
- **PATCH**: 버그 수정, 로그 개선, 문서 오타

## Unreleased → 다음 릴리스 태깅 조건

다음 항목이 완료되면 `v0.3.0` 으로 태깅 예정:
- [ ] 실기기에서 전체 벤딩 시퀀스 검증 (모터 드라이버 수령 후)
- [ ] NPU 스프링백 예측 모델 통합
- [ ] React 프론트엔드 MVP (motor/camera/bending 3 페이지)
- [ ] systemd 서비스 유닛 추가
- [ ] CI 파이프라인 (GitHub Actions 에서 pytest + mock mode)
