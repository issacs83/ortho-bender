# API Reference

Ortho-Bender SDK 백엔드의 전체 REST + WebSocket 엔드포인트 레퍼런스.

런타임 Swagger UI: `http://<device>:8000/docs` · OpenAPI JSON: `/openapi.json`

## 공통 사항

- **Base URL**: `http://<device>:8000`
- **Content-Type**: `application/json`
- **모든 응답**: envelope 형식
  ```json
  { "success": true, "data": {...}, "error": null, "code": null }
  ```
- **에러도 HTTP 200**: `success:false` + `error` + `code`. 5xx 는 서버 크래시만.
- **인증**: 현재 없음 (로컬 네트워크 전용). 향후 토큰 기반 추가 예정.

---

## 1. `/api/system` — 시스템 상태

### GET `/api/system/status`
전체 시스템 헬스 리포트.

**Response (data)**
| Field | Type | 설명 |
|-------|------|------|
| `motion_state` | int | `0=IDLE, 1=HOMING, 2=RUNNING, 3=JOGGING, 4=STOPPING, 5=FAULT, 6=ESTOP` |
| `camera_connected` | bool | 카메라 open 상태 |
| `ipc_connected` | bool | M7 RPMsg 링크 정상 여부 |
| `m7_heartbeat_ok` | bool | 최근 M7 heartbeat 수신 |
| `active_alarms` | int | 활성 알람 개수 |
| `uptime_s` | float | 백엔드 가동 시간 |
| `cpu_temp_c` | float? | SoC 온도 (가능한 경우) |

### GET `/api/system/version`
`sdk_version`, `m7_firmware`, `m7_build_timestamp` 반환.

### POST `/api/system/reboot`
```json
{ "confirm": true }
```
`confirm:true` 필수. 시스템 재부팅.

---

## 2. `/api/motor` — 모터 직접 제어

> 📐 **좌표를 보내기 전에 [06_AXIS_CONVENTIONS.md](06_AXIS_CONVENTIONS.md) 를 읽으세요.**
> 축별 단위(FEED/BEND = deg, LIFT = mm), 부호(LIFT는 `+`가 **아래**), 홈 기준,
> 캘리브레이션 값이 정리되어 있습니다.
>
> **axis 번호**: `0=FEED, 1=BEND, 2=ROTATE(미장착), 3=LIFT`


### GET `/api/motor/status`
**Response (data)**
```json
{
  "state": 0,
  "axes": [
    { "axis": 0, "position": 12.345, "velocity": 0.0,
      "drv_status": 0, "sg_result": 0, "cs_actual": 16 },
    { "axis": 1, "position": 45.0, "velocity": 0.0, ... }
  ],
  "current_step": 4,
  "total_steps": 4,
  "axis_mask": 3
}
```
- `axis_mask` 비트: `0x01=FEED, 0x02=BEND, 0x04=ROTATE, 0x08=LIFT`
- `drv_status`: TMC DRV_STATUS 원본 레지스터 값
- `sg_result`: StallGuard2 로드 측정값
- `driver_enabled`: TMC260C-PA `DRV_ENN` 라인 상태. `true`=코일 여자(ENERGIZED),
  `false`=코일 해제(FREE-WHEEL, 축 수동 회전 가능)

### POST `/api/motor/move` — **상대 이동**
```json
{ "axis": 1, "distance": 10.0, "speed": 60.0 }
```
현재 위치에서 `distance` **만큼** 움직입니다. 좌표로 가려면 아래 `/move_to` 를 쓰세요.
- `distance`: deg(FEED·BEND·ROTATE) 또는 mm(LIFT). 0 불가, 양수/음수로 방향 지정
- `speed`: deg/s 또는 mm/s, `> 0`
- **1회 명령 상한**을 넘으면 잘립니다(FEED·BEND 360, LIFT 240, 이동시간 10 s).
  긴 이동은 `/move_to` 를 쓰면 자동 분할됩니다.

### POST `/api/motor/move_to`
```json
{ "axis": 1, "position": 5.0, "speed": 8 }
```
**절대 이동** — `position` 좌표까지 이동합니다(`/move` 는 상대 이동).
- 단위는 축을 따릅니다: FEED·BEND·ROTATE = deg, LIFT = mm
- **긴 이동은 자동 분할** 됩니다. 1회 펄스는 거리 상한과 10 s 시간 상한에 걸리지만,
  `move_to` 는 목표에 닿을 때까지 반복 실행합니다(230 mm LIFT 이동 실측 오차 0.00 mm)
