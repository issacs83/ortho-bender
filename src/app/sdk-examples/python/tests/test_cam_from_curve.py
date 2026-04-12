"""test_cam_from_curve.py — cam_from_curve.py 예제 검증.

sample_arch_curve() 가 생성하는 포물선 아치가 CAM preview 에서
유의미한 bend 각도를 만들어내는지, 그리고 --execute 로 실제 벤딩까지
디스패치되는지를 확인합니다.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

import cam_from_curve


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.abspath(os.path.join(HERE, "..", "cam_from_curve.py"))


# ────────────── sample_arch_curve ──────────────

def test_sample_arch_curve_default_length():
    pts = cam_from_curve.sample_arch_curve()
    assert len(pts) == 12
    assert pts[0]["x"] == 0.0
    assert pts[-1]["x"] == 40.0


def test_sample_arch_curve_apex_is_nonzero():
    pts = cam_from_curve.sample_arch_curve(n=21)
    ys = [p["y"] for p in pts]
    mid = ys[len(ys) // 2]
    assert mid == pytest.approx(4.0, abs=0.2)
    assert ys[0] == pytest.approx(0.0, abs=1e-6)
    assert ys[-1] == pytest.approx(0.0, abs=1e-6)


def test_sample_arch_curve_points_are_well_formed():
    pts = cam_from_curve.sample_arch_curve(n=5)
    for p in pts:
        assert set(p.keys()) == {"x", "y", "z"}
        assert all(isinstance(v, float) for v in p.values())


# ────────────── CAM preview on the sample curve ──────────────

def test_preview_arch_curve_has_nonzero_bend(client):
    points = cam_from_curve.sample_arch_curve()
    preview = cam_from_curve.check(
        client.post("/api/cam/generate", json={
            "points": points,
            "material": 0,
            "wire_diameter_mm": 0.457,
            "min_segment_mm": 1.0,
            "apply_springback": True,
        }).json()
    )
    assert preview["segment_count"] >= 1
    assert preview["total_length_mm"] > 40.0  # arch length > chord
    assert preview["max_bend_deg"] > 0.0
    for s in preview["steps"]:
        assert {"L_mm", "beta_deg", "theta_deg"} <= set(s.keys())


def test_execute_arch_curve_completes(client):
    points = cam_from_curve.sample_arch_curve()
    cam_from_curve.check(
        client.post("/api/cam/execute", json={
            "points": points,
            "material": 0,
            "wire_diameter_mm": 0.457,
        }).json()
    )
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        st = cam_from_curve.check(client.get("/api/bending/status").json())
        if not st["running"]:
            return
        time.sleep(0.1)
    pytest.fail("cam execute did not complete")


# ────────────── End-to-end: run the script ──────────────

def test_cam_from_curve_preview_script_runs(backend_url):
    proc = subprocess.run(
        [sys.executable, SCRIPT, "--host", backend_url],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    assert "B-code preview" in proc.stdout
    assert "preview only" in proc.stdout


def test_cam_from_curve_execute_script_runs(backend_url):
    proc = subprocess.run(
        [sys.executable, SCRIPT, "--host", backend_url, "--execute"],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    assert "Executing on hardware" in proc.stdout
    assert "Final axes" in proc.stdout
