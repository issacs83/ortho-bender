"""
conftest.py — Pytest fixtures for Ortho-Bender SDK server integration tests.

All tests run in mock mode (OB_MOCK_MODE=true) — no hardware required.
Uses pytest-asyncio with asyncio_mode=auto, function scope fixtures.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import os
import pytest
import pytest_asyncio

# Force mock mode BEFORE any server module is imported
os.environ["OB_MOCK_MODE"] = "true"
os.environ["OB_LOG_LEVEL"] = "warning"


def _reset_settings() -> None:
    """Reset the pydantic-settings singleton so OB_ env changes take effect."""
    import server.config as cfg_module
    cfg_module._settings = None


_reset_settings()

from httpx import AsyncClient, ASGITransport


def _make_app():
    """Create a fresh FastAPI app instance with mock mode active."""
    _reset_settings()
    from server.main import create_app
    return create_app()


# ---------------------------------------------------------------------------
# Function-scoped app + client (one startup/shutdown per test)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def app():
    """FastAPI app started fresh for each test."""
    application = _make_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def client(app):
    """Async HTTP client bound to the per-test app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# fresh_client: identical to client but resets bending state explicitly
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def fresh_client():
    """
    Fresh app + client with bending module state reset.

    Use this for tests that rely on a clean bending._state.
    """
    try:
        import server.routers.bending as bending_mod
        bending_mod._state.running = False
        bending_mod._state.current_step = 0
        bending_mod._state.total_steps = 0
        bending_mod._state.material = None
        bending_mod._state.wire_diameter_mm = None
    except Exception:
        pass

    application = _make_app()
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