- 가감속은 **지정 위치 안에서 완결** — 45°를 지령하면 45°를 지나치지 않고 45°에 정지
- 도달 판정: 2 스텝 이내(BEND 0.09°, LIFT 0.01 mm). 축이 막히면 로그를 남기고 중단

### GET `/api/motor/calibration`
**Response (data)**
```json
{
  "steps_per_unit": { "0": 200.0, "1": 23.0167, "2": 200.0, "3": 200.0 },
  "distance_limit": { "0": 360.0, "1": 360.0, "2": 360.0, "3": 240.0 },
  "speed_limit":    { "0": 40.0,  "1": 347.6,  "2": 40.0,  "3": 40.0 }
}
```
- `steps_per_unit`: 축의 단위(deg 또는 mm)당 STEP 수. **모든 좌표·속도 변환의 기준**
- `distance_limit`: 1회 명령당 이동 거리 상한 (초과분은 `/move` 에서 잘리고,
  `/move_to` 는 자동 분할)
- `speed_limit`: **하드웨어 STEP 상한(8 kHz) ÷ `steps_per_unit`** 으로 자동 산출된
  축별 최대 속도. 캘리브레이션을 바꾸면 이 값도 따라 바뀌므로, 클라이언트는
  하드코딩하지 말고 이 필드를 읽으세요.
  (예: FEED 200 steps/deg → 40 deg/s, BEND 23.0167 → 347.6 deg/s)

### POST `/api/motor/calibration`
```json
{ "axis": 1, "steps_per_unit": 23.0167 }
```
축 캘리브레이션 변경 — 보드에 영속 저장됩니다
(`/var/lib/ortho-bender/axis_calibration.json`). 측정 방법은
[06_AXIS_CONVENTIONS.md](06_AXIS_CONVENTIONS.md) §7 참고.

### GET / PUT `/api/motor/protection`
```json
{ "limit_stop": true, "hold_enabled": true, "hold_cs": 8 }
```
- `limit_stop`: **이동 중 리밋센서 감지 시 자동 정지** (에지 트리거 —
  홈(창 안)에서 출발할 땐 창을 벗어날 때까지 가드 비활성이라 이탈은 항상 허용)
- `axes`: **축별 정지토크** `{axis: {hold_enabled, hold_cs}}`
  (axis 0=FEED, 1=BEND, 3=LIFT). 유휴 시 코일을 통전 유지해 축이 외력·중력에
  밀리지 않게 합니다. `hold_cs` 1–19(PSU 캡 우선) — 낮출수록 조용·저발열·저토크.
  PUT은 부분 업데이트(보낸 축만 변경), 유휴 상태면 즉시 반영되고 서버 기동 시에도
  설정된 축이 바로 통전됩니다.
- `hold_enabled` / `hold_cs`(최상위): LIFT 전용 레거시 별칭 — 신규 클라이언트는
  `axes` 를 사용하세요.
- 기본값: LIFT·FEED 홀딩 ON, BEND OFF (`hold_lift`/`hold_feed`/`hold_bend` 설정)

**예시 — FEED 홀딩을 최대 토크로**
```bash
curl -X PUT http://<ip>:8000/api/motor/protection \
     -H 'Content-Type: application/json' \
     -d '{"axes": {"0": {"hold_enabled": true, "hold_cs": 14}}}'
```

### POST `/api/motor/jog`
```json
{ "axis": 1, "direction": 1, "speed": 3.0, "distance": 0 }
```
- `direction`: `+1` 또는 `-1`
- `distance=0` → 연속 조그 (stop 호출까지)

### POST `/api/motor/home`
```json
{ "axis_mask": 0 }
```
**리밋 스위치 호밍** (PM-L25 포토인터럽터: LIFT=J21 pin7, BEND=J21 pin11).
- `axis_mask=0` → 스위치 장착 축 전체. 비트: `0x02=BEND, 0x08=LIFT`
  (FEED는 센서가 없어 `axis_mask=0x01` 지정 시 `MOTOR_HOME_ERROR`)
