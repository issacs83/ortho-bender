# 하드웨어 추상화 원칙

> **한 문장 요약**: 카메라 인터페이스가 USB3 든 MIPI CSI 든, 모터가 TMC260C-PA 든
> 다른 스테퍼/서보 드라이버든, **SDK 를 쓰는 소프트웨어 개발자의 코드는 단 한
> 줄도 바뀌지 않습니다.**

이 문서는 Ortho-Bender SDK 의 **가장 중요한 설계 원칙**인 "하드웨어 교체 투명성"을
정의합니다. 이 원칙이 왜 필요한지, 어떻게 구현되어 있는지, 그리고 개발자가
무엇을 신뢰하고 무엇을 신뢰하면 안 되는지 명확히 합니다.

---

## 1. 왜 추상화가 필요한가

의료 기기의 개발 주기는 매우 깁니다 (3~5년). 그 기간 동안 거의 반드시:

- 카메라 벤더가 단종하거나, 더 좋은 센서가 나오거나, 인터페이스가 바뀝니다
  (USB3 Vision → MIPI CSI → GigE Vision → GMSL 등)
- 모터 드라이버 IC 가 EOL 되거나, 성능 요구사항이 바뀌어 하이브리드
  스테퍼+서보로 전환되거나, FOC 드라이버로 교체됩니다
- FPGA 게이트웨이가 생기거나, 센서가 추가되거나, 안전 MCU 가 분리됩니다

만약 이런 변경이 **앱/프론트엔드/CAM 개발자의 코드에 전파된다면**, 프로젝트는
하드웨어 변경 때마다 전체 소프트웨어를 재작성해야 합니다. 이것은 FDA / IEC 62304
환경에서 치명적입니다 (재검증 부담, V&V 재수행, 인증 재취득).

따라서 **하드웨어와 애플리케이션 사이에 고정된 경계면(API)**을 두고, 그 경계면
너머에서는 모든 것이 바뀔 수 있도록 설계했습니다.

---

## 2. 경계면의 위치

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│    외부 SW 개발자의 코드 (변경 없음)                           │
│    ┌────────────────────────────────────────────────────┐    │
│    │  React / Vue 프론트엔드                             │    │
│    │  Python CAD/CAM 툴                                  │    │
│    │  Vision/ML 파이프라인 (OpenCV, PyTorch)             │    │
│    │  운영/DevOps 스크립트                               │    │
│    └────────────────────────────────────────────────────┘    │
│                            │                                 │
│      ════════════ 고정 경계면 ════════════                    │
│                            │                                 │
│      REST API      +      WebSocket                         │
│      /api/motor           /ws/motor                          │
│      /api/camera          /ws/camera                         │
│      /api/bending         /ws/system                         │
│      /api/cam                                                │
│      /api/system                                             │
│                            │                                 │
│      ════════════ 이 아래는 자유 ════════════                 │
│                            │                                 │
│    ┌────────────────────────────────────────────────────┐    │
│    │  FastAPI 라우터 레이어 (envelope / 검증)           │    │
│    ├────────────────────────────────────────────────────┤    │
│    │  서비스 어댑터 레이어 (정규화된 내부 API)           │    │
│    │  MotorAdapter · CameraAdapter · IpcClient           │    │
│    ├────────────────────────────────────────────────────┤    │
│    │  하드웨어 구현 (언제든 교체 가능)                   │    │
│    │  ┌──────────┐ ┌──────────┐ ┌──────────┐            │    │
│    │  │ VmbPy    │ │ GStreamer│ │ v4l2     │   카메라   │    │
│    │  │ (U3V)    │ │ (MIPI)   │ │ (legacy) │            │    │
│    │  └──────────┘ └──────────┘ └──────────┘            │    │
│    │                                                    │    │
│    │  ┌──────────┐ ┌──────────┐ ┌──────────┐            │    │
│    │  │TMC260C-PA│ │TMC5160   │ │ Servo+   │   모터     │    │
│    │  │STEP/DIR  │ │StealthC. │ │ EtherCAT │            │    │
│    │  └──────────┘ └──────────┘ └──────────┘            │    │
│    └────────────────────────────────────────────────────┘    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**고정 경계면 위쪽**: API 계약. 변경되면 semver major bump (v1.x → v2.0).
**고정 경계면 아래쪽**: 구현 자유. 개발팀이 언제든 교체 가능, SDK 버전에 영향 없음.

---

## 3. 카메라 교체 시나리오 — USB3 Vision ↔ MIPI CSI

### 3.1 현재 구현 (USB3 Vision)

