# 03 - 테스트 앱 가이드 (Ortho-Bender SDK Dashboard)

**대상**: 이관 받은 개발자
**전제**: `01_INITIAL_SETUP.md` 완료, `02_SDK_DEVELOPER_GUIDE.md` 훑어봄

이 문서는 보드에 미리 설치된 **테스트 앱 (React 기반 대시보드)** 의 기능 및 커스터마이징 방법을 설명합니다.

---

## 1. 테스트 앱이란

- **이름**: Ortho-Bender SDK Dashboard
- **역할**: SDK가 정상 동작함을 시각적으로 검증하는 레퍼런스 클라이언트
- **위치**:
  - 보드 배포본: `/opt/ortho-bender/frontend-dist/` (FastAPI가 `/` 경로에 정적으로 서빙)
  - 소스 코드: `src/app/frontend/` (Git 저장소 내)
- **접속**: `http://192.168.4.1:8000/` 또는 `http://ortho-bender.local:8000/`

테스트 앱은 **별도 서비스가 아니라** `ortho-bender-sdk.service` 백엔드가 빌드된 dist를 정적 파일로 함께 호스팅합니다. 별도 포트/서비스 불필요.

---

## 2. 화면 구성

좌측 사이드바에 7개 페이지:

| 페이지 | 호출 API | 역할 |
|--------|----------|------|
| **Dashboard** | `GET /api/system/status`, `WS /ws/system` | 전체 헬스 요약 (motion_state, temp, alarms) |
| **Motor** | `/api/motor/*`, `WS /ws/motor` | 4축 모터 enable, jog, home, 상태 모니터 |
| **Camera** | `/api/camera/*`, `WS /ws/camera` | 카메라 연결, 프리뷰 스트림, 단일 프레임 캡처 |
| **Bending** | `/api/bending/*`, `WS /ws/bending` | B-code 업로드, 시퀀스 실행/일시정지, 진행률 |
| **Simulation** | `/api/simulation/*` | 3D 곡선 입력 → B-code 변환 미리보기, 스프링백 시뮬 |
| **Connect** | `/api/wifi/*` | WiFi STA 스캔/연결, Bluetooth (추후) |
| **Settings** | `/api/system/*` | SDK 버전 표시, 시스템 재부팅, 로그 보기 |

각 페이지는 SDK의 특정 카테고리 API를 그대로 사용합니다. **브라우저 개발자 도구(Network 탭)를 열어두면 어떤 요청이 나가는지 실시간으로 볼 수 있어** SDK 학습에 매우 유용합니다.

---

## 3. 자주 쓰는 작업 흐름

### 3.1 하드웨어 동작 확인 (smoke test)
1. **Dashboard** → motion_state가 `0 (IDLE)`, `ipc_connected=true`, `camera_connected=true` 인지 확인
2. **Motor** → 축 1 Enable → Jog +10mm → 위치 증가 확인 → Disable
3. **Camera** → Connect → 프리뷰 스트림 확인 → 단일 프레임 다운로드
4. **Connect / WiFi 탭** → Scan → 주변 AP 목록 확인 (AP 모드와 STA 병행 동작 확인)

### 3.2 B-code 업로드 후 실행
1. **Simulation** → 샘플 곡선 로드 → Convert → B-code 생성 확인 → Download
2. **Bending** → Upload → 생성된 B-code 파일 선택 → Preview → Start
3. WebSocket으로 진행률/완료 상태 표시

### 3.3 시스템 로그 보기
1. **Settings** → View Logs → 최근 100줄 조회
2. SSH가 편하면:
   ```bash
   ssh root@192.168.4.1
   journalctl -u ortho-bender-sdk -n 200
   ```

---

## 4. 커스터마이징 (소스 수정)

### 4.1 개발 환경 셋업 (로컬 PC)

```bash
git clone <repo>
cd ortho-bender/src/app/frontend
npm install
```

### 4.2 Mock 모드 또는 실장비 백엔드 선택

