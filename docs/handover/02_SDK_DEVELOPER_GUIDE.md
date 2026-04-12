# 02 - SDK 개발자 가이드

**대상**: 이관 받은 개발자 (응용/백엔드/펌웨어 연동 개발자)
**전제**: `01_INITIAL_SETUP.md` 완료, 대시보드 접속 성공

이 문서는 SDK의 **핵심 사용 패턴**과 **API 요약**을 제공합니다. 전체 엔드포인트 명세는 `../sdk/02_API_REFERENCE.md`에 있습니다.

---

## 1. 아키텍처 한눈에 보기

```
┌────────────────────────────────────────────────────────┐
│                 i.MX8MP 보드 (Linux)                   │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │  ortho-bender-sdk.service                        │  │
│  │  (Python FastAPI, uvicorn, port 8000)            │  │
│  │                                                  │  │
│  │  ├─ REST  /api/system/*   /api/motor/*           │  │
│  │  │        /api/camera/*   /api/bending/*         │  │
│  │  │        /api/wifi/*     /api/simulation/*      │  │
│  │  │                                               │  │
│  │  └─ WS    /ws/motor   /ws/camera                 │  │
│  │           /ws/system  /ws/bending                │  │
│  └──────────────────┬───────────────────────────────┘  │
│                     │                                  │
│          ┌──────────┴──────────┐                       │
│          ▼                     ▼                       │
│    Hardware HAL           Mock Layer                   │
│    - RPMsg (M7)           - 가상 모터/카메라           │
│    - GStreamer (camera)   - 가상 센서                  │
│    - wpa_cli (WiFi)       - CI/개발용                  │
│                                                        │
└────────────────────────────────────────────────────────┘
          ▲
          │ HTTP/WS
          │
     ┌────┴────────┐
     │ 개발자 앱   │ (Python / JS / C++ / curl / React)
     └─────────────┘
```

### 핵심 원칙
- **개발자는 하드웨어를 직접 만지지 않습니다.** 모든 상호작용은 HTTP + WebSocket 경유.
- **Mock 모드**로 하드웨어 없이 개발 가능 (`OB_MOCK_MODE=1`). 기본값은 실장비.
- **API envelope** 형식 일관성: `{ success, data, error, code }`.

---

## 2. 시작하기 - 3분 만에 첫 호출

### 2.1 cURL
```bash
curl -s http://192.168.4.1:8000/api/system/status | jq
```
응답 예:
```json
{
  "success": true,
  "data": {
    "motion_state": 0,
    "camera_connected": true,
    "ipc_connected": true,
    "m7_heartbeat_ok": true,
    "active_alarms": 0,
    "uptime_s": 127.4,
    "cpu_temp_c": 42.0,
    "sdk_version": "0.1.0"
  }
}
```

### 2.2 Python
```python
import requests

BASE = "http://192.168.4.1:8000"

def status():
    r = requests.get(f"{BASE}/api/system/status", timeout=5)
    r.raise_for_status()
    return r.json()["data"]

print(status())
```

### 2.3 JavaScript (Node.js / 브라우저 동일)
```javascript
const BASE = "http://192.168.4.1:8000";

async function status() {
  const r = await fetch(`${BASE}/api/system/status`);
  const j = await r.json();
  if (!j.success) throw new Error(j.error);
  return j.data;
}

status().then(console.log);
```

### 2.4 Swagger UI (탐색용)
브라우저에서 `http://192.168.4.1:8000/docs` 를 열면 FastAPI가 자동 생성한 인터랙티브 API 문서가 표시됩니다. 각 엔드포인트를 직접 실행해 볼 수 있어 API 학습에 가장 빠른 경로입니다.

---

## 3. 주요 API 카테고리 요약

| Prefix | 목적 | 주요 엔드포인트 |
|--------|------|----------------|
| `/api/system` | 시스템 헬스, 버전, 재부팅 | `GET /status`, `GET /version`, `POST /reboot` |
| `/api/motor` | 4축 모터 직접 제어 (개발자 모드) | `POST /enable`, `POST /jog`, `POST /home`, `POST /stop` |
| `/api/camera` | Vimba X USB3 Vision 카메라 | `POST /connect`, `POST /grab`, `GET /stream`, `GET /frame` |
| `/api/bending` | B-code 시퀀스 업로드/실행 | `POST /upload`, `POST /start`, `POST /pause`, `GET /progress` |
| `/api/simulation` | 3D 곡선 → B-code 변환, 스프링백 미리보기 | `POST /convert`, `POST /preview` |
| `/api/wifi` | AP 스캔/연결 (STA) | `GET /scan`, `GET /status`, `POST /connect`, `POST /disconnect` |

전체 엔드포인트 상세(request/response 스키마, 에러 코드, 예시 호출)는 **`../sdk/02_API_REFERENCE.md`**를 참조하세요.

---

## 4. WebSocket 스트리밍

실시간 상태 스트림이 필요한 UI/로거용.

| 채널 | 메시지 타입 | 주기 | 용도 |
|------|------------|------|------|
| `/ws/system` | system_status | 1 Hz | 헬스, 알람 |
| `/ws/motor` | motor_state | 20 Hz | 4축 위치/속도/상태 |
| `/ws/camera` | camera_frame (base64 JPEG) | 5~30 FPS | 실시간 프리뷰 |
| `/ws/bending` | bending_progress | 이벤트 기반 | 시퀀스 진행률, 스텝 완료 |

