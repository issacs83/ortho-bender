# Troubleshooting

Ortho-Bender SDK 개발 / 배포 중 자주 발생하는 문제와 해결 방법.

---

## 빠른 진단 순서

문제가 생기면 항상 이 순서로 확인하세요:

1. `curl http://<host>:8000/health` — 백엔드 응답?
2. `curl http://<host>:8000/api/system/status` — IPC / 카메라 상태?
3. 백엔드 로그 (`/tmp/ortho-backend.log` 또는 `journalctl`)
4. M7 시리얼 로그 (`/dev/ttyLP5`)
5. `dmesg | tail` — 커널 레벨 이슈

---

## 1. 백엔드 기동 실패

### 1.1 `ModuleNotFoundError: No module named 'zoneinfo'`
**원인**: Yocto Python 3.10 에 stdlib zoneinfo 가 없음. Pydantic 이 import 실패.

**해결**: shim 설치
```bash
cat > /usr/lib/python3.10/site-packages/zoneinfo.py <<'EOF'
class ZoneInfoNotFoundError(Exception): pass
class ZoneInfo:
    def __init__(self, key): self.key = key
def available_timezones(): return set()
def reset_tzpath(): pass
TZPATH = ()
EOF
```

### 1.2 `pydantic-core version mismatch`
**원인**: Pydantic 과 pydantic-core 버전 페어가 안 맞음.

**해결**:
```bash
pip3 install --force-reinstall pydantic==2.9.2 pydantic-core==2.23.4
```

### 1.3 `No supported WebSocket library detected`
**원인**: uvicorn 이 websockets 패키지를 찾지 못함.

**해결**:
```bash
pip3 install websockets wsproto
```

### 1.4 `Address already in use`
**원인**: 이전 백엔드가 아직 살아있음.

**해결**:
```bash
pkill -f server.main
sleep 2
# 재기동
```

### 1.5 `ImportError: No module named vmbpy`
**원인**: VmbPy 설치 안 됨 (실기기 전용).

**해결**:
```bash
# EVK 에서
pip3 install /opt/VimbaX_2026-1/api/python/vmbpy-1.2.1-py3-none-any.whl
```
또는 mock 모드로 동작:
```bash
OB_MOCK_MODE=true python3 -m uvicorn server.main:app
```

---

## 2. IPC / M7 통신 문제

### 2.1 `IPC connect failed (RPMsg device /dev/rpmsg0 not found)`
**원인**: M7 firmware 가 로드되지 않았거나 remoteproc 이 start 상태가 아님.

**진단**:
```bash
ls /dev/rpmsg*
cat /sys/class/remoteproc/remoteproc0/state
cat /sys/class/remoteproc/remoteproc0/firmware
```

**해결**:
```bash
echo stop > /sys/class/remoteproc/remoteproc0/state
echo "ortho-bender-m7.elf" > /sys/class/remoteproc/remoteproc0/firmware
echo start > /sys/class/remoteproc/remoteproc0/state
dmesg | tail -20      # "remote processor is now up" 확인
```

만약 펌웨어 파일이 없다면: `ls /lib/firmware/`

**임시 우회**: Mock 모드 — 백엔드가 자동 폴백합니다.

### 2.2 `IPC_TIMEOUT` 에러 반복
**원인**: M7 firmware 가 hang 됨 또는 watchdog reset 루프.

**진단**: 시리얼 콘솔에서 M7 로그 확인
```bash
screen /dev/ttyLP5 115200
# 또는
minicom -D /dev/ttyLP5 -b 115200
```

**해결**:
1. M7 재로드: 위 2.1 해결 절차 반복
2. 그래도 안 되면 A53 reboot: `reboot`

### 2.3 RPMsg 메시지 해석 오류 (position 가비지 값)
**증상**: `/api/motor/status` 에 비정상 숫자 (9e-18, 36438 등).

**원인**: 바이너리 payload 파싱 불일치 (엔디안 / 구조체 크기).

**해결**: `src/app/server/services/motor_service.py` 의 `_MOTION_STATUS_FMT` 와
`src/shared/ipc_protocol.h` 구조체가 동일한지 확인.
```python
_MOTION_STATUS_FMT = "<B4f4fHHB"     # state + pos[4] + vel[4] + steps + mask
```

---

## 3. 카메라 문제

### 3.1 `VmbPy: no cameras detected`
**진단**:
```bash
lsusb | grep -i "allied\|avt"
# ID 1ab2:0001 (또는 유사)
ls /dev/video*
```

**해결**:
1. USB3 케이블/포트 확인 — USB2 포트에 꽂으면 인식 안 됨
2. udev 규칙 확인: `/etc/udev/rules.d/10-vimbax.rules`
3. 재플러그: `echo 0 > /sys/bus/usb/devices/<id>/authorized; echo 1 > ...`
4. `GENICAM_GENTL64_PATH` 환경변수 설정
   ```bash
   export GENICAM_GENTL64_PATH=/opt/VimbaX_2026-1/cti
   ```

