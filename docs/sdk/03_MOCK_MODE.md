# Mock Mode — 하드웨어 없이 개발하기

Ortho-Bender SDK 는 실제 i.MX8MP 보드와 카메라 없이도 완전히 동일한 API 를
제공하는 **Mock 모드**를 내장하고 있습니다. 프론트엔드, 통합, 단위 테스트
어디에서든 하드웨어를 기다리지 않고 개발할 수 있습니다.

---

## 1. 왜 Mock 모드가 필요한가

| 상황 | Mock 으로 해결 |
|------|--------------|
| 하드웨어 수량 부족 | ✅ 개발자 수 만큼 로컬 실행 |
| 펌웨어 빌드 대기 | ✅ M7 없이 IPC 시뮬레이션 |
| CI 에서 자동 테스트 | ✅ GitHub Actions 등에서 실행 |
| 프론트엔드 데모 | ✅ 노트북만으로 풀 스택 시연 |
| 회귀 테스트 | ✅ 결정적(deterministic) 응답 |
| 외부 개발자 온보딩 | ✅ 5분 안에 API 체험 |

**실 API 와 완전히 동일한 envelope/필드/에러 코드**를 반환하므로, 프로덕션
코드 한 줄도 바꾸지 않고 그대로 사용할 수 있습니다.

---

## 2. 활성화

### 2.1 환경변수
```bash
OB_MOCK_MODE=true python3 -m uvicorn server.main:app --reload --port 8000
```

### 2.2 자동 폴백
`OB_MOCK_MODE=false` 로 시작했지만 하드웨어가 감지되지 않으면 백엔드가 자동으로
mock 으로 폴백합니다:
```
[WARNING] IPC connect failed (/dev/rpmsg0 not found) — falling back to mock motor
[WARNING] IpcClient: running in MOCK mode — no hardware required
```
카메라와 IPC 는 **독립적으로** 폴백합니다 — 예를 들어 카메라는 실기기지만
M7 이 없는 경우, 카메라만 실제 VmbPy 로 동작하고 IPC 는 mock.

### 2.3 설정 파일 (선택)
`src/app/server/.env`:
```
OB_MOCK_MODE=true
OB_LOG_LEVEL=debug
```

---

## 3. Mock 이 제공하는 것

### 3.1 Motor Service
- `/api/motor/status` — realistic position/velocity 업데이트
- `/api/motor/move` — distance 만큼 즉시 position 증가 (시간 지연 없음)
- `/api/motor/jog` — 연속 jog, stop 호출 시 정지
- `/api/motor/home` — 모든 축 0 으로 리셋, `state=IDLE`
- `/api/motor/stop` — 즉시 감속
- `/api/motor/reset` — 폴트 클리어

### 3.2 Bending / CAM 시뮬레이션 ⭐
B-code 실행 시 **step-by-step 진행 시뮬레이션**:
- 각 스텝당 ~0.3초 소요 (실기기에 가까운 체감)
- 6개 sub-tick 으로 나뉘어 position/velocity 점진 갱신
- `/api/bending/status` 에서 `current_step`, `progress_pct`, `running` 실시간 관찰 가능
- `/ws/motor` 는 10 Hz 로 스트림 → 프론트엔드 게이지 애니메이션 검증

```bash
# Mock 에서 B-code 실행 + 진행률 폴링
curl -X POST http://localhost:8000/api/bending/execute -d '{...}'
while true; do
  curl -s http://localhost:8000/api/bending/status
  sleep 0.1
done
```

### 3.3 Camera Service
- `/api/camera/status` — `backend: "mock"`, 고정 1456×1088
- `/api/camera/capture` — 합성 그라디언트 JPEG + 타임스탬프 오버레이
- `/api/camera/settings` — 값 저장만 (실제 센서 변경 없음)
- `/ws/camera` — 합성 프레임 스트림 (`10 Hz`)

합성 프레임은 진짜 카메라처럼 매 프레임 내용이 변합니다 (밝기 gradient + tick).

### 3.4 System Service
- `uptime_s` — 프로세스 시작 이후 실제 경과
- `motion_state` — mock IPC 상태 반영
- `active_alarms` — 0
- `cpu_temp_c` — null (mock)

---

## 4. Mock 의 한계

| 영역 | 실기기 | Mock |
|------|--------|------|
| 스프링백 정확도 | 재질별 ML 보정 | 고정 계수만 |
| 카메라 노출/게인 | 실제 센서 반영 | 값만 저장 |
| TMC DRV_STATUS | 하드웨어 폴트 감지 | 항상 `0` |
| E-STOP 응답시간 | <1 ms HW latch | Software only |
| 모션 타이밍 | 물리적 가감속 프로파일 | 단순 step_duration |
| WiFi 설정 | NetworkManager 호출 | 값만 저장 |
| NPU 추론 | 실제 모델 | stub |

**Mock 에서 통과했다고 실기기에서도 통과한다고 보장할 수 없습니다.**
최종 검증은 반드시 실기기에서 수행하세요.

