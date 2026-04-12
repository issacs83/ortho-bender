"""
test_health.py — Tests for /health endpoint and basic app startup.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest


async def test_health_returns_ok(client):
    """GET /health should return 200 with status=ok."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


async def test_openapi_docs_available(client):
    """GET /docs should return 200 (Swagger UI)."""
    resp = await client.get("/docs")
    assert resp.status_code == 200


async def test_openapi_schema_available(client):
    """GET /openapi.json should return valid OpenAPI schema."""
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert "paths" in schema
    assert "openapi" in schema