### 3.2 `CameraService: open failed — device busy`
**원인**: 다른 프로세스가 카메라 점유 중 (`vmbc` GUI 등).

**해결**:
```bash
lsof /dev/bus/usb/*/*
kill <pid>
```

### 3.3 프레임이 검은 화면
**원인**:
1. Exposure 가 너무 낮음
2. Gain 0 dB + 조명 부족
3. 센서 상변태 (Cu-NiTi 벤딩처럼 온도 문제 — 농담)

**해결**:
```bash
curl -X POST http://localhost:8000/api/camera/settings \
  -H 'Content-Type: application/json' \
  -d '{"exposure_us": 10000, "gain_db": 6.0}'
```

### 3.4 `CAMERA_OFFLINE` — capture/stream/settings 거부
**원인**: 이전에 `POST /api/camera/disconnect` 를 호출했거나, 카메라 링크가
끊어져 `power_state` 가 `"off"` 로 떨어진 상태.

**확인**:
```bash
curl -s http://localhost:8000/api/camera/status | jq '.data.power_state'
```

**해결**: 세션을 다시 엽니다.
```bash
curl -s -X POST http://localhost:8000/api/camera/connect
# → success=true, data.power_state="on", data.backend="vimba_x" (실제) 또는 "mock"
```

- `CAMERA_CONNECT_FAILED` 가 돌아오면 실제 USB3 연결/Vimba X 설치를 먼저
  점검하세요 (섹션 3.1).
- 프론트엔드에서는 Camera 페이지 상단 `ConnectionControl` 패널의 **Connect**
  버튼으로 동일한 복구가 가능합니다.

### 3.5 WebSocket 프레임이 끊김
**원인**: 클라이언트 `max_size` 가 작음 (기본 1 MB).

**해결**:
```python
# Python
async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws: ...
```
```ts
// 브라우저는 제한 없음
const ws = new WebSocket(url);
```

---

## 4. 모터 / 벤딩 문제

### 4.1 `BENDING_BUSY` 에러
**원인**: 이전 시퀀스가 아직 진행 중 (상태 플래그만 남아있을 수도).

**해결**:
```bash
# 1) 실제 진행 중인지 확인
curl http://localhost:8000/api/bending/status

# 2) 강제 중단
curl -X POST http://localhost:8000/api/bending/stop

# 3) 그래도 안 되면 백엔드 재기동
```

### 4.2 `MOTOR_BUSY` — `/api/motor/disable` 거부
**원인**: `DRV_ENN` 토글은 `state ∈ {IDLE, FAULT, ESTOP}` 에서만 허용됩니다.
모션 중(HOMING/RUNNING/JOGGING 등)에는 드라이버를 끄면 코일 전류가 갑자기
사라져 급정지 쇼크가 발생하므로, 백엔드가 먼저 정지를 요구합니다.

**해결**:
```bash
# 1) 모션을 먼저 멈춘다
curl -s -X POST http://localhost:8000/api/motor/stop

# 2) IDLE 확인
curl -s http://localhost:8000/api/motor/status | jq '.data.state'

# 3) 그 다음 disable
curl -s -X POST http://localhost:8000/api/motor/disable
```

> ⚠ `/api/motor/disable` 은 **유지보수/티칭용**입니다. 안전 정지가 필요하면
> `/api/motor/estop` 을 사용하세요. 이 엔드포인트는 하드웨어 E-STOP
> (이중 경로: SW GPIO ISR + HW DRV_ENN) 을 트리거합니다.

### 4.3 모터가 움직이지 않음 (상태는 RUNNING)
**진단**:
```bash
# TMC DRV_STATUS 확인
curl http://localhost:8000/api/motor/status | jq '.data.axes'
```
- `drv_status != 0` → 드라이버 폴트 (overtemp, short, open-load)
- `cs_actual == 0` → 전류 설정이 0
- `sg_result` 극단값 → StallGuard2 임계값 오설정

**해결**:
```bash
curl -X POST http://localhost:8000/api/motor/reset -d '{"axis_mask": 0}'
```
그래도 안 되면 12V VMot 전원 / 모터 배선 / TMC SPI 연결 확인.

### 4.3 홈잉이 무한 반복
**원인**: StallGuard2 임계값이 너무 민감하거나 둔감함.

**해결**: `src/shared/machine_config.h` 의 `SGT` 값 조정 (보통 -64 ~ +63).
홈잉 캘리브레이션 절차는 `docs/PORTING.md` 참고.

---

## 5. 네트워크 / 프론트엔드

### 5.1 `CORS error` 브라우저 콘솔
**원인**: 백엔드가 프론트엔드 origin 을 허용하지 않음.

**해결**:
```bash
OB_CORS_ORIGINS="http://localhost:5173,http://192.168.1.100:5173" \
  python3 -m uvicorn server.main:app
```

