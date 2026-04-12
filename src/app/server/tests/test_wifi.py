"""
test_wifi.py — Integration tests for /api/wifi/* endpoints.

WiFi endpoints call wpa_cli subprocess. In CI (no wpa_supplicant),
they should return a structured error — not crash the server.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest


async def test_wifi_status_returns_json(client):
    """GET /api/wifi/status should return JSON (success or error)."""
    resp = await client.get("/api/wifi/status")
    assert resp.status_code == 200
    body = resp.json()
    # Either success with data or failure with error — both are valid JSON
    assert "success" in body


async def test_wifi_scan_returns_json(client):
    """GET /api/wifi/scan should return JSON (success or error)."""
    resp = await client.get("/api/wifi/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert "success" in body


async def test_wifi_connect_validates_ssid(client):
    """POST /api/wifi/connect without ssid should return 422."""
    resp = await client.post("/api/wifi/connect", json={"password": "test"})
    assert resp.status_code == 422


async def test_wifi_connect_accepts_ssid(client):
    """POST /api/wifi/connect with valid body should not crash server."""
    resp = await client.post("/api/wifi/connect", json={
        "ssid": "TestNetwork",
        "password": "testpass",
    })
    # Either succeeds or fails gracefully — must return JSON
    assert resp.status_code == 200
    body = resp.json()
    assert "success" in body


async def test_wifi_disconnect_returns_json(client):
    """POST /api/wifi/disconnect should return JSON."""
    resp = await client.post("/api/wifi/disconnect")
    assert resp.status_code == 200
    body = resp.json()
    assert "success" in body
