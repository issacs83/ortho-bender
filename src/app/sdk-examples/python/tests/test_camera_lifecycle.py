"""test_camera_lifecycle.py — /api/camera/connect · /disconnect 동작 검증.

mock 백엔드 위에서 connect → disconnect → reconnect 왕복을 확인하고,
disconnect 이후에는 capture / stream / settings 가 412 CAMERA_OFFLINE
으로 막히는지 확인합니다.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_camera(client):
    """Each test starts with the camera connected."""
    client.post("/api/camera/connect")
    yield
    client.post("/api/camera/connect")


def _status(client):
    r = client.get("/api/camera/status")
    assert r.status_code == 200
    env = r.json()
    assert env["success"] is True
    return env["data"]


def test_camera_starts_connected(client):
    """부팅 시 lifespan 이 camera_svc.connect() 를 호출하므로 처음엔 on."""
    status = _status(client)
    assert status["connected"] is True
    assert status["power_state"] == "on"


def test_camera_disconnect_transitions_to_off(client):
    env = client.post("/api/camera/disconnect").json()
    assert env["success"] is True
    assert env["data"]["power_state"] == "off"
    assert env["data"]["connected"] is False

    # Status reflects the transition.
    assert _status(client)["power_state"] == "off"


def test_capture_rejected_when_offline(client):
    client.post("/api/camera/disconnect")
    r = client.post("/api/camera/capture", params={"quality": 85})
    assert r.status_code == 412
    body = r.json()
    assert body["success"] is False
    assert body["code"] == "CAMERA_OFFLINE"


def test_settings_rejected_when_offline(client):
    client.post("/api/camera/disconnect")
    r = client.post("/api/camera/settings", json={"exposure_us": 5000, "gain_db": 6.0})
    assert r.status_code == 200   # envelope pattern
    body = r.json()
    assert body["success"] is False
    assert body["code"] == "CAMERA_OFFLINE"


def test_stream_rejected_when_offline(client):
    client.post("/api/camera/disconnect")
    r = client.get("/api/camera/stream")
    assert r.status_code == 412
    assert r.json()["code"] == "CAMERA_OFFLINE"


def test_reconnect_round_trip(client):
    # Disconnect, then connect back. Capture must work again afterward.
    client.post("/api/camera/disconnect")
    env = client.post("/api/camera/connect").json()
    assert env["success"] is True
    assert env["data"]["power_state"] == "on"
    assert env["data"]["connected"] is True

    r = client.post("/api/camera/capture", params={"quality": 85})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/jpeg")
    assert r.content[:3] == b"\xff\xd8\xff"


def test_connect_is_idempotent(client):
    # Ensure the camera is connected, then call connect again.
    client.post("/api/camera/connect")
    env = client.post("/api/camera/connect").json()
    assert env["success"] is True
    assert env["data"]["power_state"] == "on"


def test_disconnect_is_idempotent(client):
    client.post("/api/camera/disconnect")
    env = client.post("/api/camera/disconnect").json()
    assert env["success"] is True
    assert env["data"]["power_state"] == "off"
    # Leave the camera reconnected for subsequent tests (fixture is session-scoped).
    client.post("/api/camera/connect")
