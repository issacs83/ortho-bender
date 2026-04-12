# Ortho-Bender SDK 사용 가이드

Ortho-Bender 와이어 벤딩 머신의 **소프트웨어 인터페이스**는 오직 하나입니다 —
i.MX8MP A53 에서 구동되는 Python FastAPI 백엔드의 **REST API + WebSocket**.

하드웨어(TMC260C-PA 드라이버, Allied Vision 카메라, Cortex-M7 펌웨어)는
SDK 뒤에 완전히 추상화되어 있어, 앱 개발자는 모터 타이밍이나 GenICam 같은
저수준 세부를 몰라도 됩니다.

- Base URL: `http://<device-ip>:8000`
- 개발용 Mock: `OB_MOCK_MODE=true` 로 실행하면 하드웨어 없이 동일 API 제공
- OpenAPI 문서: `http://<device-ip>:8000/docs`
- WebSocket: `ws://<device-ip>:8000/ws/{motor,camera,system}`

---

## 1. Quick Start

### 1.1 백엔드 기동
```bash
# EVK / 실기기
OB_MOCK_MODE=false GENICAM_GENTL64_PATH=/opt/VimbaX_2026-1/cti \
  python3 -m uvicorn server.main:app --host 0.0.0.0 --port 8000

# 로컬 Mock (카메라/모터 없이 개발)
OB_MOCK_MODE=true \
  python3 -m uvicorn server.main:app --reload --port 8000
```

### 1.2 Health check
```bash
curl http://localhost:8000/health
# {"status":"ok"}

curl http://localhost:8000/api/system/status
```

### 1.3 응답 envelope
모든 REST 응답은 다음 형태입니다:
```json
{ "success": true, "data": { ... }, "error": null, "code": null }
```
실패 시 `success=false`, `error`, `code` 가 채워집니다. 예:
`BENDING_BUSY`, `CAM_INVALID_INPUT`, `MOTOR_FAULT`.

---

## 2. 개발자 Persona 별 진입점

| Persona | 주요 엔드포인트 | 예제 파일 |
|--------|----------------|-----------|
| **프론트엔드/대시보드** | `/api/system`, `/api/motor`, `/ws/motor`, `/ws/system` | `basic_bend.py` |
| **CAD/CAM** | `/api/cam/generate`, `/api/cam/execute`, `/api/bending/*` | `cam_from_curve.py` |
| **Vision / ML** | `/api/camera/*`, `/ws/camera` | `camera_stream.py` |

예제 소스: `src/app/sdk-examples/python/`, cURL 예제: `src/app/sdk-examples/curl/`

---

## 3. REST API 레퍼런스

### 3.1 System — `/api/system`
| Method | Path | 설명 |
|--------|------|------|
| GET | `/status` | 전체 상태 (IPC, 카메라, 알람, uptime, CPU 온도) |
| GET | `/version` | SDK / M7 펌웨어 버전 |
| POST | `/reboot` | 시스템 재부팅 (`{"confirm": true}` 필수) |

### 3.2 Motor — `/api/motor`
| Method | Path | Body | 설명 |
|--------|------|------|------|
| GET | `/status` | — | 모든 축 position/velocity/DRV_STATUS |
| POST | `/move` | `{axis, distance, speed}` | 절대 이동 (mm 또는 °) |
| POST | `/jog` | `{axis, direction(±1), speed, distance?}` | 조그 모드 |
| POST | `/home` | `{axis_mask}` (0=all) | StallGuard2 홈잉 |
| POST | `/stop` | — | 즉시 감속 정지 |
| POST | `/reset` | `{axis_mask}` | 드라이버 폴트 리셋 |

**축 매핑** (Phase 1 기본값 `axis_mask=0x03`):
- `0` FEED — 와이어 피딩 (mm)
- `1` BEND — 벤딩 다이 (°)
- `2` ROTATE — 와이어 회전 (°, Phase 2)
- `3` LIFT — 승강 (Phase 2)

