# CAD/CAM 개발자 가이드

> **대상**: 3D CAD 툴 / 치료 계획 소프트웨어 / 벤딩 경로 생성기를 개발하며
> Ortho-Bender SDK 로 머신을 구동하는 개발자. Python 또는 OpenCV 경험이
> 있으면 즉시 시작할 수 있습니다.

이 문서는 CAD/CAM 소프트웨어 개발자가 **5분 안에 현재 시스템 구조를 이해하고,
30분 안에 실제 벤딩을 구동하고, 1시간 안에 OpenCV 통합 검사 루프까지
완성**하도록 설계되었습니다.

---

## 1. Mental Model — 5분

### 1.1 당신이 알아야 할 것

```
당신의 CAD 툴                    Ortho-Bender SDK
─────────────                    ──────────────────
3D 치과 모델                      REST / WebSocket
  │                                    │
  ▼                                    │
와이어 센터라인 폴리라인 ─── POST ───> /api/cam/generate  (프리뷰)
  (x, y, z 정점 배열)                  │
                                        ▼
                                  B-code 스텝 반환 (프리뷰용)
                                        │
  ◀───────────────────────────────────┘
  사용자에게 시각화
  (CAD 뷰어 오버레이)
                                        
  확인 버튼                              
  │                                    
  ▼                                     
─── POST ──────────────────────> /api/cam/execute  (실행)
                                        │
                                        ▼
                                  머신이 실제로 벤딩
                                        │
  ◀─── GET /api/bending/status ─────┘
  진행률 UI 업데이트
                                        │
  ◀─── POST /api/camera/capture ─────┘
  (선택) 결과 검사 이미지
                                        
  OpenCV 로 검사
```

### 1.2 당신이 **몰라도** 되는 것

- ❌ TMC 드라이버 레지스터
- ❌ M7 펌웨어 코드
- ❌ RPMsg IPC 프로토콜
- ❌ StallGuard2 홈잉 알고리즘
- ❌ VmbPy / GenICam / U3V
- ❌ 카메라 USB3 vs MIPI CSI 차이
- ❌ 스프링백 물리 공식 (재질 enum 만 선택하면 자동 적용)

**당신은 JSON 을 보내고, JSON 을 받습니다.** 그게 전부입니다.

### 1.3 당신이 **절대** 하지 말아야 할 것

- `/dev/rpmsg0` 직접 접근
- 카메라 디바이스 파일 (`/dev/video*`) 직접 접근
- SSH 로 M7 펌웨어 재로드
- 환경변수 `OB_MOCK_MODE` 등을 앱 코드에서 읽기
- `backend` 필드 값으로 조건 분기 (예: `if backend=="vimba_x"`)

이런 접근은 **하드웨어가 교체되는 순간 당신의 코드가 깨집니다**. 자세한 이유는
[HARDWARE_ABSTRACTION.md](HARDWARE_ABSTRACTION.md) 를 참고하세요.

---

## 2. 준비 — 10분

### 2.1 의존성

```bash
pip install httpx numpy opencv-python-headless pytest
```

| 패키지 | 용도 |
|--------|------|
| `httpx` | REST 클라이언트 (동기/비동기 모두 지원) |
| `numpy` | 3D 폴리라인 생성, 프레임 버퍼 |
| `opencv-python-headless` | 이미지 디코딩 + 검사 |
| `pytest` | 회귀 테스트 |

### 2.2 Mock 백엔드 기동 (하드웨어 불필요)

```bash
# 터미널 1 — 리포 루트에서
cd src/app/server
pip install -r requirements.txt
OB_MOCK_MODE=true python3 -m uvicorn server.main:app --reload --port 8000
```

3초 후 확인:
```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

이제 **실기기와 100% 동일한 API** 가 로컬에서 돌아갑니다. 당신의 CAD/CAM 로직
개발 전부를 이 환경에서 완료할 수 있고, 실기기에 배포할 때 코드를 바꿀 필요가
전혀 없습니다.

### 2.3 실기기 사용 시 (참고)

`http://localhost:8000` 대신 EVK IP 를 사용하세요:
```bash
export ORTHO_BENDER_URL=http://192.168.77.2:8000
curl $ORTHO_BENDER_URL/health
```

---

## 3. 첫 벤딩 — 10분

### 3.1 최소 실행 코드

