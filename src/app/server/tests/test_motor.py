"""
test_motor.py — Integration tests for /api/motor/* endpoints.

All tests use mock IPC (no M7 hardware required).

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# GET /api/motor/status
# ---------------------------------------------------------------------------

async def test_motor_status_success(client):
    """Motor status should return success=true with axes list."""
    resp = await client.get("/api/motor/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert "state" in data
    assert "axes" in data
    assert isinstance(data["axes"], list)
    assert "axis_mask" in data


async def test_motor_status_has_expected_fields(client):
    """Motor status data should have all required fields."""
    resp = await client.get("/api/motor/status")
    data = resp.json()["data"]
    assert "state" in data
    assert "axes" in data
    assert "current_step" in data
    assert "total_steps" in data
    assert "axis_mask" in data
    assert data["axis_mask"] == 0x03  # PHASE1 mock: FEED + BEND


# ---------------------------------------------------------------------------
# POST /api/motor/move
# ---------------------------------------------------------------------------

async def test_motor_move_feed_axis(client):
    """Moving FEED axis (0) by a positive distance should succeed."""
    resp = await client.post("/api/motor/move", json={
        "axis": 0,
        "distance": 10.0,
        "speed": 20.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True


async def test_motor_move_bend_axis(client):
    """Moving BEND axis (1) by an angle should succeed."""
    resp = await client.post("/api/motor/move", json={
        "axis": 1,
        "distance": 30.0,
        "speed": 45.0,
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


async def test_motor_move_zero_distance_rejected(client):
    """Distance=0 should be rejected with 422 (validation error)."""
    resp = await client.post("/api/motor/move", json={
        "axis": 0,
        "distance": 0.0,
        "speed": 10.0,
    })
    assert resp.status_code == 422


async def test_motor_move_negative_speed_rejected(client):
    """Speed must be > 0; negative speed should return 422."""
    resp = await client.post("/api/motor/move", json={
        "axis": 0,
        "distance": 5.0,
        "speed": -1.0,
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/motor/jog
# ---------------------------------------------------------------------------

async def test_motor_jog_positive_direction(client):
    """Jog with direction=+1 should succeed."""
    resp = await client.post("/api/motor/jog", json={
        "axis": 0,
        "direction": 1,
        "speed": 10.0,
        "distance": 5.0,
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


async def test_motor_jog_negative_direction(client):
    """Jog with direction=-1 should succeed."""
    resp = await client.post("/api/motor/jog", json={
        "axis": 0,
        "direction": -1,
        "speed": 10.0,
        "distance": 5.0,
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


async def test_motor_jog_invalid_direction(client):
    """Direction=0 should be rejected with 422."""
    resp = await client.post("/api/motor/jog", json={
        "axis": 0,
        "direction": 0,
        "speed": 10.0,
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/motor/home
# ---------------------------------------------------------------------------

async def test_motor_home_all_axes(client):
    """Home with axis_mask=0 (all axes) should succeed."""
    resp = await client.post("/api/motor/home", json={"axis_mask": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    # After homing mock resets position to 0.0
    data = body["data"]
    assert data["state"] == 0  # IDLE


async def test_motor_home_specific_axes(client):
    """Home with axis_mask=0x01 (FEED only) should succeed."""
    resp = await client.post("/api/motor/home", json={"axis_mask": 1})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


async def test_motor_home_invalid_mask(client):
    """axis_mask > 0x0F should be rejected."""
    resp = await client.post("/api/motor/home", json={"axis_mask": 255})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/motor/stop
# ---------------------------------------------------------------------------

async def test_motor_stop(client):
    """Stop command should succeed and return IDLE state."""
    resp = await client.post("/api/motor/stop")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["state"] == 0  # MotionState.IDLE


# ---------------------------------------------------------------------------
# POST /api/motor/estop
# ---------------------------------------------------------------------------

async def test_motor_estop(client):
    """E-STOP should succeed and return ESTOP state (6) in mock."""
    resp = await client.post("/api/motor/estop")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["state"] == 6  # MotionState.ESTOP


# ---------------------------------------------------------------------------
# POST /api/motor/reset
# ---------------------------------------------------------------------------

async def test_motor_reset(client):
    """Reset should clear fault state and return success."""
    resp = await client.post("/api/motor/reset", json={"axis_mask": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["state"] == 0  # IDLE after reset
