# Deployment Guide

Ortho-Bender SDK 백엔드를 i.MX8MP EVK / 실기기에 배포하고 운영하는 방법.

---

## 1. 대상 환경

| 항목 | 개발 | 실기기 |
|------|------|--------|
| 보드 | 로컬 PC | NXP i.MX8MP EVK |
| OS | Linux / macOS | Yocto (ortho-bender-image-dev) |
| Python | 3.11+ | 3.10 (Yocto 기본) |
| 카메라 | mock | Allied Vision 1800 U-158m (USB3) |
| M7 펌웨어 | mock | `/lib/firmware/ortho-bender-m7.elf` |
| 기동 | `uvicorn --reload` | systemd 서비스 |

---

## 2. 네트워크

기본 구성:
- **EVK IP**: `192.168.77.2` (enet0, 정적)
- **호스트 PC**: `192.168.77.1` (USB-Ethernet via FT4232H)
- **백엔드 포트**: `8000` (0.0.0.0 바인딩)
- **프론트엔드 dev**: `5173` (Vite, Jetson 등 별도 머신)

프론트엔드 Vite 프록시 설정:
```ts
// src/app/frontend/vite.config.ts
proxy: {
  "/api": { target: "http://192.168.77.2:8000", changeOrigin: true },
  "/ws":  { target: "ws://192.168.77.2:8000",  ws: true },
}
```

WiFi 연결 시 환경변수로 오버라이드:
```bash
VITE_BACKEND_URL=http://192.168.1.50:8000 npm run dev
```

---

## 3. 배포

### 3.1 최초 설치 (EVK)

1. **Yocto 이미지 플래싱**
   ```bash
   KAS_BUILD_DIR=build-ortho-bender kas shell kas/base.yml:kas/ortho-bender-dev.yml \
     -c "bitbake ortho-bender-image-dev"
   sudo uuu -b emmc_all imx-boot ortho-bender-image-dev.wic
   ```

2. **VmbPy + Vimba X 설치** (이미지에 포함됨)
   - 경로: `/opt/VimbaX_2026-1/`
   - Genicam CTI: `/opt/VimbaX_2026-1/cti/VimbaUSBTL.cti`

3. **Python 의존성**
   ```bash
   cd /opt/ortho-bender
   pip3 install -r server/requirements.txt
   ```

### 3.2 소스 업데이트 (개발 중)

호스트에서 EVK 로 코드 동기화:
```bash
# 단발성 전체 동기화
rsync -avz --exclude=node_modules --exclude=__pycache__ \
  src/app/server/ root@192.168.77.2:/opt/ortho-bender/server/

# 단일 파일 빠른 덮어쓰기 (tar pipe)
tar cz -C src/app/server services/cam_service.py \
  | ssh root@192.168.77.2 "cd /opt/ortho-bender && tar xz -C server"
```

### 3.3 백엔드 기동

**수동 기동 (개발/디버그)**
```bash
ssh root@192.168.77.2
cd /opt/ortho-bender
OB_MOCK_MODE=false \
  GENICAM_GENTL64_PATH=/opt/VimbaX_2026-1/cti \
  python3 -m uvicorn server.main:app --host 0.0.0.0 --port 8000
```

**백그라운드 (SSH 세션 닫아도 유지)**
```bash
cd /opt/ortho-bender && rm -f /tmp/ortho-backend.log && \
  OB_MOCK_MODE=false GENICAM_GENTL64_PATH=/opt/VimbaX_2026-1/cti \
  nohup setsid python3 -m uvicorn server.main:app \
    --host 0.0.0.0 --port 8000 \
    > /tmp/ortho-backend.log 2>&1 < /dev/null &
disown
```