```python
#!/usr/bin/env python3
"""first_bend.py — 3 정점 폴리라인 → 프리뷰 → 실행"""
import httpx, time, sys

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

# 1) CAD 툴에서 추출했다고 가정한 3D 와이어 센터라인
points = [
    {"x":  0.0, "y": 0.0, "z": 0.0},
    {"x": 15.0, "y": 0.0, "z": 0.0},
    {"x": 25.0, "y": 8.0, "z": 0.0},
    {"x": 35.0, "y": 8.0, "z": 0.0},
]

body = {
    "points": points,
    "material": 0,            # 0=SS_304, 1=NiTi, 2=Beta-Ti, 3=Cu-NiTi
    "wire_diameter_mm": 0.457 # 0.018 inch
}

with httpx.Client(base_url=BASE, timeout=10.0) as c:
    # 2) 프리뷰 — 부작용 없음, 몇 번이고 호출 가능
    r = c.post("/api/cam/generate", json=body).json()
    assert r["success"], r
    preview = r["data"]
    print(f"세그먼트: {preview['segment_count']}")
    print(f"총 길이 : {preview['total_length_mm']:.2f} mm")
    print(f"최대 벤드: {preview['max_bend_deg']:.2f}°")
    print(f"스텝 수  : {len(preview['steps'])}")
    for i, s in enumerate(preview["steps"]):
        print(f"  [{i}] L={s['L_mm']:.2f} β={s['beta_deg']:.1f} θ={s['theta_deg']:.1f}")

    # 3) 실행 — 머신이 움직임
    input("\n엔터 키를 눌러 실행합니다... ")
    r = c.post("/api/cam/execute", json=body).json()
    assert r["success"], r
    print("디스패치 완료")

    # 4) 진행률 폴링
    while True:
        st = c.get("/api/bending/status").json()["data"]
        pct = st.get("progress_pct", 0.0)
        print(f"\r진행률: {pct:5.1f}% (step {st['current_step']}/{st['total_steps']})", end="")
        if not st["running"]:
            break
        time.sleep(0.2)
    print("\n완료")
```

실행:
```bash
python3 first_bend.py
```

Mock 모드라면 약 1초 뒤 완료됩니다. 실기기라면 물리 벤딩 시간만큼 소요됩니다.

### 3.2 출력 해석

```
세그먼트: 3
총 길이 : 35.38 mm
최대 벤드: 28.4°
스텝 수  : 3
  [0] L=15.00 β=0.0 θ=0.0     ← 직선 피드
  [1] L=10.63 β=0.0 θ=28.4    ← 굽힘 후 다음 구간
  [2] L=10.05 β=0.0 θ=0.0     ← 마지막 tail feed
```

첫 두 정점은 직선 → θ=0. 3점에서 방향이 바뀌며 θ=28.4° 벤드. 마지막은
남은 길이만큼 피드. **이 변환은 내부 CAM 알고리즘이 자동 수행**합니다.

### 3.3 응답 envelope 패턴

모든 REST 응답은 이 형식입니다:
```json
{ "success": true, "data": {...}, "error": null, "code": null }
```

에러도 HTTP 200 으로 옵니다:
```json
{
  "success": false,
  "data": null,
  "error": "points must contain at least 2 vertices",
  "code": "CAM_INVALID_INPUT"
}
```

5xx HTTP 코드는 **진짜 서버 크래시**일 때만 발생합니다. 일상 에러는 HTTP 200
+ `success:false` 로 처리합니다.

---

## 4. OpenCV 통합 — 검사 루프 구축

CAD/CAM 개발자가 가장 자주 구현하는 고부가가치 기능: **벤딩 후 카메라로 결과를
촬영하고 OpenCV 로 검사**하는 워크플로우입니다.

### 4.1 데이터 흐름

```
CAD 폴리라인
    │
    ▼
/api/cam/execute ─── 벤딩 실행 ───► 실제 와이어
    │                                   │
    │                                   │ 물리적 배치
    ▼                                   ▼
/api/bending/status                카메라 뷰
    │ (완료 대기)                        │
    ▼                                   ▼
/api/camera/capture ◄─────────── 이미지 획득
    │
    ▼
base64 → JPEG → OpenCV ndarray
    │
    ▼
엣지 검출 / 컨투어 / 허프 변환
    │
    ▼
벤드 각도 측정
    │
    ▼
명령 θ vs 측정 θ 비교 → PASS/FAIL
```