```
Client           FastAPI          services/camera    VmbPy SDK      Camera (USB3)
  │                 │                    │                │              │
  │ GET /status     │                    │                │              │
  ├────────────────>│                    │                │              │
  │                 │ get_status()       │                │              │
  │                 ├───────────────────>│                │              │
  │                 │                    │ Vmb.open()     │              │
  │                 │                    ├───────────────>│              │
  │                 │                    │                │ USB3 enum    │
  │                 │                    │                ├─────────────>│
  │                 │                    │                │<─────────────┤
  │                 │                    │<───────────────┤ Camera obj   │
  │                 │<───────────────────┤                │              │
  │<────────────────┤                    │                │              │
  │  {connected:true, width:1456,        │                │              │
  │   height:1088, format:"mono8",       │                │              │
  │   backend:"vimba_x"}                 │                │              │
```

### 3.2 가상: MIPI CSI 로 교체

하드웨어 팀이 i.MX8MP ISP 에 직결된 MIPI CSI 센서 (예: Sony IMX477) 로 교체.
변경되는 것:

| 계층 | 변경 | 담당 |
|------|------|------|
| 하드웨어 | USB 케이블 제거, MIPI FFC 연결 | 기구팀 |
| DTS | `csi_mipi1` 노드 활성화, IMX477 subdev 바인딩 | BSP 팀 |
| 커널 | `imx8mq-csi`, `imx477` 드라이버 컴파일 | BSP 팀 |
| 서비스 어댑터 | `V4l2CameraAdapter` 클래스 신규 구현 | 플랫폼 팀 |
| 서비스 팩토리 | `create_camera_adapter()` 가 mipi 감지 시 V4l2 반환 | 플랫폼 팀 |

**변경되지 않는 것**:

```
Client           FastAPI          services/camera    V4l2 adapter   Camera (MIPI)
  │                 │                    │                │              │
  │ GET /status     │                    │                │              │  ← 클라이언트 코드 그대로
  ├────────────────>│                    │                │              │
  │                 │ get_status()       │                │              │  ← 라우터 코드 그대로
  │                 ├───────────────────>│                │              │
  │                 │                    │ v4l2.open()    │              │  ← 서비스 인터페이스 그대로
  │                 │                    ├───────────────>│              │
  │                 │                    │                │ VIDIOC_QUERY │  ← 여기만 바뀜
  │                 │                    │                ├─────────────>│
  │                 │                    │                │<─────────────┤
  │                 │                    │<───────────────┤ v4l2 format  │
  │                 │<───────────────────┤                │              │
  │<────────────────┤                    │                │              │
  │  {connected:true, width:1456,        │                │              │
  │   height:1088, format:"mono8",       │                │              │
  │   backend:"v4l2"}              ◀──────────────────── 여기만 바뀜       │
```

**외부 개발자가 보는 유일한 차이**: `backend` 필드 값 (`vimba_x` → `v4l2`).
만약 이 값을 클라이언트 코드에서 조건 분기에 사용하지 않았다면 — **코드 변경 0**.

### 3.3 OpenCV 사용자 관점

OpenCV 로 라이브 스트림을 처리하는 Vision/ML 개발자 코드:

```python
import cv2, base64, json, asyncio, websockets, numpy as np

async def process_stream(ws_url: str):
    async with websockets.connect(ws_url, max_size=8 * 1024 * 1024) as ws:
        while True:
            msg = json.loads(await ws.recv())
            if msg["type"] != "camera_frame":
                continue
            jpeg = base64.b64decode(msg["frame_b64"])
            img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_UNCHANGED)
            # ... 분석 로직 ...
            cv2.imshow("live", img)
            if cv2.waitKey(1) == 27: break

asyncio.run(process_stream("ws://192.168.77.2:8000/ws/camera"))
```

**이 코드는 USB3 Vision 구현에서도, MIPI CSI 구현에서도, 심지어 Mock 합성
프레임에서도 전부 정상 동작합니다.** 바이트 수준에서 보면 그저 JPEG 를 받는
WebSocket 일 뿐이니까요.

---

## 4. 모터 드라이버 교체 시나리오 — TMC260C-PA ↔ 하이브리드 서보

### 4.1 현재 구현 (TMC260C-PA 스테퍼)

- STEP/DIR 펄스는 M7 GPT 타이머가 생성
- SPI 로 드라이버 레지스터 설정 (IRUN, SGT 등)
- StallGuard2 로 센서리스 홈잉
- 포지션은 M7 이 펄스 카운터로 추적 (오픈 루프)

API 응답:
```json
{
  "axes": [
    { "axis": 0, "position": 12.345, "velocity": 0.0,
      "drv_status": 0, "sg_result": 0, "cs_actual": 16 }
  ]
}
```

