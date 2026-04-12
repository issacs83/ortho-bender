"""
test_camera.py — Integration tests for /api/camera/* endpoints.

Uses CameraService in mock mode — no physical camera required.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# GET /api/camera/status
# ---------------------------------------------------------------------------

async def test_camera_status_returns_success(client):
    """Camera status should return success=true in mock mode."""
    resp = await client.get("/api/camera/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True


async def test_camera_status_connected_in_mock(client):
    """Camera should report connected=true when running in mock mode."""
    resp = await client.get("/api/camera/status")
    data = resp.json()["data"]
    assert data["connected"] is True
    assert data["backend"] == "mock"


async def test_camera_status_has_resolution(client):
    """Mock camera should report a non-zero resolution."""
    resp = await client.get("/api/camera/status")
    data = resp.json()["data"]
    assert data["width"] is not None and data["width"] > 0
    assert data["height"] is not None and data["height"] > 0


async def test_camera_status_has_settings_fields(client):
    """Camera status should include exposure_us and gain_db fields."""
    resp = await client.get("/api/camera/status")
    data = resp.json()["data"]
    assert "exposure_us" in data
    assert "gain_db" in data
    assert "format" in data


# ---------------------------------------------------------------------------
# POST /api/camera/capture
# ---------------------------------------------------------------------------

async def test_camera_capture_returns_jpeg(client):
    """Snapshot endpoint should return raw JPEG bytes (image/jpeg)."""
    resp = await client.post("/api/camera/capture")
    assert resp.status_code == 200
    assert "image/jpeg" in resp.headers["content-type"]
    # JPEG magic bytes: FF D8 FF
    assert resp.content[:3] == b"\xff\xd8\xff"


async def test_camera_capture_nonzero_size(client):
    """Captured JPEG should have non-trivial size (> 50 bytes)."""
    resp = await client.post("/api/camera/capture")
    assert resp.status_code == 200
    assert len(resp.content) > 50


async def test_camera_capture_custom_quality(client):
    """Capture with explicit quality parameter should succeed."""
    resp = await client.post("/api/camera/capture?quality=50")
    assert resp.status_code == 200
    assert resp.content[:3] == b"\xff\xd8\xff"


# ---------------------------------------------------------------------------
# POST /api/camera/settings
# ---------------------------------------------------------------------------

async def test_camera_settings_exposure(client):
    """Applying exposure_us setting should succeed and be reflected in status."""
    resp = await client.post("/api/camera/settings", json={"exposure_us": 10000.0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["exposure_us"] == 10000.0


async def test_camera_settings_gain(client):
    """Applying gain_db setting should succeed."""
    resp = await client.post("/api/camera/settings", json={"gain_db": 6.0})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


async def test_camera_settings_format_valid(client):
    """Valid pixel format should be accepted."""
    resp = await client.post("/api/camera/settings", json={"format": "mono12"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


async def test_camera_settings_format_invalid(client):
    """Invalid pixel format should return 422."""
    resp = await client.post("/api/camera/settings", json={"format": "rgb32"})
    assert resp.status_code == 422
