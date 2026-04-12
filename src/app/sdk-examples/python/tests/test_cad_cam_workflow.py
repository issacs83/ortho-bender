"""test_cad_cam_workflow.py — CAD/CAM 통합 테스트.

Mock 백엔드를 대상으로 /api/cam, /api/bending, /api/camera 전체 플로우를 검증.
실기기를 쓰려면 ORTHO_BENDER_URL 환경변수로 오버라이드하세요.
"""
import time
import base64

import pytest


STRAIGHT_WIRE = [
    {"x": 0.0, "y": 0.0, "z": 0.0},
    {"x": 10.0, "y": 0.0, "z": 0.0},
    {"x": 20.0, "y": 0.0, "z": 0.0},
]

L_BEND = [
    {"x": 0.0, "y": 0.0, "z": 0.0},
    {"x": 10.0, "y": 0.0, "z": 0.0},
    {"x": 10.0, "y": 10.0, "z": 0.0},
]


# ────────────── Health & Envelope ──────────────

def test_backend_is_healthy(client):
    r = client.get("/health").json()
    assert r["status"] == "ok"


def test_system_status_envelope(client):
    r = client.get("/api/system/status").json()
    assert r["success"] is True
    assert "ipc_connected" in r["data"]


# ────────────── CAM Preview ──────────────

def test_cam_preview_straight_wire_has_zero_bend(client):
    r = client.post("/api/cam/generate", json={
        "points": STRAIGHT_WIRE,
        "material": 0,
        "wire_diameter_mm": 0.457,
    }).json()
    assert r["success"] is True
    assert r["data"]["max_bend_deg"] == pytest.approx(0.0, abs=0.1)
    assert r["data"]["total_length_mm"] == pytest.approx(20.0, abs=0.5)


def test_cam_preview_l_bend_has_right_angle(client):
    r = client.post("/api/cam/generate", json={
        "points": L_BEND,
        "material": 0,
        "wire_diameter_mm": 0.457,
    }).json()
    assert r["success"] is True
    # SS 304 스프링백 ×1.10 → 90° × 1.10 = 99°
    assert r["data"]["max_bend_deg"] == pytest.approx(99.0, abs=2.0)


def test_cam_preview_rejects_single_point(client):
    r = client.post("/api/cam/generate", json={
        "points": [{"x": 0.0, "y": 0.0, "z": 0.0}],
        "material": 0,
        "wire_diameter_mm": 0.457,
    }).json()
    assert r["success"] is False
    assert r["code"] == "CAM_INVALID_INPUT"


def test_cam_preview_is_idempotent(client):
    body = {"points": L_BEND, "material": 0, "wire_diameter_mm": 0.457}
    r1 = client.post("/api/cam/generate", json=body).json()["data"]
    r2 = client.post("/api/cam/generate", json=body).json()["data"]
    assert r1["steps"] == r2["steps"]


def test_cam_preview_springback_toggle(client):
    body = {"points": L_BEND, "material": 0, "wire_diameter_mm": 0.457}
    with_sb = client.post(
        "/api/cam/generate", json={**body, "apply_springback": True}
    ).json()["data"]
    no_sb = client.post(
        "/api/cam/generate", json={**body, "apply_springback": False}
    ).json()["data"]
    assert with_sb["max_bend_deg"] > no_sb["max_bend_deg"]


# ────────────── CAM Execute & Progress ──────────────

def test_cam_execute_completes_under_mock(client):
    client.post("/api/cam/execute", json={
        "points": L_BEND,
        "material": 0,
        "wire_diameter_mm": 0.457,
    })

    deadline = time.monotonic() + 5.0
    completed = False
    last_step = -1
    while time.monotonic() < deadline:
        st = client.get("/api/bending/status").json()["data"]
        assert st["current_step"] >= last_step
        last_step = st["current_step"]
        if not st["running"]:
            completed = True
            break
        time.sleep(0.1)

    assert completed, "bending did not complete"


def test_bending_stop_returns_to_idle(client):
    client.post("/api/cam/execute", json={
        "points": L_BEND,
        "material": 0,
        "wire_diameter_mm": 0.457,
    })
    time.sleep(0.05)
    r = client.post("/api/bending/stop").json()
    assert r["success"] is True

    for _ in range(20):
        st = client.get("/api/bending/status").json()["data"]
        if not st["running"]:
            return
        time.sleep(0.05)
    pytest.fail("bending did not stop")


# ────────────── Camera ──────────────

def test_camera_capture_returns_valid_jpeg(client):
    r = client.post("/api/camera/capture", json={"quality": 85}).json()
    assert r["success"] is True
    assert "frame_b64" in r["data"]
    assert r["data"]["width"] > 0 and r["data"]["height"] > 0

    jpeg = base64.b64decode(r["data"]["frame_b64"])
    assert jpeg[:3] == b"\xff\xd8\xff"  # JPEG SOI marker


def test_camera_status_does_not_leak_implementation(client):
    r = client.get("/api/camera/status").json()["data"]
    assert "connected" in r
    assert "width" in r and "height" in r
    # backend 필드는 참고용. 이 값에 조건 분기하지 말 것.
    assert r.get("backend") in {"vimba_x", "v4l2", "mock"}


# ────────────── Hardware Abstraction Invariants ──────────────

@pytest.mark.parametrize("material,expected_factor", [
    (0, 1.10),  # SS_304
    (1, 1.35),  # NITI
    (2, 1.15),  # BETA_TI
    (3, 1.30),  # CU_NITI
])
def test_springback_factors_per_material(client, material, expected_factor):
    body = {
        "points": L_BEND,
        "material": material,
        "wire_diameter_mm": 0.457,
    }
    r = client.post("/api/cam/generate", json=body).json()["data"]
    expected = min(90.0 * expected_factor, 180.0)
    assert r["max_bend_deg"] == pytest.approx(expected, abs=1.0)