### 4.2 가상: 서보+엔코더 하이브리드로 업그레이드

| 계층 | 변경 |
|------|------|
| 하드웨어 | 스테퍼 → 서보 모터, TMC → 서보 드라이버 (예: Kollmorgen AKD), 엔코더 추가 |
| 인터페이스 | STEP/DIR 제거, EtherCAT 또는 CANopen 으로 변경 |
| M7 펌웨어 | motion_task 가 EtherCAT master 역할 (혹은 별도 게이트웨이 MCU 로 위임) |
| IPC 메시지 | `MSG_MOTION_EXECUTE_BCODE` 구조체는 그대로 (L/β/θ), M7 내부에서 EtherCAT PDO 로 변환 |
| A53 서비스 | 거의 변경 없음 (IPC 어댑터만 신규 타입코드 인식) |

**변경되지 않는 것**:

| 유지되는 것 | 이유 |
|-------------|------|
| `/api/motor/status` 스키마 | `axes[]` 는 여전히 position/velocity 반환 |
| `/api/motor/move` body | axis/distance/speed 개념은 서보도 동일 |
| `/api/bending/execute` | B-code `(L, β, θ)` 는 물리 원리 (피드-회전-벤드) |
| `/api/cam/*` | CAM 알고리즘은 물리 형상 기반, 드라이버 무관 |
| `/ws/motor` 스트림 | 10 Hz JSON 포맷 유지 |

**API 응답은 거의 동일**, 단지 필드의 **의미**만 변합니다:
```json
{
  "axes": [
    { "axis": 0, "position": 12.345, "velocity": 0.0,
      "drv_status": 0,  // 이제 서보 드라이버 상태 (호환 디코딩)
      "sg_result": 0,   // 의미 없음 (0 고정) — 엔코더 에러는 새 필드로
      "cs_actual": 16   // 이제 서보 전류 지령 (mA)
    }
  ]
}
```

**하위 호환성을 위한 규칙**: 스키마 필드는 **절대 제거하지 않고**, 의미가
없어진 필드는 0 또는 null 로 채우며, 신규 필드를 추가합니다. 이것이 v1.x
호환을 유지하는 방법입니다.

### 4.3 CAD/CAM 사용자 관점

CAD 툴에서 3D 폴리라인을 보내는 개발자:

```python
client.post("/api/cam/execute", json={
    "points": tooth_wire_path_3d,
    "material": 1,   # NiTi
    "wire_diameter_mm": 0.406,
})
```

**TMC 스테퍼에서든, EtherCAT 서보에서든, Mock 에서든 — 동일 코드, 동일 결과.**
추상화의 가치는 여기서 드러납니다.

---

## 5. 왜 B-code 는 벤더 중립인가

B-code 의 `(L_mm, beta_deg, theta_deg)` 3-tuple 은 **물리 동작 자체**를 기술합니다:

- `L_mm`: 와이어 몇 mm 를 밀었는지 (기하학적 길이)
- `beta_deg`: 와이어 축 회전 각도 (기하학적 회전)
- `theta_deg`: 벤드 각도 (기하학적 굽힘)

이 양들은 **어떤 드라이버로 구현하든 존재하는 양**입니다:
- 스테퍼 → 마이크로스텝 카운트로 변환
- 서보 → 목표 위치(rad)로 변환
- 리니어 모터 → 직접 거리 명령
- 향후 로봇 암 → IK 계산 후 조인트 각도

각 구현은 자기 방식으로 변환하지만, **외부 개발자에게 노출되는 포맷은
변하지 않습니다.** 이것이 B-code 를 "low-level motion format" 이 아닌
"hardware-independent geometric format" 으로 설계한 이유입니다.

---

## 6. 추상화의 한계 — 무엇이 바뀌는가

정직하게 말해서, 100% 투명한 것은 아닙니다. 하드웨어 변경 시 **일부 개발자
영역**은 영향을 받습니다:

| 변경 | 영향받는 개발자 | 조치 |
|------|-----------------|------|
| 카메라 해상도 변경 (1456×1088 → 2048×1536) | Vision/ML | 레터박스 / 크롭 조정 |
| 카메라 bit depth 변경 (mono8 → mono12) | Vision/ML | `format` 요청 변경 |
| FPS 상한 변경 (40 → 120 FPS) | Vision/ML | 더 높은 성능 기회 (선택) |
| 모터 최대 속도 변경 | CAD/CAM | `speed` 파라미터 상한 |
| 새 축 추가 (Phase 2 ROTATE/LIFT) | 프론트엔드 | UI 에서 새 축 표시 |
| 새 재질 지원 | CAD/CAM | `material` enum 값 추가 |

