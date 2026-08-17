# CAD/CAM 연동 가이드

CAD/CAM 애플리케이션에서 Ortho-Bender 장비를 제어하기 위한 **엔드투엔드 가이드**입니다.
3D 와이어 곡선을 받아 → B-code로 변환 → 장비에서 실행 → 진행률 추적까지 다룹니다.

- 사전 필독: [06_AXIS_CONVENTIONS.md](06_AXIS_CONVENTIONS.md) (축 단위·부호·원점)
- 전체 엔드포인트: [02_API_REFERENCE.md](02_API_REFERENCE.md)
- 런타임 문서: `http://<device>:8000/docs` (Swagger) · `/redoc`

---

## 1. 통합 방식 두 가지

| 방식 | 언제 쓰나 | 엔드포인트 |
|---|---|---|
| **A. CAM 파이프라인** | CAD에서 만든 **3D 폴리라인**을 그대로 넘기고 싶을 때 | `/api/cam/generate` → `/api/cam/execute` |
| **B. B-code 직접** | 자체 CAM 엔진이 이미 있어 **명령열을 직접 만들 때** | `/api/bending/execute` |
| **C. 축 직접 제어** | 교정·티칭·정밀 위치 지정 | `/api/motor/move_to` 등 |

---

## 2. 방식 A — 3D 곡선에서 바로 굽히기

### 2.1 프리뷰 생성 (모션 없음)

```http
POST /api/cam/generate
{
  "points": [ {"x":0,"y":0,"z":0}, {"x":10,"y":0,"z":0}, {"x":18,"y":6,"z":0} ],
  "material": 1,
  "wire_diameter_mm": 0.457,
  "min_segment_mm": 1.0,
  "apply_springback": true
}
```

| 필드 | 설명 |
|---|---|
| `points` | 와이어 **중심선** 3D 점열 (mm), 2~512개, 순서대로 |
| `material` | `0=NiTi, 1=SS304, 2=Beta-Ti, 3=CuNiTi` |
| `wire_diameter_mm` | 0 초과 2.0 이하 (기본 0.457) |
| `min_segment_mm` | 이산화 최소 구간 길이 (기본 1.0) |
| `apply_springback` | 재질별 스프링백 과굽힘 보정 적용 (기본 true) |

**응답**
```json
{ "success": true, "data": {
  "steps": [ {"L_mm": 10.0, "beta_deg": 0.0, "theta_deg": 31.2}, ... ],
  "segment_count": 12, "total_length_mm": 84.6,
  "max_bend_deg": 47.3, "warnings": []
}}
```
모션이 전혀 없으므로 **UI 실시간 프리뷰용으로 반복 호출해도 안전**합니다.
`warnings` 에는 곡률 과다·세그먼트 과소 등 경고가 담깁니다 — 사용자에게 노출하세요.

### 2.2 실행

```http
POST /api/cam/execute      # 같은 body → 생성 + 즉시 실행
```
`generate` 와 동일한 입력을 받아 변환 후 바로 벤딩을 시작합니다(즉시 반환).

> 프리뷰에서 사용자가 확인한 **그 결과**를 실행하고 싶다면, `generate` 로 받은
> `steps` 를 `/api/bending/execute` 에 그대로 넘기는 방식(B)이 더 안전합니다.
> 입력이 같아도 파라미터가 바뀌면 결과가 달라질 수 있기 때문입니다.

---

## 3. 방식 B — B-code 직접 실행

```http
POST /api/bending/execute
{
  "steps": [
    {"L_mm": 12.0, "beta_deg": 0.0,  "theta_deg": 30.0},
    {"L_mm":  8.5, "beta_deg": 90.0, "theta_deg": -22.5}
  ],
  "material": 1,
  "wire_diameter_mm": 0.457
}
```

**B-code 한 스텝의 의미** — `Feed → Rotate → Bend` 순서로 수행됩니다.

| 필드 | 의미 | 범위 |
|---|---|---|
| `L_mm` | 다음 굽힘점까지 **와이어를 이송**할 길이 | 0.5 ~ 200 mm |
| `beta_deg` | 와이어를 **자체 축 둘레로 회전** (굽힘 평면 선택) | −360 ~ 360° |
| `theta_deg` | **굽힘 각도** (부호 = 굽힘 방향) | −180 ~ 180° |

> ⚠️ 현재 벤치는 **FEED·BEND·LIFT 3축**만 장착되어 있고 **ROTATE 축이 없습니다.**
> 따라서 `beta_deg` 는 실제 모션으로 이어지지 않습니다. 단일 평면 곡선(모든 굽힘이
> 같은 평면)으로 시작하시고, 3D 곡선은 ROTATE 축 장착 후 사용하세요.

### 진행률 추적

```http
GET /api/bending/status
→ { "running": true, "current_step": 3, "total_steps": 12,
    "progress_pct": 25.0, "material": 1, "wire_diameter_mm": 0.457 }
```
`POST /api/bending/stop` 으로 중단합니다.

---