또는 Vite dev proxy 사용:
```ts
// vite.config.ts
proxy: { "/api": { target: "http://192.168.77.2:8000" } }
```

### 5.2 Vite 프록시가 옛 target 으로 요청
**원인**: Vite HMR 캐시가 stale.

**해결**:
```bash
pkill -f vite
rm -rf node_modules/.vite
npm run dev
```

### 5.3 EVK IP 를 모름
```bash
# Host 에서 USB-Ethernet
ip addr show | grep -A2 usb
# EVK 기본 static: 192.168.77.2

# 또는 시리얼로 EVK 접속 후
ip addr show
```

---

## 6. 빌드 / Yocto 문제

### 6.1 `bitbake: command not found`
**해결**: KAS 환경 진입 필요
```bash
KAS_BUILD_DIR=build-ortho-bender kas shell kas/base.yml:kas/ortho-bender-dev.yml
```

### 6.2 `do_compile` 커널 실패
**진단**: `bitbake -c log_tail linux-imx` 또는 `tmp/work/.../temp/log.do_compile`

### 6.3 M7 firmware 빌드 실패
```bash
cmake -B build-firmware -S src/firmware \
  -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake
cmake --build build-firmware -v
```
- toolchain 경로 (`arm-none-eabi-gcc`) 확인
- MCUXpresso SDK 경로 환경변수 확인

---

## 7. Python 테스트 / 개발 환경

### 7.1 `pytest` 가 비동기 테스트 건너뜀
**해결**:
```bash
pip install pytest-asyncio
```
`pytest.ini`:
```ini
[pytest]
asyncio_mode = auto
```

### 7.2 `httpx.TimeoutException`
**원인**: 기본 timeout (5 초) 이 벤딩 시퀀스 완료 대기에 부족.

**해결**: execute API 는 **즉시 반환**됩니다 — timeout 이 나면 시퀀스가 완료될 때까지
대기하는 코드가 잘못된 것. `/status` 폴링 패턴 사용:
```python
client = httpx.Client(base_url="...", timeout=30.0)
client.post("/api/bending/execute", ...)      # 즉시 반환
while client.get("/api/bending/status").json()["data"]["running"]:
    time.sleep(0.1)
```

---

## 8. 로그에서 자주 보이는 경고

### `OpenCV not available — camera will return synthetic frames`
**의미**: OpenCV 없이 동작 중. VmbPy 로 가져온 raw ndarray 를 JPEG 인코딩 못함 → mock 프레임 반환.

**해결**:
```bash
pip3 install opencv-python-headless
```

### `tar: timestamp ... is N seconds in the future`
**의미**: EVK 클럭이 호스트 PC 보다 뒤짐.

**영향**: 무시해도 됨. 파일은 정상 전송됨.

**해결**:
```bash
# EVK 에서
date -s "$(ssh host 'date -u +"%Y-%m-%d %H:%M:%S"')"
```

---

## 9. 긴급 복구

완전히 꼬였을 때:

```bash
# 1) EVK 에서 모든 것 중단
pkill -f python3
pkill -f uvicorn
echo stop > /sys/class/remoteproc/remoteproc0/state

# 2) 깨끗하게 다시 시작
echo start > /sys/class/remoteproc/remoteproc0/state
sleep 1
cd /opt/ortho-bender
OB_MOCK_MODE=false GENICAM_GENTL64_PATH=/opt/VimbaX_2026-1/cti \
  nohup setsid python3 -m uvicorn server.main:app --host 0.0.0.0 --port 8000 \
    > /tmp/ortho-backend.log 2>&1 < /dev/null &
disown

# 3) Health 확인
sleep 10
curl http://localhost:8000/health
curl http://localhost:8000/api/system/status
```

그래도 안 되면 재부팅:
```bash
reboot
```

---

## 10. 이슈 리포트 가이드

해결되지 않는 문제는 GitHub Issue 로 등록해주세요. 다음 정보를 포함하세요:

1. **환경**: `OB_MOCK_MODE`, Python 버전, 백엔드 실행 위치
2. **재현 스텝**: 정확한 curl / 코드
3. **기대 결과 vs 실제 결과**
4. **로그**:
   - `/tmp/ortho-backend.log` 마지막 50줄
   - `dmesg | tail -30`
   - (해당 시) M7 시리얼 출력
5. **`curl http://localhost:8000/api/system/status` 결과**
6. **Git commit hash**: `git rev-parse HEAD`

---

## 관련 문서

- [DEPLOYMENT.md](04_DEPLOYMENT.md) — 배포 절차
- [MOCK_MODE.md](03_MOCK_MODE.md) — 하드웨어 없이 개발
- [SDK_GUIDE.md](01_SDK_GUIDE.md) — 메인 사용 가이드
- [API_REFERENCE.md](02_API_REFERENCE.md) — 에러 코드 카탈로그