- **축 특성별 탐색** (2026-08 실기 확정):
  - **BEND(회전축)**: 센서 창이 1회전에 1개 → 한 방향으로 **1회전 + 여유**만 탐색하면
    반드시 만납니다. 역방향 탐색 없음, 하드스톱 없음
  - **LIFT(직선축)**: 스위치가 **스트로크 최상단**에 있으므로 위 방향으로 **전체 스트로크**
    를 한 번에 훑습니다(20 mm/s). 시작 위치가 어디든 안전
- 창 발견 후 항상 같은 쪽으로 빠져나와 **같은 에지·같은 방향·저속으로 래치**해
  반복정밀도를 확보하고, **감지점을 0(datum)** 으로 삼습니다. 이후 창 안쪽으로
  살짝 정착해 센서가 확실히 감지 상태가 되게 합니다.
- **즉시 반환**(state=HOMING). 완료는 `GET /api/motor/limits` 의 `homing:false`
  또는 `/ws/motor` 스트림으로 확인하세요.
- `POST /jog/stop` 또는 E-STOP으로 취소되며, 취소 시 `limits.error` 에 사유가 남습니다.
- 홈 완료 축은 `limits.homed` 에 기록되고 **재부팅 후에도 유지**됩니다.

### GET `/api/motor/limits`
**Response (data)**
```json
{ "limits": { "1": false, "3": true }, "homed": [1],
  "homing": false, "error": null }
```
- `limits`: 축별 리밋 스위치 실시간 상태 (장착 축만: 1=BEND, 3=LIFT). true=감지됨
- `homed`: 서버 시작 후 호밍 완료된 축 / `homing`: 호밍 진행 중 / `error`: 최근 실패 사유
- 스위치 상태는 모터 상태 스트림의 `signals.limit` 로도 축별 제공됨

### POST `/api/motor/zero`
```json
{ "axis": 1, "value": 0 }
```
영점(기준점) 설정 — 현재 물리 위치를 `value`(기본 0, mm/°)로 선언합니다.
- 모션 없음. 축을 기준 위치(기계적 스토퍼, 마킹)로 조그한 뒤 호출
- 위치 카운터는 재시작 후에도 유지됨
- **센서가 있는 축(BEND·LIFT)은 `/home` 을 쓰세요.** 이 API는 주로 **FEED**(센서 없음)
  의 원점을 잡거나, 좌표계를 임의 값으로 옮길 때 사용합니다

### GET `/api/motor/profiles`
**Response (data)**
```json
{ "profiles": { "0": { "jog_speed": 10.0, "max_speed": 40.0,
  "step_size": 1.0, "start_hz": 200, "accel": 40.0, "decel": 40.0,
  "shape": "linear" }, "1": { ... } } }
```
축별 모션 프로파일 (조그 기본값 + 가감속 형상). 보드에
`/var/lib/ortho-bender/motion_profiles.json` 으로 영속 저장.

### PUT `/api/motor/profiles/{axis}`
```json
{ "jog_speed": 12.0, "shape": "scurve" }
```
부분 업데이트 — 생략한 필드는 유지.
- `jog_speed` (0–360, deg/s 또는 mm/s), `step_size` (0–360)
- `max_speed` (0–360): 축별 **기계 속도 한계** (GRBL `$110-112` 상당) —
  jog/move 등 모든 모션 명령의 speed 가 커맨드 시점에 이 값으로 클램프됨.
  `jog_speed` 는 이 값을 넘을 수 없음
- `start_hz` (50–2000): 램프 시작(플로어) STEP 주파수
- `accel` / `decel` (1–200): 가감속, **물리 단위 (mm/s² 또는 °/s²)** —
  GRBL `$120-122` / LinuxCNC `MAX_ACCELERATION` 상당. 커맨드 시점에 축
  캘리브레이션(steps_per_unit)으로 STEP 슬루율(Hz/s, 200–40000 클램프)로
  환산되므로 마이크로스텝/캘리브레이션이 바뀌어도 의미가 유지됨
- `shape`: `"linear"`(사다리꼴) 또는 `"scurve"`(저크 제한 smoothstep —
  피크 가속도가 `accel` 설정값과 같아, S-curve 전환 시에도 설정 가속도를
  초과하지 않음)