**systemd (production)**
```ini
# /etc/systemd/system/ortho-bender-sdk.service
[Unit]
Description=Ortho-Bender SDK Backend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ortho-bender
Environment="OB_MOCK_MODE=false"
Environment="OB_MOTOR_BACKEND=spidev"
Environment="GENICAM_GENTL64_PATH=/opt/VimbaX_2026-1/cti"
ExecStart=/usr/bin/python3 -m uvicorn server.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> **백엔드 모드 선택**: `OB_MOTOR_BACKEND` 에 따라 진단 서비스의 하드웨어 접근 방식이 결정됩니다:
> - `mock` — 하드웨어 없이 개발 (기본값)
> - `spidev` — Linux spidev + gpiod 직접 SPI/GPIO 접근 (테스트 벤치용)
> - `m7` — M7 RPMsg IPC 경유 (프로덕션)

### 3.4 spidev 백엔드 추가 패키지 (EVK 테스트 벤치)

spidev 모드를 사용하려면 EVK에 다음 Python 패키지가 필요합니다:
```bash
pip3 install spidev gpiod
```
- `spidev` >= 3.6 — Linux spidev 인터페이스
- `gpiod` >= 2.0 — gpiod v2 API (libgpiod 2.x 필요)

패키지가 설치되지 않은 상태에서 `OB_MOTOR_BACKEND=spidev` 로 기동하면
`ImportError` 와 함께 서비스가 중단됩니다.

EVK에 인터넷 연결이 없는 경우, 동일 아키텍처(aarch64) 호스트에서 wheel 을
빌드하여 전송하세요:
```bash
# 호스트에서
pip3 wheel spidev gpiod -w /tmp/wheels
scp /tmp/wheels/*.whl root@192.168.77.2:/tmp/

# EVK에서
pip3 install /tmp/spidev-*.whl /tmp/gpiod-*.whl
```

```bash
systemctl daemon-reload
systemctl enable --now ortho-bender
systemctl status ortho-bender
```

---

## 4. 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `OB_MOCK_MODE` | `false` | `true` 시 IPC + 카메라 모두 mock |
| `OB_IPC_DEVICE` | `/dev/rpmsg0` | M7 RPMsg 디바이스 |
| `OB_IPC_TIMEOUT_S` | `2.0` | IPC 요청 타임아웃 |
| `OB_MOTOR_BACKEND` | `mock` | 모터 백엔드: `mock` / `spidev` / `m7` |
| `OB_SPI_DEVICE` | `/dev/spidev1.0` | SPI 디바이스 경로 (spidev 모드) |
| `OB_SPI_SPEED_HZ` | `2000000` | SPI 클럭 속도 (spidev 모드) |
| `OB_GPIO_CS1` | `GPIO3_IO19` | TMC260C #2 soft CS (spidev 모드) |
| `OB_GPIO_CS2` | `GPIO3_IO20` | TMC5072 soft CS (spidev 모드) |
| `OB_GPIO_FEED_STEP` | `GPIO3_IO22` | Feed axis STEP (spidev 모드) |
| `OB_GPIO_BEND_STEP` | `GPIO3_IO24` | Bend axis STEP (spidev 모드) |
| `OB_GPIO_DIR` | `GPIO5_IO06` | 공유 DIR (spidev 모드) |
| `OB_PORT` | `8000` | HTTP 포트 |
| `OB_HOST` | `0.0.0.0` | 바인딩 주소 |
| `OB_LOG_LEVEL` | `info` | `debug/info/warning/error` |
| `OB_CORS_ORIGINS` | `*` | 쉼표로 구분된 허용 origin |
| `OB_CAMERA_JPEG_QUALITY` | `85` | WebSocket 프레임 JPEG 품질 |
| `GENICAM_GENTL64_PATH` | — | VmbPy CTI 경로 (카메라 사용 시 필수) |

---

## 5. M7 펌웨어 로드

A53 백엔드가 기동하기 전에 M7 firmware 가 동작하고 있어야 합니다.

```bash
echo "ortho-bender-m7.elf" > /sys/class/remoteproc/remoteproc0/firmware
echo start > /sys/class/remoteproc/remoteproc0/state
ls /dev/rpmsg*        # /dev/rpmsg_ctrl0, /dev/rpmsg0 확인
```

U-Boot 에서 자동 로드 설정 (기본 이미지에 포함):
```
setenv bootargs ${bootargs} rproc_auto_boot
saveenv
```

펌웨어 부재 시 백엔드는 **자동으로 mock IPC 로 폴백**합니다 (로그: `IPC connect failed ... falling back to mock motor`).

---

## 6. 로그 / 모니터링

### 6.1 로그 위치
- **수동 기동**: `/tmp/ortho-backend.log`
- **systemd**: `journalctl -u ortho-bender -f`
- **M7 시리얼**: `/dev/ttyLP5` 또는 J5 디버그 포트 (115200)

### 6.2 주요 로그 이벤트
```
Starting Ortho-Bender SDK (mock=False)
IpcClient: connected to /dev/rpmsg0
VmbPy: selected camera Allied Vision 1800 U-158m
CameraService: opened via VmbPy (Vimba X USB3 Vision)
Ortho-Bender SDK ready on :8000
Bending execute: 4 steps, material=SS_304, wire=0.457 mm, springback=1.10
Bending sequence completed (4 steps)
```

### 6.3 시스템 메트릭
```bash
# CPU / 메모리
top -p $(pidof python3)

# 네트워크 트래픽
iftop -i eth0

# 온도
cat /sys/class/thermal/thermal_zone0/temp

# M7 상태
cat /sys/class/remoteproc/remoteproc0/state
```

---

## 7. 업그레이드 절차

1. **변경사항 푸시** (호스트)
   ```bash
   git pull origin main
   ```
2. **EVK 로 동기화**
   ```bash
   rsync -avz src/app/server/ root@192.168.77.2:/opt/ortho-bender/server/
   ```
3. **백엔드 재기동**
   ```bash
   ssh root@192.168.77.2 'pkill -f server.main; sleep 2; cd /opt/ortho-bender && ... (위의 기동 명령)'
   ```
4. **Health check**
   ```bash
   curl http://192.168.77.2:8000/health
   curl http://192.168.77.2:8000/api/system/status
   ```
5. **로그 확인 → 문제 시 이전 버전 rollback**

---

## 8. Roll-back

현재는 수동:
```bash
git checkout <previous-commit>
rsync -avz src/app/server/ root@192.168.77.2:/opt/ortho-bender/server/
# 재기동
```

향후 계획: A/B 파티션 + OTA (Phase 2). 자세한 내용은 `docs/ROADMAP.md`.

---

## 9. 보안 체크리스트 (프로덕션 배포 전)

- [ ] Root 패스워드 변경 (기본 `"root"` 금지)
- [ ] SSH key 기반 로그인 + 비밀번호 인증 비활성화
- [ ] `debug-tweaks` 이미지 feature 제거
- [ ] 시리얼 콘솔 root login 비활성화
- [ ] JTAG 포트 물리적 봉인
- [ ] `OB_CORS_ORIGINS` 특정 도메인으로 제한
- [ ] 방화벽: 포트 8000 을 내부 네트워크로만 제한 (또는 nginx reverse proxy)
- [ ] API 토큰 인증 추가 (향후)

---

## 10. 관련 문서

- [MOCK_MODE.md](03_MOCK_MODE.md) — 하드웨어 없이 개발 + 3-mode 백엔드
- [TROUBLESHOOTING.md](05_TROUBLESHOOTING.md) — 배포 중 자주 발생하는 문제
- [bootflow.md](../architecture/03_BOOTFLOW.md) — 부팅 시퀀스 상세
- [evk-remoteproc-analysis.md](../hardware/02_EVK_REMOTEPROC.md) — M7 remoteproc 내부
- [TEST_BENCH_CONNECTION.md](../hardware/04_TEST_BENCH_CONNECTION.md) — DRI0035 + TMC5072 하드웨어 연결 가이드