**모두 "능력 확장" 방향의 변경**이지 API 형태나 동작 방식의 변경은 아닙니다.
기존 코드는 계속 동작합니다 (추가 기능만 놓침).

### 6.1 Semver 약속

- **MAJOR (2.0)**: envelope 변경, 엔드포인트 제거, 필수 파라미터 추가
- **MINOR (1.1)**: 신규 엔드포인트, 신규 옵셔널 파라미터, 신규 material/format
- **PATCH (1.0.1)**: 버그 수정, 성능 개선, 문서 업데이트

**하드웨어 교체는 MINOR 이하에서 대부분 흡수됩니다.**

---

## 7. 어떻게 이것을 테스트하는가

개발자가 "정말 내 코드가 하드웨어 변경에 내성이 있나?" 를 검증하는 방법:

### 7.1 Mock 모드에서 개발

```bash
OB_MOCK_MODE=true python3 -m uvicorn server.main:app
```

Mock 어댑터는 **가짜 하드웨어**입니다. Mock 에서 동작한다면 이미 추상화
경계를 존중하고 있다는 뜻입니다 (실제 하드웨어에 의존하는 코드는 Mock 에서
깨집니다).

### 7.2 백엔드 식별 피하기

클라이언트 코드에서 **이런 식의 조건문을 쓰지 마세요**:
```python
# ❌ 이러면 하드웨어 교체에 취약해짐
if status["backend"] == "vimba_x":
    do_vimba_specific_thing()
```

대신:
```python
# ✅ 기능 탐지 기반
if "mono12" in status.get("supported_formats", []):
    request_high_bit_depth()
```

### 7.3 엔드포인트만 의존

- `/api/*` 와 `/ws/*` **만** 사용
- `/dev/rpmsg0`, VmbPy, GStreamer 를 직접 호출하지 않음
- 환경변수 `OB_*` 는 운영자 영역, 앱 코드에서 읽지 않음

---

## 8. 현재 구현의 어댑터 위치 (내부 참고)

외부 개발자가 알 필요는 없지만, 플랫폼 팀을 위한 참고:

| 하드웨어 | 어댑터 파일 | 추상화되는 인터페이스 |
|----------|-------------|----------------------|
| TMC260C-PA (via M7) | `services/ipc_client.py` | `execute_bcode()`, `get_status()` |
| Mock 모터 | 동일 파일, `_simulate_*` 메서드 | 동일 |
| Allied Vision U3V | `services/camera_service.py` | `open()`, `grab_frame()`, `set_exposure()` |
| Mock 카메라 | 동일 파일, 합성 프레임 경로 | 동일 |
| 향후 MIPI CSI | (예정) `services/v4l2_camera.py` | 동일 |
| 향후 EtherCAT 서보 | 변경 없음 (M7 내부에서 처리) | 동일 |

새 하드웨어를 추가할 때 플랫폼 팀은:
1. 어댑터 클래스 추가 (동일 인터페이스 구현)
2. 팩토리에서 감지 로직 추가
3. Mock 대비 통합 테스트 실행

외부 개발자에게는 **보이지 않습니다**.

---

## 9. 요약 체크리스트

개발자는 다음 사실만 기억하면 됩니다:

- [x] 카메라가 USB3, MIPI, GigE 어떤 것이든 `/api/camera` 는 동일
- [x] 모터가 스테퍼, 서보, 리니어 어떤 것이든 `/api/motor`, `/api/bending` 은 동일
- [x] B-code `(L, β, θ)` 는 벤더 중립 물리 포맷
- [x] Mock 모드로 모든 클라이언트 로직을 오프라인 검증 가능
- [x] 하드웨어 변경은 대부분 MINOR semver 이하로 흡수
- [x] 클라이언트 코드는 `backend` 필드 같은 구현 식별자에 조건 분기 금지
- [x] SDK 버전만 고정하면 **내 코드는 5년 뒤에도 동작**

---

## 10. 관련 문서

- [ARCHITECTURE.md](01_ARCHITECTURE.md) — 전체 시스템 구조 및 계층
- [SDK_GUIDE.md](../sdk/01_SDK_GUIDE.md) — 메인 사용 가이드
- [API_REFERENCE.md](../sdk/02_API_REFERENCE.md) — 엔드포인트 스키마
- [CAD_CAM_GUIDE.md](../algorithm/01_CAD_CAM_GUIDE.md) — CAD/CAM 개발자 전용 가이드
- [MOCK_MODE.md](../sdk/03_MOCK_MODE.md) — 하드웨어 없이 개발