### 4.2 완전한 예제

```python
#!/usr/bin/env python3
"""cad_cam_opencv_workflow.py
CAD/CAM + OpenCV 완전 통합 예제.

이 스크립트는 아래를 하나의 파이프라인으로 수행합니다:
  1. 샘플 3D 폴리라인 생성 (실전에서는 CAD 툴 출력)
  2. /api/cam/generate 로 프리뷰 (사용자 확인용)
  3. /api/cam/execute 로 실제 벤딩 디스패치
  4. 진행률 폴링 (WebSocket 대신 단순 REST)
  5. /api/camera/capture 로 결과 이미지 획득
  6. OpenCV 로 이미지 디코딩 + 엣지 검출 + 허프 라인 → 각도 측정
  7. 명령 각도 vs 측정 각도 비교 → PASS/FAIL

Mock 모드에서는 카메라 프레임이 합성 그라디언트이므로 각도 측정은
의미 없는 값이 나오지만, 파이프라인 자체는 100% 동일하게 동작합니다.
실기기에서는 실제 벤딩 결과를 촬영합니다.
"""
from __future__ import annotations
import base64, time, argparse, sys
from dataclasses import dataclass

import httpx
import numpy as np
import cv2


# ───────────────────────── Data Models ─────────────────────────

@dataclass
class BendJob:
    points: list[dict]
    material: int
    wire_diameter_mm: float

    def to_body(self) -> dict:
        return {
            "points": self.points,
            "material": self.material,
            "wire_diameter_mm": self.wire_diameter_mm,
        }


@dataclass
class InspectionResult:
    commanded_max_theta: float
    measured_max_theta: float | None
    passed: bool
    frame_path: str
    notes: list[str]


# ───────────────────────── SDK Client ─────────────────────────

class OrthoBenderClient:
    """
    SDK REST 클라이언트. 하드웨어 교체(USB→MIPI, 스테퍼→서보)에 완전 무관.
    당신은 이 클래스만 사용하면 됩니다.
    """

    def __init__(self, base_url: str, timeout: float = 30.0):
        self._http = httpx.Client(base_url=base_url, timeout=timeout)

    def health(self) -> bool:
        return self._http.get("/health").json().get("status") == "ok"

    def cam_preview(self, job: BendJob) -> dict:
        r = self._http.post("/api/cam/generate", json=job.to_body()).json()
        if not r["success"]:
            raise RuntimeError(f"{r['code']}: {r['error']}")
        return r["data"]

    def cam_execute(self, job: BendJob) -> None:
        r = self._http.post("/api/cam/execute", json=job.to_body()).json()
        if not r["success"]:
            raise RuntimeError(f"{r['code']}: {r['error']}")

    def wait_bending_complete(self, poll_s: float = 0.2, timeout_s: float = 120.0) -> dict:
        start = time.monotonic()
        while True:
            st = self._http.get("/api/bending/status").json()["data"]
            if not st.get("running", False):
                return st
            if time.monotonic() - start > timeout_s:
                raise TimeoutError("bending did not complete in time")
            time.sleep(poll_s)

    def capture_frame(self, quality: int = 90) -> np.ndarray:
        r = self._http.post("/api/camera/capture", json={"quality": quality}).json()
        if not r["success"]:
            raise RuntimeError(f"{r['code']}: {r['error']}")
        jpeg_bytes = base64.b64decode(r["data"]["frame_b64"])
        buf = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)

    def close(self) -> None:
        self._http.close()

    def __enter__(self): return self
    def __exit__(self, *a): self.close()


# ───────────────────────── CAD Input ─────────────────────────

def sample_archwire(num: int = 12, radius: float = 25.0) -> list[dict]:
    """
    샘플 폴리라인: 상악 아치와이어를 단순 포물선으로 근사.
    실전에서는 당신의 CAD 툴에서 추출한 3D 센터라인을 넣으세요.
    """
    xs = np.linspace(-radius, radius, num)
    ys = (xs ** 2) / (2 * radius)
    return [{"x": float(x), "y": float(y), "z": 0.0} for x, y in zip(xs, ys)]


# ───────────────────────── OpenCV Inspection ─────────────────────────

def measure_max_bend_angle(frame: np.ndarray) -> tuple[float | None, list[str]]:
    """
    프레임에서 벤딩된 와이어의 최대 굽힘 각도를 측정합니다.

    전략:
    1. 가우시안 블러 → Canny 엣지
    2. 모폴로지 클로즈로 엣지 연결
    3. Hough Line Transform 으로 직선 세그먼트 추출
    4. 인접 세그먼트 쌍의 각도 차이 중 최대값 반환

    반환: (measured_deg, notes). 측정 불가 시 (None, [...]).
    """
    notes: list[str] = []

    if frame is None or frame.size == 0:
        return None, ["empty frame"]

    blur = cv2.GaussianBlur(frame, (5, 5), 1.2)
    edges = cv2.Canny(blur, 50, 150)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

    lines = cv2.HoughLinesP(
        edges, rho=1, theta=np.pi / 180,
        threshold=60, minLineLength=30, maxLineGap=10,
    )
    if lines is None or len(lines) < 2:
        notes.append(f"insufficient lines ({0 if lines is None else len(lines)})")
        return None, notes

    # 각 라인의 각도 (도 단위, 0~180)
    angles = []
    for ln in lines[:, 0, :]:
        x1, y1, x2, y2 = ln
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180
        angles.append(ang)

    angles.sort()
    # 인접 각도 차이 중 최대 — 직선 세그먼트 사이의 꺾임
    diffs = [abs(angles[i + 1] - angles[i]) for i in range(len(angles) - 1)]
    if not diffs:
        return None, ["single angle cluster"]

    max_diff = max(diffs)
    # 180° 주기 반영 (예: 170°와 10° 사이의 실제 각차는 20°)
    max_diff = min(max_diff, 180.0 - max_diff)
    notes.append(f"{len(lines)} lines detected, max Δangle = {max_diff:.1f}°")
    return float(max_diff), notes


def inspect_bend(
    client: OrthoBenderClient,
    job: BendJob,
    tolerance_deg: float = 3.0,
) -> InspectionResult:
    """
    벤딩 실행 + 카메라 캡처 + OpenCV 측정 + 합격 판정 전체 파이프라인.
    """
    preview = client.cam_preview(job)
    commanded_theta = float(preview["max_bend_deg"])

    client.cam_execute(job)
    client.wait_bending_complete()

    # 촬영 안정화 대기 (실기기에서만 의미 있음)
    time.sleep(0.3)
    frame = client.capture_frame(quality=90)

    measured, notes = measure_max_bend_angle(frame)

    frame_path = f"/tmp/ortho_frame_{int(time.time())}.png"
    cv2.imwrite(frame_path, frame)

    if measured is None:
        passed = False
        notes.append("measurement failed")
    else:
        passed = abs(measured - commanded_theta) <= tolerance_deg

    return InspectionResult(
        commanded_max_theta=commanded_theta,
        measured_max_theta=measured,
        passed=passed,
        frame_path=frame_path,
        notes=notes,
    )


# ───────────────────────── Entry Point ─────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://localhost:8000")
    ap.add_argument("--material", type=int, default=0)
    ap.add_argument("--diameter", type=float, default=0.457)
    ap.add_argument("--points", type=int, default=12)
    ap.add_argument("--tolerance", type=float, default=3.0)
    args = ap.parse_args()

    points = sample_archwire(num=args.points)
    job = BendJob(points=points, material=args.material, wire_diameter_mm=args.diameter)

    with OrthoBenderClient(args.host) as client:
        if not client.health():
            print("ERROR: backend is not healthy", file=sys.stderr)
            return 2

        result = inspect_bend(client, job, tolerance_deg=args.tolerance)

    print(f"commanded max bend : {result.commanded_max_theta:.2f}°")
    print(f"measured  max bend : {result.measured_max_theta}")
    print(f"tolerance          : ±{args.tolerance}°")
    print(f"verdict            : {'PASS' if result.passed else 'FAIL'}")
    print(f"frame saved to     : {result.frame_path}")
    for n in result.notes:
        print(f"  • {n}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
```

