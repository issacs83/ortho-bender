"""test_basic_bend.py — basic_bend.py 예제 검증.

예제의 핵심 유틸(check envelope unwrap)과 예제가 실제로 호출하는 API 흐름을
mock 백엔드에서 재현합니다. 또한 스크립트 자체를 subprocess 로 돌려
end-to-end 동작을 확인합니다.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

import basic_bend


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.abspath(os.path.join(HERE, "..", "basic_bend.py"))


# ────────────── Helper unit tests ──────────────

def test_check_unwraps_success():
    assert basic_bend.check({"success": True, "data": {"x": 1}}) == {"x": 1}


def test_check_raises_on_failure():
    with pytest.raises(RuntimeError, match=r"\[4001\] AXIS_NOT_READY"):
        basic_bend.check({"success": False, "code": 4001, "error": "AXIS_NOT_READY"})


# ────────────── API flow replicated from the example ──────────────

def test_basic_bend_api_flow(client):
    """basic_bend.main() 이 호출하는 5단계를 그대로 재현."""
    status = basic_bend.check(client.get("/api/system/status").json())
    assert "sdk_version" in status
    assert "motion_state" in status

    motor = basic_bend.check(
        client.post("/api/motor/home", json={"axis_mask": 0}).json()
    )
    assert "state" in motor

    steps = [
        {"L_mm": 10.0, "beta_deg": 0.0, "theta_deg": 30.0},
        {"L_mm": 15.0, "beta_deg": 90.0, "theta_deg": 45.0},
        {"L_mm": 20.0, "beta_deg": -90.0, "theta_deg": 60.0},
    ]
    result = basic_bend.check(
        client.post("/api/bending/execute", json={
            "steps": steps,
            "material": 0,
            "wire_diameter_mm": 0.457,
        }).json()
    )
    assert result["total_steps"] == 3

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        bending = basic_bend.check(client.get("/api/bending/status").json())
        if not bending["running"]:
            break
        time.sleep(0.1)
    else:
        pytest.fail("bending did not complete in time")

    motor = basic_bend.check(client.get("/api/motor/status").json())
    # Phase 1 mock exposes FEED (0) + BEND (1); hardware may add ROTATE/LIFT.
    axes = {ax["axis"] for ax in motor["axes"]}
    assert {0, 1} <= axes


# ────────────── End-to-end: run the script itself ──────────────

def test_basic_bend_script_runs(backend_url):
    """예제를 실제로 실행해서 exit code 와 출력이 정상인지 확인."""
    proc = subprocess.run(
        [sys.executable, SCRIPT, "--host", backend_url],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    assert "System Status" in proc.stdout
    assert "Homing" in proc.stdout
    assert "Done." in proc.stdout
