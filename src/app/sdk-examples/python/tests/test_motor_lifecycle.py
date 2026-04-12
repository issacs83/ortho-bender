"""test_motor_lifecycle.py — /api/motor/enable · /disable 동작 검증.

TMC260C-PA DRV_ENN 토글을 IPC 모의계층까지 왕복으로 확인합니다.
- 부팅 후 driver_enabled=True
- disable → driver_enabled=False 로 내려감
- enable → 다시 True
- 모션 중에는 disable 거부 (MOTOR_BUSY)
"""
from __future__ import annotations

import time

import pytest


@pytest.fixture(autouse=True)
def _reset_motor(client):
    # 모든 테스트는 drivers enabled, IDLE 상태에서 시작.
    client.post("/api/motor/stop")
    client.post("/api/motor/enable")
    yield
    client.post("/api/motor/stop")
    client.post("/api/motor/enable")


def _status(client):
    env = client.get("/api/motor/status").json()
    assert env["success"] is True
    return env["data"]


def test_motor_starts_driver_enabled(client):
    assert _status(client)["driver_enabled"] is True


def test_disable_transitions_to_free_wheel(client):
    env = client.post("/api/motor/disable").json()
    assert env["success"] is True
    assert env["data"]["driver_enabled"] is False
    assert _status(client)["driver_enabled"] is False


def test_enable_restores_coils(client):
    client.post("/api/motor/disable")
    env = client.post("/api/motor/enable").json()
    assert env["success"] is True
    assert env["data"]["driver_enabled"] is True


def test_disable_rejected_while_running(client):
    # Kick off a multi-step B-code run, then immediately try to disable.
    steps = [
        {"L_mm": 10.0, "beta_deg": 0.0, "theta_deg": 30.0},
        {"L_mm": 15.0, "beta_deg": 0.0, "theta_deg": 45.0},
        {"L_mm": 20.0, "beta_deg": 0.0, "theta_deg": 60.0},
    ]
    client.post("/api/bending/execute", json={
        "steps": steps,
        "material": 0,
        "wire_diameter_mm": 0.457,
    })

    # Give the mock simulator a moment to enter RUNNING.
    time.sleep(0.05)

    env = client.post("/api/motor/disable").json()
    assert env["success"] is False
    assert env["code"] == "MOTOR_BUSY"

    # Wait for bending to complete so teardown finds the motor IDLE.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not client.get("/api/bending/status").json()["data"]["running"]:
            break
        time.sleep(0.1)


def test_enable_is_idempotent(client):
    env = client.post("/api/motor/enable").json()
    assert env["success"] is True
    env = client.post("/api/motor/enable").json()
    assert env["success"] is True
    assert env["data"]["driver_enabled"] is True
