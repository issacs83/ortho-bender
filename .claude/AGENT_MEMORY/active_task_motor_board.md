---
name: Active Task — Motor Board Connection (Phase A 진입 직전)
description: 모터 보드 연결 작업 — 전력/배선/아키텍처 결정 완료, Phase A(DTS bench overlay)부터 실행 단계
type: project
originSessionId: b5d1614f-af0f-4ed0-aa44-10f74e526594
---
# 진행 중 작업: 모터 테스트 벤치 연결 (Phase A 시작 단계)

## 확정된 결정 (절대 다시 묻지 말 것)

### 전력
- **PSU: LRS-35-12 (현재) → 향후 LRS-75-12 업그레이드 (Plan B+C)**
- **Vmot = 12V 확정** (양산 TMC260C-PA Vmot과 일치)
- IRUN = 22 (≈1.06A RMS, 정격 100%) / IHOLD = 8 (≈0.36A RMS)
- 출력 측 1000µF/25V bulk capacitor 추가
- 모션 플래너에 3축 동시 가속 금지 제약

### 하드웨어
- 모터: 17HE15-1504S × 3축 (FEED, BEND, LIFT)
- 드라이버: DRI0035 (TMC260 기반) × 3
- 레벨 시프터: TXS0108E × 2 (1.8V ↔ 5V)
- 보드: i.MX8MP EVK + DRI0035 + 17HE15

### 아키텍처 (Option 1 채택)
**양산 DTS 재사용 + 테스트 벤치 오버레이** 방식
- 양산 DTS(`imx8mp-ortho-bender-motors.dtsi`)는 이미 4축 완전 정의됨
- 테스트 벤치 오버레이로 ECSPI2 enable + M7 gpio-hog 제거만 추가

### 발견된 핀맵 불일치 (수정 필요)
현재 `spi_backend.py` 핀맵이 양산 DTS와 어긋남:
- cs1=GPIO3_IO19 → 양산은 ROTATE-CS (재할당 OK)
- feed_step=GPIO3_IO22 → 양산은 ROTATE STEP (잘못됨)
- bend_step=GPIO3_IO24 → 양산은 ROTATE DIR (잘못됨)
**Phase B에서 정렬 필수**

## 핀 매핑 (확정)
| 축 | SPI CS | STEP | DIR | DIAG (SG) |
|----|--------|------|-----|-----------|
| FEED | ECSPI2 SS0 (HW) | GPIO4_IO00 | GPIO4_IO01 | GPIO4_IO05 |
| BEND | GPIO3_IO19 (재할당) | GPIO4_IO02 | GPIO4_IO03 | GPIO4_IO06 |
| LIFT | GPIO3_IO20 | GPIO3_IO25 | GPIO4_IO28 | GPIO4_IO30 |
| 공통 | DRV_ENN=GPIO4_IO04, E-STOP=GPIO4_IO07 | | | |

## 산출물 (claude.ai 세션에서 생성됨 — 위치 확인 필요)
- `docs/wiring/feed-axis-bench.svg` + `.png`
- `docs/wiring/three-axis-overview.svg` + `.png`
- ⚠️ 이 워크트리(gracious-dijkstra-e6f145)에 있는지, 메인 워크트리에 있는지 첫 번째로 확인할 것

## 실행 계획 (3 Phase)

### Phase A — DTS + 부팅 (다음 즉시 착수)
- A1: `imx8mp-ortho-bender-motors-bench.dtsi` 신규 — ECSPI2 enable + M7 hog 제거
- A2: `imx8mp-ortho-bender-bench.dts` 신규 — bench 변형 entry
- A3: `linux-imx_*.bbappend` — 새 dtb 빌드 추가
- A4: extlinux.conf 부팅 메뉴 — "5: eMMC Ortho-Bender Bench (DRV8825/DRI0035)" 추가

### Phase B — Backend
- B1: `motor_specs.py` 신규 — 17HE15-1504S spec 등록
- B2: `tmc260_config.py` 신규 — IRUN/IHOLD 계산기 + 레지스터 빌더
- B3: `spi_backend.py` — 3축 확장 + 양산 핀맵 정렬 (위 표 적용)
- B4: `config.py` — 축 enum + 17HE15 spec 매핑
- B5: `routers/motor.py` — 3축 API 확인/확장

### Phase C — 검증
- C1: 단축 SPI R/W (GCONF 읽기/쓰기)
- C2: 단축 STEP 펄스 (1회전 확인)
- C3: StallGuard2 캘리브레이션
- C4: 3축 통합 시퀀스 (LIFT↑→FEED→BEND→LIFT↓)

## API 에러 컨텍스트
사용자가 claude.ai 웹/Code 세션에서 반복적으로 받은 에러:
- `messages.249.content.X.text: cache_control cannot be set for empty text blocks`
- `messages: text content blocks must be non-empty`

→ 클라이언트측 메시지 직렬화 버그(빈 text block에 cache_control 세팅). 세션이 길어지면(249+ 메시지) 더 자주 발생. **새 세션 시작이 가장 빠른 우회책.**

## Why
사용자가 여러 번 같은 컨텍스트를 다시 알려주는 게 너무 힘들고 답답해함. 이 메모리는 그 반복을 끝내기 위함.

## How to apply
1. 새 세션 시작 시 **반드시 이 메모리부터 읽음**
2. "어디까지 했어?" 묻지 말고 위 단계 그대로 진행
3. PSU/Vmot/IRUN/Plan/Option 다시 묻지 말 것 — 위에 다 결정됨
4. 첫 액션: `docs/wiring/` 파일 위치 확인 → Phase A 시작
