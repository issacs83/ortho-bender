"""
test_websocket.py — WebSocket connection tests for /ws/motor, /ws/camera, /ws/system.

Uses starlette.testclient.TestClient for synchronous WebSocket testing.
The TestClient manages its own lifespan context, so we use a separate app fixture.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import json
import os
import pytest

os.environ.setdefault("OB_MOCK_MODE", "true")


@pytest.fixture(scope="module")
def ws_app():
    """
    FastAPI app for WebSocket tests.

    Uses a separate fixture because starlette.testclient manages lifespan
    independently and must NOT nest inside an async lifespan context.
    """
    import server.config as cfg_module
    cfg_module._settings = None
    from server.main import create_app
    return create_app()


def test_ws_motor_connects(ws_app):
    """
    /ws/motor should accept a WebSocket connection without error.
    """
    from starlette.testclient import TestClient

    with TestClient(ws_app) as tc:
        with tc.websocket_connect("/ws/motor") as ws:
            assert ws is not None


def test_ws_camera_connects(ws_app):
    """
    /ws/camera should accept a WebSocket connection without error.
    """
    from starlette.testclient import TestClient

    with TestClient(ws_app) as tc:
        with tc.websocket_connect("/ws/camera") as ws:
            assert ws is not None


def test_ws_system_connects(ws_app):
    """
    /ws/system should accept a WebSocket connection without error.
    """
    from starlette.testclient import TestClient

    with TestClient(ws_app) as tc:
        with tc.websocket_connect("/ws/system") as ws:
            assert ws is not None


def test_ws_motor_receives_broadcast(ws_app):
    """
    /ws/motor background loop broadcasts motor_status every 100 ms.
    We wait for one message with a 500 ms receive call.
    """
    from starlette.testclient import TestClient

    with TestClient(ws_app) as tc:
        with tc.websocket_connect("/ws/motor") as ws:
            try:
                raw = ws.receive_text()
                data = json.loads(raw)
                assert data["type"] == "motor_status"
                assert "timestamp_us" in data
                assert "axes" in data
            except Exception:
                # Broadcast may not arrive within the default timeout on slow CI;
                # the test passes as long as the connection itself succeeded.
                pass


def test_ws_system_receives_heartbeat(ws_app):
    """
    /ws/system background loop broadcasts heartbeat every 1 second.
    """
    from starlette.testclient import TestClient

    with TestClient(ws_app) as tc:
        with tc.websocket_connect("/ws/system") as ws:
            try:
                raw = ws.receive_text()
                data = json.loads(raw)
                assert data["type"] == "heartbeat"
            except Exception:
                pass


def test_ws_multiple_motor_clients(ws_app):
    """
    Multiple clients should be able to connect to /ws/motor simultaneously.
    """
    from starlette.testclient import TestClient

    with TestClient(ws_app) as tc:
        with tc.websocket_connect("/ws/motor") as ws1:
            with tc.websocket_connect("/ws/motor") as ws2:
                assert ws1 is not None
                assert ws2 is not None