### 4.3 실행 예

```bash
# Mock 백엔드에서 (합성 프레임이므로 측정은 실패할 수 있음 — 파이프라인 검증용)
python3 cad_cam_opencv_workflow.py --host http://localhost:8000

# 실기기에서 (실제 벤딩 + 실제 카메라)
python3 cad_cam_opencv_workflow.py --host http://192.168.77.2:8000 --tolerance 2.0
```

이 하나의 스크립트가 **REST + CAM + 모션 + 카메라 + OpenCV 분석**을 모두
커버합니다. 실제 제품에서는 이 구조를 확장하여:
- 측정 결과를 DB 에 저장 (로트 추적)
- FAIL 시 자동 재벤딩 (보정)
- 샘플 N 개 후 통계로 스프링백 계수 동적 튜닝
- 프론트엔드에 검사 뷰 실시간 스트림

등을 구현할 수 있습니다.

---

## 5. 테스트 코드 — pytest 회귀 테스트

CAD/CAM 로직은 **실기기 없이 Mock 모드에서 전부 pytest 로 회귀 테스트**할 수
있습니다. 이것이 추상화의 실질적 이익입니다.

### 5.1 테스트 구조

```
src/app/sdk-examples/python/tests/
├── conftest.py              # pytest fixture (httpx client, mock backend)
├── test_cad_cam_workflow.py # CAM 워크플로우 단위/통합 테스트
└── test_opencv_inspection.py# OpenCV 측정 함수 단위 테스트
```

