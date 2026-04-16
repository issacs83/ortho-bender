"""Integration tests for /api/motor/diag/* endpoints."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with mock backend."""
    from fastapi import FastAPI
    from src.app.server.routers.diag_router import router, get_diag_service
    from src.app.server.services.motor_backend import MockMotorBackend
    from src.app.server.services.diag_service import DiagService

    app = FastAPI()
    backend = MockMotorBackend()
    diag_svc = DiagService(backend)

    app.include_router(router)
    app.dependency_overrides[get_diag_service] = lambda: diag_svc

    return TestClient(app)


def test_get_backend(client):
    r = client.get("/api/motor/diag/backend")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["data"]["backend"] == "mock"


def test_spi_test(client):
    r = client.get("/api/motor/diag/spi-test")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    results = data["data"]["results"]
    assert len(results) == 3
    assert all(res["ok"] for res in results)


def test_read_register(client):
    r = client.get("/api/motor/diag/register/tmc260c_0/0x04")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert "value" in data["data"]


def test_write_register(client):
    r = client.post(
        "/api/motor/diag/register/tmc260c_0/0x04",
        json={"value": 0x101D5},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True


def test_dump_registers(client):
    r = client.get("/api/motor/diag/dump/tmc260c_0")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert "CHOPCONF" in data["data"]["registers"]


def test_dump_tmc5072(client):
    r = client.get("/api/motor/diag/dump/tmc5072")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert "GCONF" in data["data"]["registers"]


def test_invalid_driver_returns_error(client):
    r = client.get("/api/motor/diag/register/nonexistent/0x00")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is False