## 4. 방식 C — 축 직접 제어 (교정·티칭)

```python
import requests
BASE = "http://192.168.77.2:8000"

def api(method, path, **kw):
    r = requests.request(method, BASE + path, timeout=120, **kw).json()
    if not r["success"]:
        raise RuntimeError(f'{r["code"]}: {r["error"]}')
    return r["data"]

# 1) 원점 확보 — 센서가 있는 축은 홈으로 기준을 잡는다
api("POST", "/api/motor/home", json={"axis_mask": 0})       # BEND + LIFT
while api("GET", "/api/motor/limits")["homing"]:
    time.sleep(0.3)

# 2) 절대 좌표 이동 (BEND=deg, LIFT=mm, LIFT의 +는 아래)
api("POST", "/api/motor/move_to", json={"axis": 1, "position": 45.0, "speed": 120})
api("POST", "/api/motor/move_to", json={"axis": 3, "position": 120.0, "speed": 20})

# 3) 도달 확인
for ax in api("GET", "/api/motor/status")["axes"]:
    print(ax["axis"], ax["position"])
```

`move_to` 는 가감속을 **지정 좌표 안에서 완결**하고, 긴 이동은 자동 분할합니다.
실측 오차는 BEND ≤ 0.24°, LIFT 0.00 mm 입니다.

---

## 5. 실시간 상태 구독 (WebSocket)

```javascript
const ws = new WebSocket("ws://192.168.77.2:8000/ws/motor");
ws.onmessage = (e) => {
  const s = JSON.parse(e.data);      // MotorStatus (약 100 ms 주기)
  // s.state: 0=IDLE 1=HOMING 2=RUNNING 3=JOGGING 4=STOPPING 5=FAULT 6=ESTOP
  // s.axes[i].position / .signals.limit (리밋 센서 상태)
};
```
| 스트림 | 내용 |
|---|---|
| `/ws/motor` | 축 위치·상태·신호 (진행률 UI용) |
| `/ws/camera` | 카메라 프레임 (base64 JPEG) |
| `/ws/system` | 시스템 이벤트/알람 |
| `/ws/motor/diag` | 드라이버 레지스터 진단 (StallGuard 등) |

---

## 6. 안전 인터록 — 외부 앱이 지켜야 할 것

1. **E-STOP 감시**: `state == 6` 이면 모든 모션 명령이 거부됩니다.
   해제는 `POST /api/motor/reset` (사용자 확인 후).
2. **작업 전 홈**: 전원이 꺼진 동안 축이 움직였을 수 있으므로, 정밀 작업 전
   `POST /api/motor/home` 으로 기준을 다시 잡으세요.
3. **한 번에 한 모션**: 새 모션 명령은 진행 중인 모션을 감속 취소하고 대체합니다
   (마지막 명령 우선). 시퀀스를 보내려면 **완료를 확인하고 다음 명령**을 보내세요.
4. **속도 하한 주의**: BEND는 아주 낮은 속도에서 공진으로 스텝이 유실될 수 있습니다.
   정밀 이동은 60 deg/s 이상 권장.

---

## 7. 에러 코드

| code | 의미 | 대응 |
|---|---|---|
| `CAM_INVALID_INPUT` | 점열/파라미터 범위 오류 | 입력 검증 |
| `CAM_INTERNAL_ERROR` | 변환 실패 | 로그 확인 후 재시도 |
| `BENDING_BUSY` | 이미 벤딩 실행 중 | `/api/bending/status` 확인 후 대기 |
| `MOTOR_HOME_ERROR` | 센서 없는 축 호밍 / 센서 이상 | 축 번호·배선 확인 |
| `MOTOR_MOVE_ERROR` | 이동 실패(범위·E-STOP 등) | `error` 문구 확인 |
| `MOTOR_BUSY` | 모션 중 드라이버 비활성화 시도 | `/stop` 후 재시도 |
| `MOTOR_PROTECTION_ERROR` | 보호 설정 오류 | 파라미터 범위 확인 |
| `CAMERA_OFFLINE` | 카메라 세션 off | `/api/camera/connect` |

모든 에러는 **HTTP 200 + `success:false`** 로 옵니다. HTTP 5xx는 서버 장애입니다.

---

## 8. Mock 모드 — 장비 없이 개발

```bash
OB_MOCK_MODE=true python3 -m uvicorn server.main:app --reload --port 8000
```
동일한 API가 하드웨어 없이 응답합니다. CI·프론트엔드 개발에 사용하세요
(자세한 차이는 [03_MOCK_MODE.md](03_MOCK_MODE.md)).

---

## 9. 예제 코드

| 파일 | 내용 |
|---|---|
| `src/app/sdk-examples/python/cam_from_curve.py` | 3D 곡선 → 프리뷰 → 실행 → 진행률 |
| `src/app/sdk-examples/python/precise_positioning.py` | 홈 → 절대 이동 → 검증 (축 직접 제어) |
| `src/app/sdk-examples/curl/api_examples.sh` | 주요 엔드포인트 curl 모음 |