### Python 예시 (`websockets` 패키지)
```python
import asyncio, json, websockets

async def main():
    uri = "ws://192.168.4.1:8000/ws/motor"
    async with websockets.connect(uri) as ws:
        async for msg in ws:
            data = json.loads(msg)
            print(data["axes"][0]["position_mm"])

asyncio.run(main())
```

### JavaScript 예시
```javascript
const ws = new WebSocket("ws://192.168.4.1:8000/ws/motor");
ws.onmessage = (e) => {
  const data = JSON.parse(e.data);
  console.log(data.axes.map(a => a.position_mm));
};
```

---

## 5. 개발 워크플로우 패턴

### 5.1 Mock 모드 (하드웨어 없이 개발)
본인 노트북/서버에서 백엔드를 실행해 볼 수 있습니다:
```bash
git clone <repo>
cd ortho-bender/src/app/server
export OB_MOCK_MODE=1
pip install -r requirements.txt
uvicorn server.main:app --host 0.0.0.0 --port 8000
```
- 모든 하드웨어 호출이 가상 구현으로 대체됩니다.
- 카메라는 합성 프레임, 모터는 시뮬레이션 포지션, M7 IPC는 가상 응답.
- 대시보드도 동일하게 동작.
- 상세: `../sdk/03_MOCK_MODE.md`

### 5.2 원격 디버그 (보드 실장비)
보드에서 바로 Python 코드를 수정해 보고 싶다면:
```bash
ssh root@192.168.4.1
cd /opt/ortho-bender/server
vi routers/motor.py   # or copy file in from your host
systemctl restart ortho-bender-sdk
journalctl -u ortho-bender-sdk -f
```

### 5.3 앱에서 SDK 호출 (권장 패턴)
자체 애플리케이션 개발 시:
1. **HTTP 클라이언트 래퍼**를 하나 만들어 envelope unwrap을 일원화 (`success:false` → 예외)
2. **WebSocket 구독자**를 하나 만들어 재접속/백오프 처리
3. **Mock 모드 환경변수**를 앱에도 전달해 개발/CI 환경에서 사용

Python/JS 샘플 래퍼는 `../../examples/`에 있습니다:
- `examples/python_sdk_client.py`
- `examples/node_sdk_client.js`
- `examples/curl_sdk_examples.sh`
- `examples/opencv_frame_pipeline.py`

---

## 6. 에러 핸들링 규약

### 6.1 에러 envelope
```json
{
  "success": false,
  "data": null,
  "error": "AXIS_NOT_READY",
  "code": 4001
}
```

### 6.2 코드 범위
| 범위 | 분류 |
|------|------|
| 1xxx | 시스템/부트 에러 |
| 2xxx | 카메라 에러 |
| 3xxx | IPC/M7 에러 |
| 4xxx | 모터/운동 에러 |
| 5xxx | B-code/시뮬레이션 에러 |
| 6xxx | WiFi/네트워크 에러 |
| 9xxx | 내부 버그 (신고 대상) |

### 6.3 HTTP 상태
- **200**: envelope.success로 판정 (정상/업무 오류 모두)
- **422**: 요청 스키마 불일치 (Pydantic validation)
- **500**: 서버 크래시 (`journalctl -u ortho-bender-sdk` 확인)

---

## 7. 안전 규칙 (HARD LIMIT)

본 장비는 **FDA Class II 의료기기 분류**를 목표로 개발 중이며, 운동 명령은 다음 규칙을 준수합니다:

- **E-Stop**: `POST /api/motor/stop` 호출 시 M7 측 GPIO ISR이 1 ms 이내 모든 축 정지. 하드웨어 DRV_ENN 라인도 동시에 차단됩니다.
- **Safety limit**: 모든 이동 명령은 백엔드에서 ROM(Range of Motion) 체크 후 M7에 전달됩니다. 범위 초과 시 `4xxx` 에러 반환.
- **Watchdog**: M7 펌웨어는 200 ms watchdog 보호. A53와의 IPC 타임아웃 발생 시 자동 안전 정지.

개발 중 임의로 안전 로직을 우회하지 마세요. 자세한 내용은 `../architecture/01_ARCHITECTURE.md` 및 `../architecture/03_BOOTFLOW.md` 를 참조하세요.

---

## 8. 변경 및 기여

- 소스 위치: `src/app/server/` (백엔드), `src/app/frontend/` (React 대시보드)
- 코딩 규칙: `.claude/rules/coding-rules.md`
- 빌드 / 배포: `../sdk/04_DEPLOYMENT.md`
- 이슈/버그: 프로젝트 이슈 트래커 (이관 시 전달)

---

## 9. 참고 문서 맵

| 필요한 정보 | 문서 |
|------------|------|
| 엔드포인트 상세/스키마 | `../sdk/02_API_REFERENCE.md` |
| 아키텍처 / 기술 스택 | `../architecture/01_ARCHITECTURE.md` |
| HW 추상화 계층 | `../architecture/02_HARDWARE_ABSTRACTION.md` |
| Mock 모드 사용법 | `../sdk/03_MOCK_MODE.md` |
| 배포/빌드 스크립트 | `../sdk/04_DEPLOYMENT.md` |
| 문제 해결 | `../sdk/05_TROUBLESHOOTING.md` |
| B-code 스펙 | `../algorithm/02_BCODE_SPEC.md` |
| CAD/CAM 워크플로우 | `../algorithm/01_CAD_CAM_GUIDE.md` |
| 와이어 재료 (NiTi/SS/Beta-Ti) | `../algorithm/03_WIRE_MATERIALS.md` |