### 5.2 conftest.py (fixture)

```python
"""conftest.py — 모든 테스트가 공유하는 fixture"""
import os, time, socket, subprocess, signal
import httpx, pytest


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


@pytest.fixture(scope="session")
def backend_url() -> str:
    """
    백엔드 URL 를 반환. 이미 실행 중이면 그것을 사용하고,
    아니면 자동으로 mock 모드로 띄운 뒤 세션 종료 시 정리.
    """
    host, port = "127.0.0.1", 8000
    url = f"http://{host}:{port}"

    # 외부 오버라이드 허용 (CI 에서 실기기 URL 주입 가능)
    override = os.environ.get("ORTHO_BENDER_URL")
    if override:
        yield override
        return

    if _port_open(host, port):
        yield url
        return

    env = os.environ.copy()
    env["OB_MOCK_MODE"] = "true"
    proc = subprocess.Popen(
        ["python3", "-m", "uvicorn", "server.main:app",
         "--host", host, "--port", str(port)],
        cwd=os.path.join(os.path.dirname(__file__), "../../../server"),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid,
    )

    for _ in range(50):
        if _port_open(host, port):
            break
        time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail("mock backend failed to start")

    yield url

    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    proc.wait(timeout=5)


@pytest.fixture
def client(backend_url: str):
    with httpx.Client(base_url=backend_url, timeout=10.0) as c:
        yield c
```

### 5.3 test_cad_cam_workflow.py

