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

### POST `/api/motor/move`
```json
{ "axis": 0, "distance": 10.0, "speed": 5.0 }
```
- `axis`: 0=FEED, 1=BEND, 2=ROTATE, 3=LIFT
- `distance`: mm (FEED) 또는 ° (BEND/ROTATE)
- `speed`: mm/s 또는 °/s, `> 0`
- `distance`: non-zero (양수=정방향, 음수=역방향)

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
- `axis_mask=0` → 모든 enabled 축
- StallGuard2 기반 기계적 endstop 검출

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

### GET `/api/camera/status`
```json
{
  "connected": true,
  "device_id": "1800 U-158m",
  "width": 1456, "height": 1088,
  "exposure_us": 5000.0, "gain_db": 0.0,
  "format": "mono8",
  "backend": "vimba_x",
  "fps": 30.0,
  "power_state": "on"
}
```
- `power_state`: `"on" | "off"` — SDK 세션 라이프사이클 상태.
  `"off"` 일 때는 capture/stream/settings 호출이 `CAMERA_OFFLINE` 으로 거부됩니다.

> **교체 투명성 주의사항**: `device_id`, `backend` 필드는 **참고/진단용**입니다.
> 값은 하드웨어 세대/센서 교체/백엔드 전환(vimba_x → v4l2 → mock)에 따라 바뀔 수
> 있습니다. **클라이언트 코드는 이 값에 조건 분기하지 마세요** —
> 자세한 이유는 [HARDWARE_ABSTRACTION.md](../architecture/02_HARDWARE_ABSTRACTION.md) 를 참고하세요.


### POST `/api/camera/capture`
```json
{ "quality": 85 }
```
- `quality`: JPEG 품질 (1~100, 기본 85)
- 응답: `{ "frame_b64": "...", "width", "height", "timestamp_us" }`

### POST `/api/camera/settings`
```json
{ "exposure_us": 3000, "gain_db": 6.0, "format": "mono8" }
```
- `format`: `mono8 | mono12 | rgb8`
- 필드는 모두 optional — 보내는 것만 변경됨

### POST `/api/camera/connect`
카메라 SDK 세션을 재오픈합니다. body 없음.
- 백엔드 탐색 순서: Vimba X → GStreamer → V4L2 → Mock
- 응답: `CameraStatusResponse` (`power_state="on"`)
- 이미 connected 상태면 즉시 성공 (idempotent)
- **에러 `CAMERA_CONNECT_FAILED`**: 모든 백엔드가 실패

### POST `/api/camera/disconnect`
Vimba X SDK 를 정상 종료 시퀀스로 닫습니다 (frame release → `cam.__exit__()` →
`vmb.__exit__()`). body 없음.
- 응답: `CameraStatusResponse` (`power_state="off"`)
- 이후 capture/stream/settings 은 `CAMERA_OFFLINE` 반환
- 용도: 카메라 교체, 장시간 유휴, SDK 재초기화. **USB/VBUS 는 건드리지 않습니다.**

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

현재 제한 없음. WebSocket 은 서버 측에서 broadcast 를 10 Hz 로 스로틀링.
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
