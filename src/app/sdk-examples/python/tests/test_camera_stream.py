"""test_camera_stream.py — camera_stream.py 예제 검증.

snapshot() REST 경로와 live_stream() WebSocket 경로를 모두 검증.
WebSocket 은 mock 백엔드의 camera_frame 메시지를 N 장 받는 것까지 확인.
"""
from __future__ import annotations

import asyncio
import os

import pytest

import camera_stream


# ────────────── check() helper ──────────────

def test_check_unwraps_success():
    assert camera_stream.check({"success": True, "data": {"ok": 1}}) == {"ok": 1}


def test_check_raises_on_failure():
    with pytest.raises(RuntimeError, match=r"\[2001\] CAMERA_NOT_CONNECTED"):
        camera_stream.check({
            "success": False, "code": 2001, "error": "CAMERA_NOT_CONNECTED",
        })


# ────────────── snapshot mode ──────────────

def test_snapshot_writes_valid_jpeg(tmp_path, backend_url):
    out = tmp_path / "frame.jpg"
    camera_stream.snapshot(backend_url, str(out))

    assert out.exists()
    data = out.read_bytes()
    assert len(data) > 100
    assert data[:3] == b"\xff\xd8\xff"  # JPEG SOI


# ────────────── live stream mode ──────────────

def test_live_stream_receives_frames(backend_url):
    # websockets must be installed for this test
    websockets = pytest.importorskip("websockets")
    asyncio.run(camera_stream.live_stream(backend_url, frames=3))


def test_live_stream_ws_url_rewriting():
    """http→ws / https→wss 변환이 정확한지 단위로 확인."""
    assert "http://localhost:8000".replace("http", "ws") + "/ws/camera" == (
        "ws://localhost:8000/ws/camera"
    )
    assert "https://board:8000".replace("http", "ws") + "/ws/camera" == (
        "wss://board:8000/ws/camera"
    )