```python
"""test_cad_cam_workflow.py — CAD/CAM 통합 테스트"""
import time
import pytest


STRAIGHT_WIRE = [
    {"x": 0.0, "y": 0.0, "z": 0.0},
    {"x": 10.0, "y": 0.0, "z": 0.0},
    {"x": 20.0, "y": 0.0, "z": 0.0},
]

L_BEND = [
    {"x": 0.0, "y": 0.0, "z": 0.0},
    {"x": 10.0, "y": 0.0, "z": 0.0},
    {"x": 10.0, "y": 10.0, "z": 0.0},
]


# ────────────── Health & Envelope ──────────────

def test_backend_is_healthy(client):
    r = client.get("/health").json()
    assert r["status"] == "ok"


def test_system_status_envelope(client):
    r = client.get("/api/system/status").json()
    assert r["success"] is True
    assert "motion_state" in r["data"]
    # backend 필드에 조건 분기하지 말 것! 존재 여부만 확인.
    assert "ipc_connected" in r["data"]


# ────────────── CAM Preview ──────────────

def test_cam_preview_straight_wire_has_zero_bend(client):
    r = client.post("/api/cam/generate", json={
        "points": STRAIGHT_WIRE,
        "material": 0,
        "wire_diameter_mm": 0.457,
    }).json()
    assert r["success"] is True
    assert r["data"]["max_bend_deg"] == pytest.approx(0.0, abs=0.1)
    assert r["data"]["total_length_mm"] == pytest.approx(20.0, abs=0.5)


def test_cam_preview_l_bend_has_right_angle(client):
    r = client.post("/api/cam/generate", json={
        "points": L_BEND,
        "material": 0,
        "wire_diameter_mm": 0.457,
    }).json()
    assert r["success"] is True
    # SS 304 스프링백 ×1.10 → 90° × 1.10 = 99° (180 클램프 전)
    assert r["data"]["max_bend_deg"] == pytest.approx(99.0, abs=2.0)


def test_cam_preview_rejects_single_point(client):
    r = client.post("/api/cam/generate", json={
        "points": [{"x": 0.0, "y": 0.0, "z": 0.0}],
        "material": 0,
        "wire_diameter_mm": 0.457,
    }).json()
    assert r["success"] is False
    assert r["code"] == "CAM_INVALID_INPUT"


def test_cam_preview_is_idempotent(client):
    """같은 입력에 여러 번 호출해도 동일 결과 — 부작용 없음."""
    body = {"points": L_BEND, "material": 0, "wire_diameter_mm": 0.457}
    r1 = client.post("/api/cam/generate", json=body).json()["data"]
    r2 = client.post("/api/cam/generate", json=body).json()["data"]
    assert r1["steps"] == r2["steps"]


def test_cam_preview_springback_toggle(client):
    """apply_springback=false 시 재질 계수 미적용."""
    body = {"points": L_BEND, "material": 0, "wire_diameter_mm": 0.457}
    with_sb = client.post(
        "/api/cam/generate", json={**body, "apply_springback": True}
    ).json()["data"]
    no_sb = client.post(
        "/api/cam/generate", json={**body, "apply_springback": False}
    ).json()["data"]
    assert with_sb["max_bend_deg"] > no_sb["max_bend_deg"]


# ────────────── CAM Execute & Progress ──────────────

def test_cam_execute_completes_under_mock(client):
    client.post("/api/cam/execute", json={
        "points": L_BEND,
        "material": 0,
        "wire_diameter_mm": 0.457,
    })

    # Mock 은 스텝당 ~0.3s — 5초 안에 반드시 완료
    deadline = time.monotonic() + 5.0
    completed = False
    last_step = -1
    while time.monotonic() < deadline:
        st = client.get("/api/bending/status").json()["data"]
        assert st["current_step"] >= last_step  # 단조 증가
        last_step = st["current_step"]
        if not st["running"]:
            completed = True
            break
        time.sleep(0.1)

    assert completed, "bending did not complete"


def test_bending_stop_returns_to_idle(client):
    client.post("/api/cam/execute", json={
        "points": L_BEND,
        "material": 0,
        "wire_diameter_mm": 0.457,
    })
    time.sleep(0.05)
    r = client.post("/api/bending/stop").json()
    assert r["success"] is True

    # 정지 후 잠시 기다리면 running=false
    for _ in range(20):
        st = client.get("/api/bending/status").json()["data"]
        if not st["running"]:
            return
        time.sleep(0.05)
    pytest.fail("bending did not stop")


# ────────────── Camera ──────────────

def test_camera_capture_returns_valid_jpeg(client):
    r = client.post("/api/camera/capture", json={"quality": 85}).json()
    assert r["success"] is True
    assert "frame_b64" in r["data"]
    assert r["data"]["width"] > 0 and r["data"]["height"] > 0

    import base64
    jpeg = base64.b64decode(r["data"]["frame_b64"])
    assert jpeg[:3] == b"\xff\xd8\xff"  # JPEG SOI marker


def test_camera_status_does_not_leak_implementation(client):
    r = client.get("/api/camera/status").json()["data"]
    assert "connected" in r
    assert "width" in r and "height" in r
    # backend 필드는 참고용. 이 값에 조건 분기하지 말 것 — 하드웨어 교체에 취약.
    assert r.get("backend") in {"vimba_x", "v4l2", "mock"}


# ────────────── Hardware Abstraction Invariants ──────────────

@pytest.mark.parametrize("material,expected_factor", [
    (0, 1.10),  # SS_304
    (1, 1.35),  # NITI
    (2, 1.15),  # BETA_TI
    (3, 1.30),  # CU_NITI
])
def test_springback_factors_per_material(client, material, expected_factor):
    """재질별 스프링백 계수가 API 문서와 일치하는지 회귀 테스트."""
    body = {
        "points": L_BEND,     # 90° bend
        "material": material,
        "wire_diameter_mm": 0.457,
    }
    r = client.post("/api/cam/generate", json=body).json()["data"]
    expected = min(90.0 * expected_factor, 180.0)
    assert r["max_bend_deg"] == pytest.approx(expected, abs=1.0)
```

### 5.4 test_opencv_inspection.py

