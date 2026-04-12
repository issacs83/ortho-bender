"""
test_system.py — Integration tests for /api/system/* endpoints.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# GET /api/system/status
# ---------------------------------------------------------------------------

async def test_system_status_returns_success(client):
    """System status should return success=true."""
    resp = await client.get("/api/system/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True


async def test_system_status_has_required_fields(client):
    """System status data should contain all expected fields."""
    resp = await client.get("/api/system/status")
    data = resp.json()["data"]
    required = {
        "motion_state", "camera_connected", "ipc_connected",
        "m7_heartbeat_ok", "active_alarms", "uptime_s",
    }
    for field in required:
        assert field in data, f"Missing field: {field}"


async def test_system_status_camera_connected_in_mock(client):
    """Camera should be connected in mock mode."""
    resp = await client.get("/api/system/status")
    data = resp.json()["data"]
    assert data["camera_connected"] is True


async def test_system_status_ipc_connected_in_mock(client):
    """IPC should be connected in mock mode."""
    resp = await client.get("/api/system/status")
    data = resp.json()["data"]
    assert data["ipc_connected"] is True


async def test_system_status_uptime_positive(client):
    """Uptime should be a non-negative number."""
    resp = await client.get("/api/system/status")
    data = resp.json()["data"]
    assert isinstance(data["uptime_s"], (int, float))
    assert data["uptime_s"] >= 0.0


async def test_system_status_motion_state_valid(client):
    """Motion state should be a valid MotionState integer (0-6)."""
    resp = await client.get("/api/system/status")
    data = resp.json()["data"]
    assert 0 <= data["motion_state"] <= 6


# ---------------------------------------------------------------------------
# GET /api/system/version
# ---------------------------------------------------------------------------

async def test_system_version_returns_success(client):
    """Version endpoint should return success=true."""
    resp = await client.get("/api/system/version")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True


async def test_system_version_sdk_version_present(client):
    """SDK version should be present in mock mode."""
    resp = await client.get("/api/system/version")
    data = resp.json()["data"]
    assert "sdk_version" in data
    assert data["sdk_version"] == "0.1.0"


async def test_system_version_m7_firmware_in_mock(client):
    """M7 firmware version should be returned from mock IPC."""
    resp = await client.get("/api/system/version")
    data = resp.json()["data"]
    # Mock returns 1.0.0
    assert data["m7_firmware"] == "1.0.0"


# ---------------------------------------------------------------------------
# POST /api/system/reboot
# ---------------------------------------------------------------------------

async def test_system_reboot_requires_confirm(client):
    """Reboot without confirm=true should return error (not 422)."""
    resp = await client.post("/api/system/reboot", json={"confirm": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["code"] == "REBOOT_NOT_CONFIRMED"


async def test_system_reboot_with_confirm_schedules(client):
    """Reboot with confirm=true should succeed (schedules deferred task)."""
    resp = await client.post("/api/system/reboot", json={"confirm": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "Reboot" in body["data"]["message"]