- 감속 램프는 조그 정지/자연 종료 시 적용. 폴트·스톨·E-STOP 은 하드 스톱 유지
- 참고: S-curve 감속은 같은 `decel` 에서 linear 대비 **정지 시간·거리가
  1.5배** (피크 가속도를 유지하는 대가). 정밀 정지 위치가 중요하면 linear 사용

### POST `/api/motor/stop`
모든 축 즉시 감속 정지. body 없음.

### POST `/api/motor/reset`
```json
{ "axis_mask": 0 }
```
DRV_STATUS 폴트 클리어. 재홈잉 필요할 수 있음.

### POST `/api/motor/enable`
TMC260C-PA `DRV_ENN` 라인을 active(LOW)로 내려 코일을 여자시킵니다. body 없음.
- 응답: `MotorStatusResponse` (`driver_enabled=true`)
- 이미 enabled 상태에서 호출해도 성공 (idempotent)

### POST `/api/motor/disable`
`DRV_ENN`을 inactive(HIGH)로 올려 드라이버 출력단을 꺼버립니다 (FREE-WHEEL).
body 없음.
- 응답: `MotorStatusResponse` (`driver_enabled=false`)
- **에러 `MOTOR_BUSY`**: `state` 가 `IDLE/FAULT/ESTOP` 이 아닐 때 — 모션 중에는
  거부됩니다. 먼저 `/api/motor/stop` 을 호출하세요.
- 용도: 유지보수/티칭, 장시간 유휴 시 발열·전력 절감. **E-STOP 대체용 아님.**

---

## 3. `/api/camera` — 카메라

> 2026-08 기준 벤치 카메라는 **Alvium 1800 C (MIPI CSI-2)** 이며 네이티브
> `isi_csi2` 백엔드(raw V4L2 MPLANE + avt3 subdev)로 구동됩니다.
> USB Alvium(VmbPy) 등은 폴백 체인으로 유지됩니다.

### GET `/api/camera/status`
```json
{
  "connected": true,
  "device_id": "Alvium 1800 C (MIPI CSI-2)",
  "width": 816, "height": 624,
  "exposure_us": 20000.0, "gain_db": 0.0,
  "format": "mono8",
  "backend": "isi_csi2",
  "fps": 50.0,
  "power_state": "on"
}
```
- `power_state`: `"on" | "off"` — SDK 세션 라이프사이클 상태.
  `"off"` 일 때는 capture/stream/settings 호출이 `CAMERA_OFFLINE` 으로 거부됩니다.

> **교체 투명성 주의사항**: `device_id`, `backend` 필드는 **참고/진단용**입니다.
> 값은 하드웨어 세대/센서 교체/백엔드 전환(isi_csi2 → vimba_x → mock)에 따라
> 바뀔 수 있습니다. **클라이언트 코드는 이 값에 조건 분기하지 마세요** —
> 자세한 이유는 [HARDWARE_ABSTRACTION.md](../architecture/02_HARDWARE_ABSTRACTION.md) 를 참고하세요.

### POST `/api/camera/capture?quality=85`
단일 프레임을 **raw JPEG 바이너리**(`image/jpeg`)로 반환합니다.
- `quality`: JPEG 품질 (1~100, 기본 85)
- 카메라 오프라인 시 412 `CAMERA_OFFLINE`

### GET `/api/camera/stream?fps=15`
MJPEG 스트림 (`multipart/x-mixed-replace`). `<img src>` 로 바로 사용.
- `fps`: 1~50 (스키마 강제 — 범위 밖은 422). 센서 ~50fps,
  JPEG 인코드로 실효 ~25fps.

### POST `/api/camera/settings`
```json
{ "exposure_us": 3000, "gain_db": 6.0, "format": "mono8" }
```
- `exposure_us`: 18.9µs ~ 10s (하드웨어 클램프, 반영까지 2~3프레임)
- `gain_db`: 0 ~ 48 dB (0.1 dB 스텝)
- 필드는 모두 optional — 보내는 것만 변경됨

### GET / POST `/api/camera/controls` — 전체 파라미터 표면
드라이버가 노출하는 **모든** 컨트롤을 동적으로 열거/설정합니다
(C-052m 기준 30개: 노출+오토윈도우, 게인+오토윈도우, 감마, 블랙레벨,
Reverse X/Y, 비닝, 트리거 풀세트, 온도/펌웨어/시리얼 등).
- GET 응답 항목: `id, name, type, min/max/step/default, read_only,
  inactive, value, menu{}` — 값은 드라이버 원시 단위
  (노출 ns, 게인 밀리벨, 감마 ×100, 온도 0.1°C)