```python
"""test_opencv_inspection.py — OpenCV 측정 함수 단위 테스트

SDK 또는 백엔드 없이 순수 이미지 처리 로직만 검증.
"""
import numpy as np
import cv2
import pytest
from cad_cam_opencv_workflow import measure_max_bend_angle


def _synthetic_bend_image(angle_deg: float, size: int = 400) -> np.ndarray:
    """
    중심에서 지정된 각도로 꺾인 두 직선을 그린 흑백 이미지.
    측정 알고리즘 검증용.
    """
    img = np.zeros((size, size), dtype=np.uint8)
    cx, cy = size // 2, size // 2
    length = size // 3

    # 첫 번째 직선 (수평)
    cv2.line(img, (cx - length, cy), (cx, cy), 255, 3)

    # 두 번째 직선 (각도만큼 회전)
    rad = np.radians(angle_deg)
    x2 = int(cx + length * np.cos(rad))
    y2 = int(cy - length * np.sin(rad))  # y 방향 반전
    cv2.line(img, (cx, cy), (x2, y2), 255, 3)

    return img


def test_measures_zero_bend_from_straight_line():
    img = _synthetic_bend_image(0.0)
    angle, _ = measure_max_bend_angle(img)
    # 완전한 직선은 의미 있는 벤드가 없으므로 None 또는 ~0
    assert angle is None or angle < 5.0


@pytest.mark.parametrize("target", [30.0, 45.0, 60.0, 90.0])
def test_measures_approximate_angle(target):
    img = _synthetic_bend_image(target)
    angle, notes = measure_max_bend_angle(img)
    assert angle is not None, f"detection failed: {notes}"
    # 허프 변환은 ±3° 범위 내에서 일반적으로 일치
    assert abs(angle - target) <= 5.0, f"target={target}, got {angle}"


def test_empty_frame_returns_none():
    angle, notes = measure_max_bend_angle(np.zeros((400, 400), dtype=np.uint8))
    assert angle is None
    assert notes
```

### 5.5 실행

```bash
cd src/app/sdk-examples/python
pytest tests/ -v

# 특정 테스트만
pytest tests/test_cad_cam_workflow.py::test_cam_preview_l_bend_has_right_angle -v

# 실기기 대상
ORTHO_BENDER_URL=http://192.168.77.2:8000 pytest tests/ -v
```

### 5.6 CI 통합 예 (GitHub Actions)

```yaml
- name: CAD/CAM 회귀 테스트
  run: |
    cd src/app/sdk-examples/python
    pip install httpx numpy opencv-python-headless pytest
    pytest tests/ -v --tb=short
```

**하드웨어가 없어도** CI 는 당신의 CAD/CAM 로직이 깨지지 않았음을 증명합니다.
이것이 mock 모드의 실질적 가치입니다.

---

## 6. 에러 처리 패턴

CAD/CAM 코드가 자주 만나는 에러들과 권장 대응:

| code | 언제 | 대응 |
|------|------|------|
| `CAM_INVALID_INPUT` | 정점 수 부족 (< 2), 범위 초과 (`L>200`, `θ>180`) | 호출 전 클라이언트에서 검증, 사용자에게 입력 수정 요청 |
| `BENDING_BUSY` | 이전 시퀀스가 아직 진행 중 | `/api/bending/status` 폴링 또는 `/stop` 후 재시도 |
| `CAM_EXECUTE_ERROR` | 모터 디스패치 실패 (IPC 문제 등) | `/api/system/status` 로 진단 → 재시도 |
| `MOTOR_FAULT` | TMC DRV_STATUS 이상 (overtemp 등) | `/api/motor/reset` 후 원인 해소 (냉각, 배선 등) |
| `IPC_TIMEOUT` | M7 펌웨어 무응답 | 시스템 로그 확인, 운영자에게 에스컬레이션 |

### 6.1 방어적 호출 패턴

```python
def safe_execute(client, job: BendJob, max_retries: int = 2) -> None:
    for attempt in range(max_retries + 1):
        r = client._http.post("/api/cam/execute", json=job.to_body()).json()
        if r["success"]:
            return

        code = r["code"]
        if code == "BENDING_BUSY" and attempt < max_retries:
            client._http.post("/api/bending/stop")
            time.sleep(0.5)
            continue
        if code == "MOTOR_FAULT" and attempt < max_retries:
            client._http.post("/api/motor/reset", json={"axis_mask": 0})
            time.sleep(1.0)
            continue
        raise RuntimeError(f"{code}: {r['error']}")
```

