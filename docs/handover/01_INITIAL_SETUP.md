# 01 - 초기 셋업 사용자 매뉴얼

**대상**: 이관 받은 개발자
**소요 시간**: 약 5분
**필요 장비**: 보드, 전원 어댑터, 노트북(WiFi 가능)

---

## 1. 패키지 구성품 확인

| # | 품목 | 수량 | 비고 |
|---|------|------|------|
| 1 | Ortho-Bender 메인 보드 (i.MX8MP EVK) | 1 | 카메라 J6 포트 장착 상태 |
| 2 | DC 12V 전원 어댑터 | 1 | 보드 DC-Jack 전용 |
| 3 | 복구 USB 메모리 | 1 | eMMC 원본 이미지 + uuu |
| 4 | 퀵스타트 카드 | 1 | 접속 정보 요약 |
| 5 | 매뉴얼 PDF (01~03) | 1세트 | 본 문서 포함 |

보드 윗면에 접속 정보 라벨이 부착되어 있습니다. 라벨 값과 본 문서의 값이 다르면 **라벨 값이 우선**합니다.

---

## 2. 첫 부팅

### 2.1 전원 투입
1. 보드 오른쪽 DC-Jack에 전원 어댑터 연결
2. 보드 옆 전원 스위치 **ON**
3. 부팅 LED 점등 확인 (약 30초 소요)

### 2.2 부팅 완료 확인
부팅이 완료되면 자동으로 다음이 실행됩니다:

- `wpa_supplicant` 및 `hostapd` (WiFi STA + AP 동시 모드)
- `ortho-bender-ap` (uap0 인터페이스 + DHCP 서버 + WiFi AP)
- `ortho-bender-sdk` (FastAPI 백엔드, 포트 8000)
- `avahi-daemon` (mDNS, `ortho-bender.local`)
- `dropbear.socket` (SSH)

부팅 완료까지 **약 60초**. 서두르지 말고 LED가 안정될 때까지 기다려 주세요.

---

## 3. 노트북에서 보드 접속

### 3.1 WiFi 접속 (기본 경로)

노트북의 WiFi 목록에서 보드가 송출하는 AP를 선택합니다.

| 항목 | 값 |
|------|------|
| **SSID** | `Ortho-Bender-FBAD` |
| **보안** | WPA2-PSK |
| **비밀번호** | `ortho-bender` |
| **채널** | 6 (2.4 GHz, 대부분 노트북 호환) |
| **보드 IP** | `192.168.4.1` |
| **노트북 IP** | DHCP로 `192.168.4.100~200` 중 자동 할당 |

접속 성공 여부는 노트북 셸에서 확인:
```bash
ping 192.168.4.1
```
응답 오면 성공.

### 3.2 브라우저에서 대시보드 열기

아래 중 **하나**를 입력:

```
http://192.168.4.1:8000/
http://ortho-bender.local:8000/
```

Ortho-Bender SDK Dashboard가 표시되면 정상. 좌측 사이드바에서 `Dashboard`, `Motor`, `Camera`, `Bending`, `Simulation`, `Connect`, `Settings` 메뉴를 확인할 수 있습니다.

### 3.3 SSH 접속 (개발 편의)

```bash
ssh root@192.168.4.1
# 또는
ssh root@ortho-bender.local
```

| 항목 | 값 |
|------|------|
| **사용자** | `root` |
| **비밀번호** | `ortho-bender` |

> ⚠️ 운영 배포 전에 반드시 비밀번호를 변경하고 pubkey 전용으로 전환하세요. 본 값은 개발 이관용 임시 자격입니다.

---

## 4. 대체 접속 경로

### 4.1 이더넷 (유선)

| 경로 | 설정 |
|------|------|
| **고정 IP** | 노트북을 `192.168.77.1/24`로 설정 후, 보드 `192.168.77.2`로 접속 |
| **DHCP** | 회사 네트워크 스위치 사용 시 eth0에 IP 자동 할당 (대시보드 Settings 페이지에서 확인 가능) |

### 4.2 mDNS (이름 기반)

노트북에 Avahi/Bonjour가 설치되어 있으면 IP 대신 이름으로 접속 가능:
```
ortho-bender.local
```
- macOS: 기본 지원
- Windows: iTunes 또는 Bonjour Print Services 설치 필요
- Linux: `avahi-daemon` + `libnss-mdns` 설치

---

## 5. 첫 동작 확인 체크리스트

보드 접속 후 대시보드에서 다음을 순서대로 확인:

- [ ] **Dashboard 페이지**: System status가 `OK`, motion_state=`0 (IDLE)`, cpu_temp 표시
- [ ] **Camera 페이지**: `Connect` 클릭 → 비디오 프리뷰 표시 (카메라 J6 장착 상태)
- [ ] **Motor 페이지**: 각 축 `Enable` 클릭 → 상태 변경, `Jog` 버튼 정상 응답 (Mock 모드에서는 가상 상태)
- [ ] **Connect 페이지 → WiFi 탭**: `Scan` 버튼 클릭 → 주변 AP 목록 표시 (7~8초 소요)
- [ ] **SSH**: `ssh root@192.168.4.1` 정상 로그인, `systemctl status ortho-bender-sdk` `active (running)`

5개 항목 모두 통과하면 개발 시작 가능 상태입니다.

---

## 6. 문제 발생 시

### 6.1 AP 신호가 보이지 않을 때
1. 전원 LED 확인
2. 부팅 완료까지 60초 대기 (재시도)
3. 노트북 WiFi 드라이버가 2.4 GHz 채널 6을 지원하는지 확인
4. 여전히 안 보이면 **이더넷 경로**로 접속 후 로그 확인:
   ```bash
   journalctl -u ortho-bender-ap -n 50
   journalctl -u hostapd -n 50
   ```

### 6.2 대시보드가 안 열릴 때
1. ping 성공 여부 확인 (`ping 192.168.4.1`)
2. SSH 접속해서 백엔드 상태 확인:
   ```bash
   systemctl status ortho-bender-sdk
   curl -s http://127.0.0.1:8000/api/system/status
   ```
3. 로그:
   ```bash
   journalctl -u ortho-bender-sdk -n 100
   ```

### 6.3 완전 복구 (최후 수단)
eMMC 이미지를 복원합니다. `03_TEST_APP_GUIDE.md`의 부록 B "복구 절차"를 참조하세요. 복구 USB 메모리에 `uuu` 실행 파일과 `ortho-bender-handover-*.wic` 이미지가 포함되어 있습니다.

---

## 7. 다음 단계

- 개발 API 사용법 → `02_SDK_DEVELOPER_GUIDE.md`
- 테스트 앱(React 대시보드) 구조 및 커스터마이징 → `03_TEST_APP_GUIDE.md`
- 전체 API 레퍼런스 → `../API_REFERENCE.md`
- 아키텍처 개요 → `../ARCHITECTURE.md`
- 하드웨어 추상화 계층 → `../HARDWARE_ABSTRACTION.md`