### 3.3 Camera — `/api/camera`
| Method | Path | 설명 |
|--------|------|------|
| GET | `/status` | 연결 여부, 해상도, 현재 exposure/gain, backend |
| POST | `/capture` | `{quality?}` → 단일 JPEG (base64) |
| POST | `/settings` | exposure_us / gain_db / format (mono8/mono12/rgb8) |

Backend 는 `vimba_x` (실카메라) 또는 `mock` (합성 프레임) 중 하나를 반환합니다.

### 3.4 Bending — `/api/bending`
| Method | Path | Body | 설명 |
|--------|------|------|------|
| POST | `/execute` | `{steps[], material, wire_diameter_mm}` | B-code 시퀀스 디스패치 (즉시 반환) |
| GET | `/status` | — | `running`, `current_step`, `progress_pct` 실시간 진행률 |
| POST | `/stop` | — | 시퀀스 중단 + 감속 |

스프링백 보상은 material 에 따라 자동 적용됩니다 (SS_304=×1.10,
NITI=×1.35, BETA_TI=×1.15, CU_NITI=×1.30). theta 는 180° 로 클램프됩니다.

### 3.5 CAM — `/api/cam`
| Method | Path | Body | 설명 |
|--------|------|------|------|
| POST | `/generate` | `{points[], material, wire_diameter_mm, min_segment_mm?, apply_springback?}` | 3D 폴리라인 → B-code 프리뷰 (모션 없음) |
| POST | `/execute` | 상동 | B-code 생성 + 모터 디스패치 원스텝 |

`generate` 는 프론트엔드의 실시간 프리뷰용으로 반복 호출해도 안전합니다.
출력 스텝은 입력 정점 N개에 대해 N-2 개 벤드 + 1 개 tail feed 입니다.

---

## 4. WebSocket 엔드포인트

| Path | 주기 | Payload |
|------|------|---------|
| `/ws/motor` | 10 Hz | `{type, state, axes[], timestamp_us}` |
| `/ws/camera` | camera FPS (최대) | `{type, frame_b64, width, height, timestamp_us}` |
| `/ws/system` | 이벤트 기반 | `{type, severity?, alarm_code?, message, timestamp_us}` |

모두 JSON 텍스트 프레임입니다. `/ws/camera` 는 메시지가 커서 클라이언트
`max_size ≥ 4 MB` 로 설정하세요.

---

## 5. 프론트엔드 개발자용

React / Vue 에서 바로 쓰는 패턴:

```ts
// 상태 구독
const ws = new WebSocket("ws://192.168.77.2:8000/ws/motor");
ws.onmessage = (e) => {
  const f = JSON.parse(e.data);
  if (f.type === "motor_status") setState(f);
};

// 커맨드
await fetch("/api/motor/home", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ axis_mask: 0 }),
});
```

개발 중에는 Vite dev server proxy 로 CORS 없이 붙일 수 있습니다
(`src/app/frontend/vite.config.ts` 참고).

---

## 6. CAD/CAM 개발자용

치료 계획(3D 와이어 센터라인) 을 받아 머신을 구동하는 최소 코드:

```python
import httpx, time

points = [...]  # list of {"x", "y", "z"} in mm
client = httpx.Client(base_url="http://192.168.77.2:8000")

# 1) 프리뷰 (CAD 뷰어 오버레이용)
preview = client.post("/api/cam/generate", json={
    "points": points, "material": 0, "wire_diameter_mm": 0.457,
}).json()["data"]

# 2) 사용자 확인 후 실행
client.post("/api/cam/execute", json={
    "points": points, "material": 0, "wire_diameter_mm": 0.457,
})

# 3) 진행률 폴링
while True:
    st = client.get("/api/bending/status").json()["data"]
    if not st["running"]:
        break
    time.sleep(0.2)
```

이미 B-code 를 외부 툴에서 생성한 경우 `/api/cam` 을 건너뛰고
`/api/bending/execute` 로 `{L_mm, beta_deg, theta_deg}` 배열을 직접
보내면 됩니다 (최대 128 step).

**Material 코드**: `0=SS_304`, `1=NITI`, `2=BETA_TI`, `3=CU_NITI`.

---

