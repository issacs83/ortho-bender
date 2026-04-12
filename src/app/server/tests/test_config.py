"""
test_config.py — Unit tests for Settings configuration loading.

Verifies env var override, defaults, and prefix behaviour.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import os
import pytest


def _make_settings(**env_overrides):
    """Create a fresh Settings instance with given env var overrides."""
    import importlib
    import server.config as cfg_module

    old_env = {}
    try:
        for key, val in env_overrides.items():
            old_env[key] = os.environ.get(key)
            os.environ[key] = val

        # Force fresh instantiation
        cfg_module._settings = None
        settings = cfg_module.Settings()
        return settings
    finally:
        for key, orig in old_env.items():
            if orig is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = orig
        # Restore singleton to avoid polluting other tests
        cfg_module._settings = None


def test_default_mock_mode_is_true():
    """mock_mode should default to True for safe development use."""
    settings = _make_settings()
    assert settings.mock_mode is True


def test_env_override_mock_mode_false():
    """OB_MOCK_MODE=false should disable mock mode."""
    settings = _make_settings(OB_MOCK_MODE="false")
    assert settings.mock_mode is False


def test_env_override_mock_mode_true():
    """OB_MOCK_MODE=true should enable mock mode."""
    settings = _make_settings(OB_MOCK_MODE="true")
    assert settings.mock_mode is True


def test_default_port():
    """Default port should be 8000."""
    settings = _make_settings()
    assert settings.port == 8000


def test_env_override_port():
    """OB_PORT env var should override port."""
    settings = _make_settings(OB_PORT="9000")
    assert settings.port == 9000


def test_default_ipc_device():
    """Default IPC device should be /dev/rpmsg0."""
    settings = _make_settings()
    assert settings.ipc_device == "/dev/rpmsg0"


def test_env_override_ipc_device():
    """OB_IPC_DEVICE should override the RPMsg device path."""
    settings = _make_settings(OB_IPC_DEVICE="/dev/rpmsg1")
    assert settings.ipc_device == "/dev/rpmsg1"


def test_default_camera_fps():
    """Default camera FPS should be 15.0."""
    settings = _make_settings()
    assert settings.camera_fps == 15.0


def test_default_feed_max_mm():
    """Default feed max should be 200.0 mm."""
    settings = _make_settings()
    assert settings.feed_max_mm == 200.0


def test_default_bend_max_deg():
    """Default bend max should be 180.0 degrees."""
    settings = _make_settings()
    assert settings.bend_max_deg == 180.0


def test_get_settings_singleton():
    """get_settings() should return the same instance on repeated calls."""
    import server.config as cfg_module
    cfg_module._settings = None
    s1 = cfg_module.get_settings()
    s2 = cfg_module.get_settings()
    assert s1 is s2
    cfg_module._settings = None


def test_cors_origins_default():
    """Default CORS origins should allow all (["*"])."""
    settings = _make_settings()
    assert "*" in settings.cors_origins