프론트엔드는 기본적으로 **상대 경로**(`/api/...`)로 API를 호출하므로, Vite dev server의 프록시 또는 실장비 IP를 통해 백엔드에 도달합니다.

**방법 A: 노트북에서 Mock 백엔드 + Vite dev server**
```bash
# Terminal 1: 로컬 백엔드 (Mock)
cd src/app/server
export OB_MOCK_MODE=1
uvicorn server.main:app --host 0.0.0.0 --port 8000

# Terminal 2: Vite dev server
cd src/app/frontend
npm run dev -- --host 0.0.0.0
# → http://localhost:5173/
```
Vite는 `/api`와 `/ws`를 `localhost:8000` 으로 프록시합니다 (`vite.config.ts` 참조).

**방법 B: 실장비 백엔드에 원격 Vite 연결**
```bash
# 노트북의 Vite dev server를 실장비 백엔드에 붙임
cd src/app/frontend
# vite.config.ts 의 proxy target 을 임시로 http://192.168.4.1:8000 으로 변경
npm run dev -- --host 0.0.0.0
```

### 4.3 페이지 추가/수정

```
src/app/frontend/src/
├── pages/
│   ├── DashboardPage.tsx
│   ├── MotorPage.tsx
│   ├── CameraPage.tsx
│   ├── BendingPage.tsx
│   ├── SimulationPage.tsx
│   ├── ConnectionPage.tsx
│   └── SettingsPage.tsx
├── api/        (API 클라이언트 래퍼)
├── components/ (재사용 컴포넌트)
└── App.tsx     (라우팅)
```

신규 페이지 추가 절차:
1. `pages/NewPage.tsx` 작성
2. `App.tsx` 라우트 추가
3. 사이드바 링크 추가 (`components/Sidebar.tsx` 또는 해당 파일)
4. API 호출은 `api/` 디렉토리의 기존 래퍼를 사용 (`apiFetch` helper)

### 4.4 빌드 → 보드 배포
```bash
# 로컬에서 빌드
cd src/app/frontend
npm run build
# → dist/ 생성

# 보드로 전송
rsync -av --delete dist/ root@192.168.4.1:/opt/ortho-bender/frontend-dist/

# 또는 scp
scp -r dist/* root@192.168.4.1:/opt/ortho-bender/frontend-dist/
```
배포 후 새로고침만 하면 반영됩니다. 백엔드 재시작 불필요 (StaticFiles는 파일시스템을 매 요청마다 참조).

---

## 5. 자주 발생하는 문제

### 5.1 "WebSocket connection failed" 콘솔 경고
- **증상**: 브라우저 콘솔에 `WebSocket is closed before the connection is established`
- **원인**: Vite dev server에서 `/ws/*` 프록시가 아직 연결되기 전 첫 렌더
- **해결**: 무해한 경고. 실제 동작에는 영향 없음. 거슬리면 `vite.config.ts` 의 `hmr.clientPort` 설정 확인.

### 5.2 Scan 버튼이 계속 "Scanning..." 상태
- **원인**: WiFi 스캔은 7~8초 소요됩니다. STA+AP 동시 모드에서 Single Channel Concurrency 때문에 여러 번 재시도됩니다.
- **정상 동작**: 시간이 지나면 결과가 표시됨
- **지속되면**: `journalctl -u ortho-bender-sdk | grep wifi` 로 백엔드 로그 확인

### 5.3 카메라 프리뷰가 검은 화면
- **원인**: J6 포트 카메라가 미인식
- **확인**:
  ```bash
  ssh root@192.168.4.1
  lsusb | grep -i allied
  journalctl -u ortho-bender-sdk | grep -i camera
  ```
- **복구**: 카메라 USB 케이블 재접속 + `systemctl restart ortho-bender-sdk`

### 5.4 대시보드가 404 / 빈 페이지
- **원인**: `/opt/ortho-bender/frontend-dist/` 가 비었거나 백엔드가 찾지 못함
- **확인**:
  ```bash
  ls /opt/ortho-bender/frontend-dist/index.html
  systemctl status ortho-bender-sdk
  curl -I http://127.0.0.1:8000/
  ```
