# src/app/server/tests/test_camera_endpoints.py
"""
test_camera_endpoints.py — Integration tests for all 20 camera REST endpoints.

Tests run in mock mode (OB_MOCK_MODE=true) — no hardware required.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Connection & Status
# ---------------------------------------------------------------------------

async def test_connect(client):
    resp = await client.post("/api/camera/connect")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "device" in data
    assert "capabilities" in data
    assert data["device"]["vendor"] == "Mock"


async def test_status(client):
    resp = await client.get("/api/camera/status")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["connected"] is True


async def test_capabilities(client):
    resp = await client.get("/api/camera/capabilities")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["exposure"]["supported"] is True
    assert data["roi"]["supported"] is True


async def test_device_info(client):
    resp = await client.get("/api/camera/device-info")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "model" in data
    assert "serial" in data


# ---------------------------------------------------------------------------
# Exposure
# ---------------------------------------------------------------------------

async def test_get_exposure(client):
    resp = await client.get("/api/camera/exposure")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "time_us" in data
    assert "range" in data


async def test_set_exposure_manual(client):
    resp = await client.post("/api/camera/exposure",
                             json={"auto": False, "time_us": 10000})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["time_us"] == 10000
    assert data["auto"] is False


async def test_set_exposure_auto(client):
    resp = await client.post("/api/camera/exposure", json={"auto": True})
    assert resp.status_code == 200
    assert resp.json()["data"]["auto"] is True


async def test_set_exposure_out_of_range(client):
    resp = await client.post("/api/camera/exposure",
                             json={"auto": False, "time_us": 999999999})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "FEATURE_OUT_OF_RANGE"


# ---------------------------------------------------------------------------
# Gain
# ---------------------------------------------------------------------------

async def test_get_gain(client):
    resp = await client.get("/api/camera/gain")
    assert resp.status_code == 200
    assert "value_db" in resp.json()["data"]


async def test_set_gain(client):
    resp = await client.post("/api/camera/gain",
                             json={"auto": False, "value_db": 6.0})
    assert resp.status_code == 200
    assert resp.json()["data"]["value_db"] == 6.0


# ---------------------------------------------------------------------------
# ROI
# ---------------------------------------------------------------------------

async def test_get_roi(client):
    resp = await client.get("/api/camera/roi")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "width" in data
    assert "width_range" in data


async def test_set_roi(client):
    resp = await client.post("/api/camera/roi",
                             json={"width": 800, "height": 600})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["width"] == 800
    assert data["height"] == 600
    assert "frame_rate" in data["invalidated"]


async def test_center_roi(client):
    await client.post("/api/camera/roi", json={"width": 800, "height": 600})
    resp = await client.post("/api/camera/roi/center")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["offset_x"] == (1456 - 800) // 2
    assert data["offset_y"] == (1088 - 600) // 2


# ---------------------------------------------------------------------------
# Pixel Format
# ---------------------------------------------------------------------------

async def test_get_pixel_format(client):
    resp = await client.get("/api/camera/pixel-format")
    assert resp.status_code == 200
    assert "format" in resp.json()["data"]
    assert "available" in resp.json()["data"]


async def test_set_pixel_format(client):
    resp = await client.post("/api/camera/pixel-format",
                             json={"format": "mono12"})
    assert resp.status_code == 200
    assert resp.json()["data"]["format"] == "mono12"


# ---------------------------------------------------------------------------
# Frame Rate
# ---------------------------------------------------------------------------

async def test_get_frame_rate(client):
    resp = await client.get("/api/camera/frame-rate")
    assert resp.status_code == 200
    assert "value" in resp.json()["data"]


async def test_set_frame_rate(client):
    resp = await client.post("/api/camera/frame-rate",
                             json={"enable": True, "value": 15.0})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["enable"] is True
    assert data["value"] == 15.0


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------

async def test_get_trigger(client):
    resp = await client.get("/api/camera/trigger")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "mode" in data
    assert "available_modes" in data


async def test_set_trigger_software(client):
    resp = await client.post("/api/camera/trigger",
                             json={"mode": "software"})
    assert resp.status_code == 200
    assert resp.json()["data"]["mode"] == "software"


async def test_fire_trigger(client):
    await client.post("/api/camera/trigger", json={"mode": "software"})
    resp = await client.post("/api/camera/trigger/fire")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Temperature
# ---------------------------------------------------------------------------

async def test_get_temperature(client):
    resp = await client.get("/api/camera/temperature")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "value_c" in data
    assert 30.0 <= data["value_c"] <= 50.0


# ---------------------------------------------------------------------------
# UserSet
# ---------------------------------------------------------------------------

async def test_get_user_set(client):
    resp = await client.get("/api/camera/user-set")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "available_slots" in data
    assert "Default" in data["available_slots"]


async def test_user_set_save_load(client):
    # Set exposure
    await client.post("/api/camera/exposure",
                      json={"auto": False, "time_us": 8000})
    # Save
    resp = await client.post("/api/camera/user-set/save",
                             json={"slot": "UserSet1"})
    assert resp.status_code == 200
    # Change exposure
    await client.post("/api/camera/exposure",
                      json={"auto": False, "time_us": 1000})
    # Load
    resp = await client.post("/api/camera/user-set/load",
                             json={"slot": "UserSet1"})
    assert resp.status_code == 200
    # Verify restored
    resp = await client.get("/api/camera/exposure")
    assert resp.json()["data"]["time_us"] == 8000


async def test_user_set_default(client):
    resp = await client.post("/api/camera/user-set/default",
                             json={"slot": "UserSet1"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Capture & Stream
# ---------------------------------------------------------------------------

async def test_capture_jpeg(client):
    resp = await client.post("/api/camera/capture")
    assert resp.status_code == 200
    assert "image/jpeg" in resp.headers["content-type"]
    assert resp.content[:3] == b"\xff\xd8\xff"


async def test_capture_custom_quality(client):
    resp = await client.post("/api/camera/capture?quality=50")
    assert resp.status_code == 200
    assert resp.content[:3] == b"\xff\xd8\xff"


# ---------------------------------------------------------------------------
# Disconnect
# ---------------------------------------------------------------------------

async def test_disconnect(client):
    resp = await client.post("/api/camera/disconnect")
    assert resp.status_code == 200
    # Status should show disconnected
    resp = await client.get("/api/camera/status")
    data = resp.json()["data"]
    assert data["connected"] is False