- POST body: `{ "id": <controls의 id>, "value": <int 또는 int 배열> }`
  — compound 컨트롤(예: AREA 타입 `Binning Setting` = [가로, 세로])은
  배열로. 버튼형(Trigger Software)은 value 무시하고 발화.
- 응답은 **하드웨어가 실제 수락한 값**(클램프 반영)

### GET / POST `/api/camera/roi` — 센서 영역(크롭)
ROI 는 V4L2 컨트롤이 아니라 subdev **selection API** 라서 `/controls`
에 없습니다.
- GET: `{ crop, bounds, default, capture }` (각각 left/top/width/height)
- POST: `{ "left": 100, "top": 50, "width": 400, "height": 300 }`
  — 적용 시 캡처/스트림이 새 크기로 재시작, 드라이버가 정렬 단위로
  보정한 실제 값이 응답에 담김 (예: 300 → 304)

### GET / POST `/api/camera/framerate` — 센서 취득 프레임레이트
subdev **frame-interval API** (역시 `/controls` 밖). 낮출수록 노출 시간
상한이 올라갑니다. 변경 시 스트림이 잠시 재시작됩니다.
- POST: `{ "fps": 30 }` → 응답 `{ "fps": 30.0 }` (적용값)

### POST `/api/camera/connect`
카메라 세션을 재오픈합니다. body 없음.
- 백엔드 탐색 순서: **isi_csi2 (MIPI)** → VmbPy → Vimba X GStreamer →
  V4L2 GStreamer → UVC → Mock
- 부팅 직후 카메라가 늦게 뜨는 경우 서버가 **백그라운드에서 자동
  재연결**하므로 일반적으로 수동 호출이 필요 없습니다
- 이미 connected 상태면 즉시 성공 (idempotent)
- **에러 `CAMERA_CONNECT_FAILED`**: 모든 백엔드가 실패

### POST `/api/camera/disconnect`
카메라를 정상 종료합니다 (스트림 정지·버퍼 해제; VmbPy 백엔드는 SDK
네이티브 시퀀스). body 없음.
- 응답: `CameraStatusResponse` (`power_state="off"`)
- 이후 capture/stream/settings 은 `CAMERA_OFFLINE` 반환

---

## 4. `/api/bending` — B-code 시퀀스 실행

### POST `/api/bending/execute`
```json
{
  "steps": [
    { "L_mm": 10.0, "beta_deg": 0.0, "theta_deg": 30.0 },
    { "L_mm": 15.0, "beta_deg": 90.0, "theta_deg": 45.0 }
  ],
  "material": 0,
  "wire_diameter_mm": 0.457
}
```
- `steps`: 1~128 개
- `L_mm`: 0.5~200.0
- `beta_deg`: -360.0~360.0
- `theta_deg`: 0.0~180.0 (스프링백 적용 전)
- `material`: `0=SS_304, 1=NITI, 2=BETA_TI, 3=CU_NITI`
- 즉시 반환 → `/status` 로 진행률 폴링

**에러**: `BENDING_BUSY` — 이전 시퀀스 진행 중

### GET `/api/bending/status`
```json
{
  "running": true,
  "current_step": 3,
  "total_steps": 10,
  "progress_pct": 30.0,
  "material": 0,
  "wire_diameter_mm": 0.457
}
```

### POST `/api/bending/stop`
현재 시퀀스 감속 정지 + 상태 초기화.

---

## 5. `/api/cam` — 3D 커브 → B-code CAM

### POST `/api/cam/generate`
```json
{
  "points": [
    { "x": 0, "y": 0, "z": 0 },
    { "x": 10, "y": 0, "z": 0 },
    { "x": 20, "y": 5, "z": 2 }
  ],
  "material": 0,
  "wire_diameter_mm": 0.457,
  "min_segment_mm": 1.0,
  "apply_springback": true
}
```
- `points`: 2~512 개
- `min_segment_mm`: 이산화 최소 세그먼트 (기본 1.0)
- `apply_springback`: false → 원본 theta 유지 (디버그)