- **복구**: `dist/` 재배포 (섹션 4.4 참조) 또는 복구 USB로 eMMC 이미지 복원 (부록 B)

---

## 부록 A - 개발지원 명령어 치트시트

보드 SSH 접속 상태에서 자주 쓰는 명령:

```bash
# 백엔드 상태/재시작
systemctl status ortho-bender-sdk
systemctl restart ortho-bender-sdk

# 실시간 로그
journalctl -u ortho-bender-sdk -f

# AP 상태
systemctl status ortho-bender-ap
/sbin/iw dev uap0 info
/sbin/iw dev uap0 station dump       # 접속한 노트북 목록

# WiFi STA (선택적 인터넷 연결)
wpa_cli -i mlan0 status
wpa_cli -i mlan0 scan
wpa_cli -i mlan0 scan_results

# 네트워크 인터페이스
/sbin/ip -br addr
/sbin/ip route

# API 직접 호출 (localhost)
curl -s http://127.0.0.1:8000/api/system/status | python3 -m json.tool

# 프론트엔드 갱신 (dist 교체 후 즉시 반영)
ls -la /opt/ortho-bender/frontend-dist/

# M7 펌웨어 로드 상태 (remoteproc)
cat /sys/class/remoteproc/remoteproc0/state
cat /sys/class/remoteproc/remoteproc0/firmware

# CPU/온도
cat /sys/class/thermal/thermal_zone0/temp
```

---

## 부록 B - 복구 절차 (eMMC 초기화)

보드가 부팅 불가 상태거나 `/opt/ortho-bender/` 가 손상된 경우:

### B.1 필요 장비
- 복구 USB 메모리 (동봉)
- 호스트 PC (Linux/Windows, `uuu` 실행)
- USB-C 케이블 (보드 J9)

### B.2 절차
1. 보드 DIP 스위치를 **USB 다운로드 모드**로 변경 (SW1: 1010)
2. USB-C 케이블로 보드 J9 ↔ 호스트 PC 연결
3. 보드 전원 투입 → 호스트에서 `NXP SDP` 장치 인식 확인
4. 복구 USB 메모리를 호스트 PC에 삽입
5. 터미널 실행:
   ```bash
   cd /media/$USER/ORTHO-RECOVERY   # 또는 USB 메모리 마운트 경로
   sudo ./uuu -b emmc_all imx-boot ortho-bender-handover-YYYYMMDD.wic
   ```
6. flash 완료 후 보드 DIP 스위치를 **eMMC 부팅 모드**로 복원 (SW1: 0110)
7. 전원 재투입 → 정상 부팅 확인 (약 30초)

### B.3 복구 이미지 정보
| 항목 | 값 |
|------|------|
| 파일명 | `ortho-bender-handover-YYYYMMDD.wic` |
| 크기 | 약 2 GB |
| 내용 | U-Boot + Linux Kernel + rootfs + /opt/ortho-bender/ 배포본 + 설정 파일 전체 |
| 사용 툴 | [mfgtools uuu](https://github.com/NXPmicro/mfgtools) |

복구 후에는 `01_INITIAL_SETUP.md` 의 5번 체크리스트를 다시 수행하여 정상 상태임을 확인하세요.

---

## 부록 C - 문의 및 이슈 리포트

- 코드 이슈: 프로젝트 저장소 Issues
- 하드웨어 결함: 이관 담당자에게 직접 연락
- 알려진 이슈:
  - **J7 USB 포트 미사용**: 카메라는 J6만 사용 (J7 enumeration 이슈 남음)
  - **첫 WiFi Scan 지연**: SCC 모드로 7~8초 소요 (정상 동작)

업데이트/버그픽스는 Git 저장소 메인 브랜치를 통해 배포됩니다. 최신 소스 동기화 절차는 `../sdk/04_DEPLOYMENT.md` 를 참조하세요.
