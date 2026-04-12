"""test_lifecycle_demo.py — lifecycle_demo.py 예제 검증.

envelope helper 단위 테스트 + mock 백엔드로 실제 스크립트를 돌려 exit code
와 출력 흐름을 확인합니다.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

import lifecycle_demo


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.abspath(os.path.join(HERE, "..", "lifecycle_demo.py"))


# ────────────── Helper unit tests ──────────────

def test_envelope_success():
    ok_, data, code, err = lifecycle_demo.envelope(
        {"success": True, "data": {"x": 1}, "code": None, "error": None}
    )
    assert ok_ is True
    assert data == {"x": 1}
    assert code is None
    assert err is None


def test_envelope_failure():
    ok_, data, code, err = lifecycle_demo.envelope(
        {"success": False, "data": None, "code": "MOTOR_BUSY", "error": "running"}
    )
    assert ok_ is False
    assert data is None
    assert code == "MOTOR_BUSY"
    assert err == "running"


def test_check_raises_on_failure():
    with pytest.raises(RuntimeError, match=r"\[CAMERA_OFFLINE\] off"):
        lifecycle_demo.check(
            {"success": False, "data": None, "code": "CAMERA_OFFLINE", "error": "off"}
        )


# ────────────── End-to-end script run ──────────────

@pytest.fixture(autouse=True)
def _reset_state(client):
    # Leave the mock backend in a clean state for subsequent tests.
    client.post("/api/motor/stop")
    client.post("/api/motor/enable")
    client.post("/api/camera/connect")
    yield
    client.post("/api/motor/stop")
    client.post("/api/motor/enable")
    client.post("/api/camera/connect")


def test_lifecycle_demo_script_runs(backend_url):
    proc = subprocess.run(
        [sys.executable, SCRIPT, "--host", backend_url],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    out = proc.stdout
    assert "Initial state" in out
    assert "Camera: disconnect" in out
    assert "power_state → off" in out
    assert "412 Precondition Failed" in out
    assert "CAMERA_OFFLINE" in out
    assert "Camera: reconnect" in out
    assert "power_state → on" in out
    assert "Motor: disable drivers" in out
    assert "driver_enabled → False" in out
    assert "Correctly refused: [MOTOR_BUSY]" in out
    assert "driver_enabled → True" in out
    assert "Done." in out