**Response**
```json
{
  "steps": [ ... ],
  "segment_count": 2,
  "total_length_mm": 25.38,
  "max_bend_deg": 27.5,
  "warnings": []
}
```
프리뷰 전용. 모션 없음. 반복 호출 안전.

### POST `/api/cam/execute`
`/generate` 와 동일 body, 생성 즉시 모터에 디스패치. 진행률은 `/api/bending/status`.

**에러 코드**
- `CAM_INVALID_INPUT` — 정점 부족, 범위 초과
- `CAM_EXECUTE_ERROR` — 모터 디스패치 실패

---

## 6. `/api/wifi` — WiFi 설정 (선택)

### GET `/api/wifi/status`
현재 AP 연결 정보 (SSID, RSSI, IP).

### POST `/api/wifi/connect`
```json
{ "ssid": "lab-wifi", "password": "..." }
```
- 연결 성공 시 새 IP 를 응답에 포함

### POST `/api/wifi/disconnect`
현재 AP 에서 해제.

---

## 7. WebSocket

### `/ws/motor` — 10 Hz 모터 스트림
```json
{
  "type": "motor_status",
  "state": 2,
  "axes": [ { "axis": 0, "position": 8.3, "velocity": 5.0, ... } ],
  "timestamp_us": 1234567890
}
```

### `/ws/camera` — 카메라 프레임 스트림
```json
{
  "type": "camera_frame",
  "frame_b64": "<base64 JPEG>",
  "width": 1456,
  "height": 1088,
  "timestamp_us": 1234567890
}
```
클라이언트 `max_size` 는 최소 4 MB 권장.

### `/ws/system` — 이벤트 기반 시스템 알림
```json
{
  "type": "alarm",
  "severity": 1,
  "alarm_code": 101,
  "message": "TMC overtemperature warning",
  "timestamp_us": 1234567890
}
```
- `severity`: `0=WARNING, 1=FAULT, 2=CRITICAL`
- `type`: `alarm | state_change | heartbeat`

---

## 7.5 `/api/motor/diag` — TMC 레지스터 진단

모터 드라이버(TMC260C x2, TMC5072)에 대한 저수준 SPI 레지스터 접근.
테스트 벤치 진단 및 드라이버 구성 검증용.

### GET `/api/motor/diag/backend`
현재 모터 백엔드 모드와 등록된 드라이버 목록.

**Response (data)**
```json
{
  "backend": "spidev",
  "drivers": ["tmc260c_0", "tmc260c_1", "tmc5072"]
}
```
- `backend`: `"mock" | "spidev" | "m7"`

### GET `/api/motor/diag/spi-test`
모든 드라이버에 SPI 통신 테스트 (ping).

**Response (data)**
```json
{
  "results": [
    { "driver": "tmc260c_0", "ok": true, "latency_us": 42.3, "error": null },
    { "driver": "tmc260c_1", "ok": true, "latency_us": 38.1, "error": null },
    { "driver": "tmc5072",   "ok": false, "latency_us": 2001.0, "error": "SPI timeout" }
  ]
}
```

### GET `/api/motor/diag/register/{driver}/{addr}`
단일 레지스터 읽기.

- `driver`: `tmc260c_0 | tmc260c_1 | tmc5072`
- `addr`: 레지스터 주소 (10진수 또는 `0x` 접두 16진수)

**Response (data)**
```json
{
  "driver": "tmc260c_0",
  "addr": "0x04",
  "value": 65749,
  "value_hex": "0x000100D5"
}
```

### POST `/api/motor/diag/register/{driver}/{addr}`
단일 레지스터 쓰기.

**Request body**
```json
{ "value": 65749 }
```

**Response**: 읽기와 동일 형식 (write-back 값).

### GET `/api/motor/diag/dump/{driver}`
지정 드라이버의 모든 상태 레지스터 덤프.

**Response (data)**
```json
{
  "driver": "tmc260c_0",
  "registers": {
    "DRVCTRL":  "0x00000000",
    "CHOPCONF": "0x000901B5",
    "SMARTEN":  "0x000A8202",
    "SGCSCONF": "0x000D0505",
    "DRVCONF":  "0x000EF040"
  }
}
```

### `/ws/motor/diag` — 200 Hz 진단 스트림

StallGuard2 + 드라이버 상태를 200 Hz (5 ms 간격)로 브로드캐스트.
TMC260C 0/1에 대한 실시간 로드/폴트 모니터링용.