## 7. Vision / ML 개발자용

```python
# One-shot 캡처 (검사 트리거용)
import httpx, base64
r = httpx.post("http://192.168.77.2:8000/api/camera/capture",
               json={"quality": 90}).json()
jpeg = base64.b64decode(r["data"]["frame_b64"])
open("frame.jpg", "wb").write(jpeg)
```

```python
# 라이브 스트림 (ML 추론 파이프라인용)
import asyncio, base64, json, websockets

async def run():
    async with websockets.connect(
        "ws://192.168.77.2:8000/ws/camera",
        max_size=8 * 1024 * 1024,
    ) as ws:
        while True:
            msg = json.loads(await ws.recv())
            if msg["type"] != "camera_frame":
                continue
            jpeg = base64.b64decode(msg["frame_b64"])
            # decode with OpenCV / PIL, run inference, ...

asyncio.run(run())
```

Exposure / gain 조정:
```bash
curl -X POST http://192.168.77.2:8000/api/camera/settings \
  -H 'Content-Type: application/json' \
  -d '{"exposure_us": 5000, "gain_db": 6.0}'
```

Raw 이미지(mono12) 가 필요하면 `/api/camera/settings` 로 format 을 바꾸되,
WebSocket 은 여전히 JPEG 인코딩되어 전달됩니다. Raw 픽셀 파이프라인은
현재 GStreamer appsink → OpenCV 로만 제공됩니다 (추후 바이너리 WS 추가 예정).

---

## 8. 에러 처리 패턴

| code | 언제 | 조치 |
|------|------|------|
| `BENDING_BUSY` | 이전 시퀀스가 아직 돌고 있음 | `/api/bending/status` 로 확인 또는 `/stop` 후 재시도 |
| `CAM_INVALID_INPUT` | 정점 2개 미만 또는 범위 초과 | 입력 폴리라인 검증 |
| `MOTOR_FAULT` | TMC DRV_STATUS 에 overtemp/short | `/api/motor/reset` 후 원인 해소 |
| `IPC_TIMEOUT` | M7 펌웨어 무응답 | 시스템 로그 확인, 필요 시 reboot |
| `CAMERA_DISCONNECTED` | USB3 링크 단절 | 물리적 커넥터 / 전원 확인 |

에러는 HTTP 200 + `success:false` 로 오는 것이 기본입니다 (envelope 패턴).
5xx 는 진짜 서버 크래시일 때만 발생합니다.

---

## 9. Mock 모드

`OB_MOCK_MODE=true` 설정 시:
- IPC: 내장 `_simulate_bcode` 가 스텝당 약 0.3s 로 position/velocity 를
  실시간 갱신 — 프론트엔드 진행률 UI 를 하드웨어 없이 검증할 수 있습니다.
- Camera: 합성 프레임(그라디언트 + 타임스탬프) 생성, 실제 카메라 없이
  `/ws/camera` 동작 확인 가능.
- System status: `ipc_connected=false`, `m7_heartbeat_ok=false` 로 리포트.

Mock 은 실 API 와 동일한 envelope / 필드를 반환하므로 프로덕션 코드 변경
없이 그대로 붙입니다.

---

## 10. 관련 파일

| 경로 | 역할 |
|------|------|
| `src/app/server/main.py` | FastAPI 엔트리포인트, lifespan, 라우터 바인딩 |
| `src/app/server/routers/` | REST 엔드포인트 (motor, camera, bending, cam, system, wifi) |
| `src/app/server/services/ipc_client.py` | RPMsg + mock 시뮬레이션 |
| `src/app/server/services/camera_service.py` | VmbPy / mock 카메라 |
| `src/app/server/services/cam_service.py` | 3D 커브 → B-code 알고리즘 |
| `src/app/server/models/schemas.py` | Pydantic v2 요청/응답 스키마 |
| `src/app/sdk-examples/python/` | 예제 스크립트 |

상세 IPC 프로토콜은 `src/shared/ipc_protocol.h`, 아키텍처 전반은
[`docs/ARCHITECTURE.md`](ARCHITECTURE.md) 를 참고하세요.