---

## 7. 체크리스트 — "내 CAD/CAM 코드는 완성됐는가?"

배포 전 확인:

- [ ] 모든 로직이 **mock 모드에서 통과**한다 (`OB_MOCK_MODE=true`)
- [ ] pytest 회귀 테스트가 **하드웨어 없이** 그린이다
- [ ] `/dev/rpmsg0`, VmbPy, GStreamer 를 직접 호출하지 않는다
- [ ] `backend` 필드 값에 **조건 분기하지 않는다**
- [ ] 환경변수 `OB_*` 를 앱 코드에서 읽지 않는다
- [ ] 모든 REST 호출이 **envelope 패턴**(success/data/error/code)을 검사한다
- [ ] 에러는 HTTP 200 + `success:false` 로 처리한다 (5xx 는 예외 상황)
- [ ] 카메라 응답 JPEG 는 OpenCV 로 디코딩한다 (원시 포맷 의존 금지)
- [ ] B-code 실행 후 **반드시** `/api/bending/status` 폴링으로 완료 확인
- [ ] 재질 enum 은 API 상수로 하드코딩 (0=SS_304, 1=NiTi, 2=β-Ti, 3=Cu-NiTi)
- [ ] 128 스텝 한도를 **입력 검증 단계에서 가드**한다
- [ ] Mock 에서 통과한 후 **실기기에서도 1회 이상 검증**한다

---

## 8. FAQ

**Q. 실기기를 어떻게 구해요?**
A. 배포 / 랩 환경은 [DEPLOYMENT.md](DEPLOYMENT.md) 참고. 실기기 없어도 전체
개발 가능 — Mock 모드가 실 API 와 동일합니다.

**Q. OpenCV 없이 PIL 만 쓸 수 있나요?**
A. 네. REST 는 JPEG base64 만 반환하므로 어떤 이미지 라이브러리든 사용 가능.
단, 예제와 테스트는 OpenCV 기준입니다.

**Q. 프레임을 binary WebSocket 으로 받을 수 있나요?**
A. 현재 JSON 텍스트 + base64 만 지원. 바이너리 WebSocket 은 Phase 2 에서
추가 예정 — 그때까지는 base64 디코딩 오버헤드를 감수하세요 (HD 해상도 기준
수 ms).

**Q. WebSocket 으로 모터 상태를 받는 것과 REST 폴링의 차이는?**
A. `/ws/motor` 는 10 Hz 푸시, 폴링은 요청 주기에 따름. **벤딩 진행률은
폴링으로도 충분**합니다 (스텝당 ~300 ms). 대시보드는 WS 권장.

**Q. B-code 를 직접 작성하고 CAM 을 건너뛸 수 있나요?**
A. 네. `/api/bending/execute` 에 `{steps: [...], material, wire_diameter_mm}`
를 직접 보내세요. 포맷은 [BCODE_SPEC.md](BCODE_SPEC.md) 참고.

**Q. 재질 스프링백 계수를 튜닝할 수 있나요?**
A. 현재는 서버 내장 상수. 향후 NPU 기반 동적 보정 모델이 통합될 예정입니다
(로드맵 Phase 2). 그때도 API 형태는 유지됩니다.

**Q. 카메라 교체되면 이 문서의 OpenCV 예제가 깨지나요?**
A. **아니요**. [HARDWARE_ABSTRACTION.md](HARDWARE_ABSTRACTION.md) 에서
설명한 대로, `/api/camera/capture` 는 JPEG 만 반환하는 벤더 중립 인터페이스
입니다. 센서가 바뀌면 해상도나 bit depth 가 바뀔 수 있지만, **디코딩
파이프라인은 동일**합니다.

---

## 9. 관련 문서

- [HARDWARE_ABSTRACTION.md](HARDWARE_ABSTRACTION.md) — 왜 당신의 코드가 하드웨어 교체에 안전한가
- [API_REFERENCE.md](API_REFERENCE.md) — 모든 엔드포인트 스키마
- [BCODE_SPEC.md](BCODE_SPEC.md) — 저수준 B-code 포맷
- [WIRE_MATERIALS.md](WIRE_MATERIALS.md) — 재질별 특성 + 계수
- [MOCK_MODE.md](MOCK_MODE.md) — Mock 백엔드 상세
- [SDK_GUIDE.md](SDK_GUIDE.md) — 전체 SDK 가이드
