---
name: ⚠️ 모터 드라이버 보드 정정 — DRI0035 → Veyron 1x2A 가능성
description: 사용자 사진 (2026-05-01)에서 실제 보드는 DFROBOT Veyron 1x2A v0.1로 확인. 메모리의 DRI0035 가정 재검토 필수.
type: project
---

# 모터 드라이버 보드 정정

## 사용자 사진 (2026-05-01 11:58)
사진 파일: `/home/issacs/work/projects/claude-dev-forge/dashboard/public/uploads/1777604331688-telegram-photo.jpg`

명확히 보이는 라벨: **"DFROBOT Veyron 1x2A v0.1 Stepper Motor Shield"** × 3개

## 메모리 vs 실물 차이
| 항목 | 메모리 (가정) | 실물 (사진) |
|------|--------------|-------------|
| 보드명 | DRI0035 (TMC260C 기반) | Veyron 1x2A v0.1 |
| 핀 배치 | DRI0035 핀맵 | 다를 가능성 |
| 드라이버 IC | TMC260C | TMC2160 또는 TMC2208 추정 (사진에서 chip mark 미확인) |
| IRUN 계산 | TMC260 식 | 칩셋에 따라 다름 |

## 사진에서 보이는 핀 라벨 (3개 보드 동일)
- 좌측 4-pin terminal: B2 B1 A2 A1 (모터 코일 4선)
- 하단 5-pin terminal: DIR SG STE EN PWR (또는 비슷)
- 좌상단 expansion: SCL SDA MISO ... (Arduino 호환)
- Power 표시: Vin

## 영향 받는 메모리/결정사항
### `active_task_motor_board.md` 재검토 필요
- 핀맵 (FEED/BEND/LIFT)
- IRUN/IHOLD 계산 (TMC260 vs Veyron)
- TXS0108E 매핑 (Veyron이 5V tolerant인지)
- DRV_ENN 위치

### `docs/wiring/feed-axis-bench.png`, `three-axis-overview.png` 재검토 필요
- DRI0035 가정으로 그림. Veyron으로 다시 그려야 할 수도

## 다음 단계
1. Veyron 1x2A v0.1 데이터시트 확보 (DFROBOT wiki)
2. 실제 IC 마킹 사용자에게 추가 사진 요청
3. 핀맵 / IRUN 재계산 / 배선도 업데이트
4. **이미 작성된 `imx8mp-ortho-bender-motors-bench.dtsi`도 영향 받음**

## How to apply
- DTS bench overlay (Phase A1 결과물)는 일단 그대로 두되, Phase B (backend) 들어가기 전에 검증
- 사용자 추가 사진 (IC 마킹) 받으면 정확한 칩셋 확정
- 그 전에 진행은 가능 (SPI는 일반 spidev로 작동)