---

## 5. 프론트엔드 개발 워크플로우

권장 구성 (하드웨어 없이):

```bash
# Terminal 1 — 백엔드 (노트북 로컬)
cd src/app/server
OB_MOCK_MODE=true python3 -m uvicorn server.main:app --reload --port 8000

# Terminal 2 — 프론트엔드 dev server
cd src/app/frontend
VITE_BACKEND_URL=http://localhost:8000 npm run dev
```

브라우저 `http://localhost:5173/` 접속 → 모든 기능 동작.

### 시나리오 테스트

```ts
// React 컴포넌트에서
const runDemoSequence = async () => {
  await fetch("/api/bending/execute", {
    method: "POST",
    body: JSON.stringify({
      steps: generateDemoBcode(),
      material: 0,
      wire_diameter_mm: 0.457,
    }),
  });

  // /ws/motor 구독으로 진행률 관찰
};
```

Mock IPC 가 ~1.2초 (4 step × 0.3초) 동안 position 을 선형 증가시키므로
UI 게이지가 자연스럽게 움직입니다.

---

## 6. 단위 테스트 / CI

### 6.1 pytest
```bash
cd src/app/server
OB_MOCK_MODE=true pytest tests/ -v
```

테스트 예:
```python
# tests/test_bending.py
async def test_bcode_execute_updates_progress():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.post("/api/bending/execute", json={
            "steps": [{"L_mm": 10, "beta_deg": 0, "theta_deg": 30}] * 3,
            "material": 0,
            "wire_diameter_mm": 0.457,
        })
        assert r.json()["success"] is True

        # 진행률이 0에서 100으로 증가하는지 확인
        await asyncio.sleep(1.0)
        s = await ac.get("/api/bending/status")
        assert s.json()["data"]["current_step"] >= 1
```

### 6.2 GitHub Actions
```yaml
- name: Run backend tests
  run: |
    cd src/app/server
    pip install -r requirements.txt pytest httpx
    OB_MOCK_MODE=true pytest tests/ -v
```

---

## 7. 결정적 Mock 만들기 (향후)

현재 mock 은 `time.monotonic()` 기반 — 재현 불가능한 타이밍입니다.
결정적 테스트가 필요한 경우 다음 방법을 고려하세요:

```python
# 환경변수로 mock 속도 조절
os.environ["OB_MOCK_STEP_DURATION"] = "0.01"  # 0.3 → 0.01
```

(현재 구현되지 않음 — 이슈 #TBD)

---

## 8. 실기기 vs Mock 판별

### 8.1 모터 백엔드 3-mode 구조

모터 진단 서비스는 `OB_MOTOR_BACKEND` 환경변수로 3가지 모드 중 하나를 선택합니다:

| 모드 | 환경변수 값 | 용도 | 하드웨어 의존 |
|------|------------|------|-------------|
| Mock | `mock` (기본) | 개발, CI, 데모 | 없음 |
| Spidev | `spidev` | EVK 테스트 벤치 | Linux spidev + gpiod |
| M7 | `m7` | 프로덕션 | M7 RPMsg IPC |

현재 모터 백엔드 모드를 확인하려면:
```bash
curl http://localhost:8000/api/motor/diag/backend
```
```json
{
  "success": true,
  "data": {
    "backend": "spidev",
    "drivers": ["tmc260c_0", "tmc260c_1", "tmc5072"]
  }
}
```

### 8.2 시스템 상태 확인

```bash
curl http://localhost:8000/api/system/status
```
```json
{
  "ipc_connected": false,       // ← mock 이면 false
  "m7_heartbeat_ok": false,
  "camera_connected": true      // ← 폴백 시 혼합 가능
}
```

```bash
curl http://localhost:8000/api/camera/status
```
```json
{
  "backend": "mock"             // ← mock 이면 "mock", 실기기면 "vimba_x"
}
```

---

## 9. 주요 파일

| 파일 | 역할 |
|------|------|
| `services/ipc_client.py` | Mock IPC + `_simulate_bcode` |
| `services/camera_service.py` | Mock 카메라 프레임 생성 |
| `services/motor_service.py` | IPC 응답 파싱 (실/mock 공통) |
| `services/motor_backend.py` | MotorBackend ABC + MockMotorBackend |
| `services/spi_backend.py` | SpidevMotorBackend (Linux spidev + gpiod v2) |
| `services/diag_service.py` | TMC 진단 서비스 (3개 백엔드 공통) |
| `config.py` | `OB_MOCK_MODE`, `OB_MOTOR_BACKEND` 환경변수 로드 |

---

## 10. 관련 문서

- [SDK_GUIDE.md](01_SDK_GUIDE.md) — 메인 사용 가이드
- [DEPLOYMENT.md](04_DEPLOYMENT.md) — 실기기 배포
- [TROUBLESHOOTING.md](05_TROUBLESHOOTING.md) — 문제 해결