```json
{
  "type": "diag_status",
  "timestamp_us": 1234567890,
  "drivers": {
    "tmc260c_0": {
      "sg_result": 245,
      "stst": false,
      "ot": false,
      "otpw": false,
      "s2ga": false,
      "s2gb": false,
      "ola": false,
      "olb": false
    },
    "tmc260c_1": null
  }
}
```
- `sg_result`: StallGuard2 측정값 (0~1023, 높을수록 부하 적음)
- `stst`: standstill indicator
- `ot`: overtemperature shutdown
- `otpw`: overtemperature pre-warning
- `s2ga/s2gb`: short to ground (coil A/B)
- `ola/olb`: open load (coil A/B)
- 드라이버 값이 `null`이면 해당 드라이버 통신 실패

**에러 코드** (진단 전용)

| Code | 언제 | 조치 |
|------|------|------|
| `DIAG_BACKEND_ERROR` | 백엔드 정보 조회 실패 | 서비스 재시작 |
| `SPI_TEST_ERROR` | SPI 테스트 실행 실패 | 배선/전원 확인 |
| `INVALID_PARAM` | 잘못된 driver 이름 또는 주소 | `tmc260c_0 / tmc260c_1 / tmc5072` 사용 |
| `DIAG_READ_ERROR` | 레지스터 읽기 SPI 실패 | SPI 배선 확인 |
| `DIAG_WRITE_ERROR` | 레지스터 쓰기 SPI 실패 | SPI 배선 확인 |
| `DIAG_DUMP_ERROR` | 덤프 실패 | 드라이버 전원 확인 |

---

## 8. 에러 코드 카탈로그

| Code | HTTP | 언제 | 조치 |
|------|------|------|------|
| `INTERNAL_ERROR` | 200 | 예상치 못한 예외 | 로그 확인 |
| `BENDING_BUSY` | 200 | 시퀀스 진행 중 | `/status` 확인 또는 `/stop` |
| `BENDING_STOP_ERROR` | 200 | stop 실패 | 재시도, 안 되면 reboot |
| `CAM_INVALID_INPUT` | 200 | 정점 부족/범위 | 입력 검증 |
| `CAM_EXECUTE_ERROR` | 200 | 모터 디스패치 실패 | 모터 상태 확인 |
| `CAM_INTERNAL_ERROR` | 200 | CAM 알고리즘 크래시 | 입력을 이슈로 보고 |
| `MOTOR_FAULT` | 200 | DRV_STATUS 이상 | `/motor/reset` |
| `IPC_TIMEOUT` | 200 | M7 무응답 | M7 firmware 재기동 |
| `CAMERA_DISCONNECTED` | 200 | USB3 링크 단절 | 커넥터/전원 확인 |
| `CAMERA_OFFLINE` | 200/412 | `/disconnect` 후 capture/stream/settings 호출 | `/api/camera/connect` |
| `CAMERA_CONNECT_FAILED` | 200 | `/connect` 가 모든 백엔드에서 실패 | 카메라 USB·SDK 설치 확인 |
| `MOTOR_BUSY` | 200 | 모션 중 `/motor/disable` 호출 | 먼저 `/motor/stop` |

---

## 9. Rate Limiting

현재 제한 없음. WebSocket 은 서버 측에서 채널별로 스로틀링:
- `/ws/motor`: 10 Hz (100 ms)
- `/ws/camera`: ~15 fps (66 ms)
- `/ws/system`: 1 Hz (1000 ms)
- `/ws/motor/diag`: 200 Hz (5 ms) — 클라이언트 연결 시에만 활성화

`/api/camera/capture` 는 카메라 트리거 한도(~30 fps)에 종속.

---

## 10. Python SDK 예제 단축 인덱스

| 파일 | 용도 |
|------|------|
| `sdk-examples/python/basic_bend.py` | 3-step 벤딩 튜토리얼 |
| `sdk-examples/python/cam_from_curve.py` | 3D 커브 → B-code → 실행 |
| `sdk-examples/python/camera_stream.py` | REST 스냅샷 + WS 스트림 |
| `sdk-examples/python/lifecycle_demo.py` | 카메라·모터 connect/disconnect 라운드 트립 |
| `sdk-examples/curl/api_examples.sh` | cURL 요리책 |
