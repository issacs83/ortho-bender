"""
test_bending.py — Integration tests for /api/bending/* endpoints.

Tests the B-code execution pipeline including springback compensation
and bending status reporting.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# GET /api/bending/status (idle)
# ---------------------------------------------------------------------------

async def test_bending_status_idle(fresh_client):
    """Bending status should return running=false on a fresh app instance."""
    resp = await fresh_client.get("/api/bending/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["running"] is False
    assert data["current_step"] == 0
    assert data["total_steps"] == 0


# ---------------------------------------------------------------------------
# POST /api/bending/execute
# ---------------------------------------------------------------------------

async def test_bending_execute_single_step(fresh_client):
    """Execute a single B-code step with SS_304 material."""
    resp = await fresh_client.post("/api/bending/execute", json={
        "steps": [{"L_mm": 10.0, "beta_deg": 0.0, "theta_deg": 45.0}],
        "material": 0,           # SS_304
        "wire_diameter_mm": 0.457,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["total_steps"] == 1


async def test_bending_execute_multi_step(fresh_client):
    """Execute a multi-step B-code sequence."""
    steps = [
        {"L_mm": 5.0, "beta_deg": 0.0, "theta_deg": 30.0},
        {"L_mm": 8.0, "beta_deg": 90.0, "theta_deg": 45.0},
        {"L_mm": 3.0, "beta_deg": -45.0, "theta_deg": 60.0},
    ]
    resp = await fresh_client.post("/api/bending/execute", json={
        "steps": steps,
        "material": 0,
        "wire_diameter_mm": 0.457,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["total_steps"] == 3


async def test_bending_execute_niti_material(fresh_client):
    """Execute with NiTi material (higher springback compensation)."""
    resp = await fresh_client.post("/api/bending/execute", json={
        "steps": [{"L_mm": 10.0, "beta_deg": 0.0, "theta_deg": 90.0}],
        "material": 1,           # NITI
        "wire_diameter_mm": 0.457,
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


async def test_bending_execute_beta_ti(fresh_client):
    """Execute with Beta-Titanium material."""
    resp = await fresh_client.post("/api/bending/execute", json={
        "steps": [{"L_mm": 7.0, "beta_deg": 45.0, "theta_deg": 60.0}],
        "material": 2,           # BETA_TI
        "wire_diameter_mm": 0.5,
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


async def test_bending_execute_empty_steps_rejected(fresh_client):
    """Empty steps list should be rejected with 422."""
    resp = await fresh_client.post("/api/bending/execute", json={
        "steps": [],
        "material": 0,
        "wire_diameter_mm": 0.457,
    })
    assert resp.status_code == 422


async def test_bending_execute_invalid_theta_rejected(fresh_client):
    """theta_deg > 180 should be rejected with 422."""
    resp = await fresh_client.post("/api/bending/execute", json={
        "steps": [{"L_mm": 10.0, "beta_deg": 0.0, "theta_deg": 200.0}],
        "material": 0,
        "wire_diameter_mm": 0.457,
    })
    assert resp.status_code == 422


async def test_bending_execute_invalid_L_mm_rejected(fresh_client):
    """L_mm < 0.5 should be rejected with 422."""
    resp = await fresh_client.post("/api/bending/execute", json={
        "steps": [{"L_mm": 0.1, "beta_deg": 0.0, "theta_deg": 45.0}],
        "material": 0,
        "wire_diameter_mm": 0.457,
    })
    assert resp.status_code == 422


async def test_bending_execute_springback_caps_at_180(fresh_client):
    """Springback compensation should cap theta at 180 degrees, not error."""
    # theta=170 * 1.35 (NiTi) = 229.5 → capped to 180
    resp = await fresh_client.post("/api/bending/execute", json={
        "steps": [{"L_mm": 10.0, "beta_deg": 0.0, "theta_deg": 170.0}],
        "material": 1,           # NiTi — 35% springback
        "wire_diameter_mm": 0.457,
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# POST /api/bending/stop
# ---------------------------------------------------------------------------

async def test_bending_stop(fresh_client):
    """Bending stop should always succeed (even when not running)."""
    resp = await fresh_client.post("/api/bending/stop")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["bending"]["running"] is False


# ---------------------------------------------------------------------------
# GET /api/bending/status after execute
# ---------------------------------------------------------------------------

async def test_bending_status_after_execute(fresh_client):
    """After a successful execute, status should show all steps completed."""
    await fresh_client.post("/api/bending/execute", json={
        "steps": [
            {"L_mm": 5.0, "beta_deg": 0.0, "theta_deg": 45.0},
            {"L_mm": 5.0, "beta_deg": 0.0, "theta_deg": 45.0},
        ],
        "material": 0,
        "wire_diameter_mm": 0.457,
    })
    resp = await fresh_client.get("/api/bending/status")
    data = resp.json()["data"]
    # After mock execute completes synchronously, current_step == total_steps
    assert data["current_step"] == data["total_steps"]
    assert data["running"] is False
