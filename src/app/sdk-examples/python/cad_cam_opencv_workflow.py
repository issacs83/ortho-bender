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
import base64
import time
import argparse
import sys
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

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


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

    angles = []
    for ln in lines[:, 0, :]:
        x1, y1, x2, y2 = ln
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180
        angles.append(ang)

    angles.sort()
    diffs = [abs(angles[i + 1] - angles[i]) for i in range(len(angles) - 1)]
    if not diffs:
        return None, ["single angle cluster"]

    max_diff = max(diffs)
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
