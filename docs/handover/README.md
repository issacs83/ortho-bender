# Ortho-Bender Developer Handover Package

이 디렉토리는 이관 받은 개발자를 위한 **스탠드얼론 문서 세트**입니다. 보드 전원만 넣으면 바로 개발을 시작할 수 있도록 구성되어 있습니다.

## 읽는 순서

1. **`00_QUICK_START_CARD.md`** — 1페이지 요약 (인쇄 동봉용)
2. **`01_INITIAL_SETUP.md`** — 전원 투입부터 첫 동작 확인까지 (~5분)
3. **`02_SDK_DEVELOPER_GUIDE.md`** — SDK 사용법, REST/WebSocket API 요약, 개발 패턴
4. **`03_TEST_APP_GUIDE.md`** — React 대시보드 사용법 + 커스터마이징 + 복구 절차

## 관련 상세 문서

본 핸드오버 패키지는 기존 SDK 문서를 참조합니다. 깊이 있는 정보는 아래로:

| 주제 | 파일 |
|------|------|
| 전체 API 레퍼런스 | [`../API_REFERENCE.md`](../API_REFERENCE.md) |
| 아키텍처 | [`../ARCHITECTURE.md`](../ARCHITECTURE.md) |
| HW 추상화 | [`../HARDWARE_ABSTRACTION.md`](../HARDWARE_ABSTRACTION.md) |
| Mock 모드 | [`../MOCK_MODE.md`](../MOCK_MODE.md) |
| 배포/빌드 | [`../DEPLOYMENT.md`](../DEPLOYMENT.md) |
| 트러블슈팅 | [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) |
| B-code 스펙 | [`../BCODE_SPEC.md`](../BCODE_SPEC.md) |
| CAD/CAM 가이드 | [`../CAD_CAM_GUIDE.md`](../CAD_CAM_GUIDE.md) |
| 와이어 재료 | [`../WIRE_MATERIALS.md`](../WIRE_MATERIALS.md) |

## 이관 담당자 체크리스트

패키징 전 확인:

- [ ] 보드 eMMC 에 최신 빌드 배포 완료 (`/opt/ortho-bender/` 최신)
- [ ] `ortho-bender-sdk`, `ortho-bender-ap`, `avahi-daemon`, `systemd-networkd`, `dropbear.socket` 모두 enabled
- [ ] AP SSID/PW 가 라벨과 일치 (`Ortho-Bender-FBAD` / `ortho-bender`)
- [ ] root 비밀번호 설정됨 (`ortho-bender`)
- [ ] 카메라 J6 장착 및 정상 enumeration 확인
- [ ] eMMC 전체 이미지 백업 생성 (`ortho-bender-handover-YYYYMMDD.wic`)
- [ ] 복구 USB 에 uuu + wic 이미지 복사
- [ ] 콜드 부팅 3회 테스트 통과 (30~60초 내 서비스 기동)
- [ ] 낯선 노트북으로 5단계 시나리오 End-to-End 검증
- [ ] 보드 상단에 라벨 부착
- [ ] 문서 01~03 PDF 인쇄 + 퀵스타트 카드 + 패키지 동봉
