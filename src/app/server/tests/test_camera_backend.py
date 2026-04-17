"""
test_camera_backend.py — Unit tests for camera backend ABC and models.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Import checks — verify all public types are importable
# ---------------------------------------------------------------------------

def test_feature_enum_has_all_members():
    from server.services.camera_backends import Feature
    expected = {"exposure", "gain", "roi", "pixel_format",
                "frame_rate", "trigger", "temperature", "user_set"}
    assert {f.value for f in Feature} == expected


def test_error_hierarchy():
    from server.services.camera_backends import (
        CameraError, FeatureNotSupportedError,
        FeatureOutOfRangeError, CameraDisconnectedError,
        CameraTimeoutError, Feature, NumericRange,
    )
    e = FeatureNotSupportedError(Feature.EXPOSURE)
    assert isinstance(e, CameraError)
    assert e.feature == Feature.EXPOSURE

    r = NumericRange(min=20, max=10_000_000, step=1)
    e2 = FeatureOutOfRangeError(Feature.EXPOSURE, 999_999_999, r)
    assert isinstance(e2, CameraError)
    assert e2.requested == 999_999_999
    assert e2.valid_range.max == 10_000_000


def test_captured_frame_to_jpeg():
    import numpy as np
    from server.services.camera_backends import CapturedFrame, FrameMeta

    meta = FrameMeta(
        timestamp_us=0, exposure_us=1000, gain_db=0,
        temperature_c=25.0, fps_actual=30.0, width=64, height=64,
    )
    arr = np.zeros((64, 64), dtype=np.uint8)
    frame = CapturedFrame(array=arr, pixel_format="mono8", meta=meta)
    jpeg = frame.to_jpeg(quality=50)
    assert jpeg[:3] == b"\xff\xd8\xff"
    assert len(jpeg) > 50


def test_abc_cannot_instantiate():
    from server.services.camera_backends import CameraBackend
    with pytest.raises(TypeError):
        CameraBackend()


# ---------------------------------------------------------------------------
# MockCameraBackend tests
# ---------------------------------------------------------------------------

@pytest.fixture
async def mock_cam():
    from server.services.camera_backends.mock_backend import MockCameraBackend
    cam = MockCameraBackend()
    await cam.connect()
    yield cam
    await cam.disconnect()


async def test_mock_connect_returns_device_info(mock_cam):
    info = mock_cam.device_info()
    assert info.vendor == "Mock"
    assert info.model == "Alvium 1800 U-158m (Mock)"


async def test_mock_capabilities_all_supported(mock_cam):
    from server.services.camera_backends import Feature
    caps = mock_cam.capabilities()
    for f in Feature:
        assert caps[f].supported is True


async def test_mock_capture_returns_numpy_frame(mock_cam):
    import numpy as np
    frame = await mock_cam.capture()
    assert isinstance(frame.array, np.ndarray)
    assert frame.array.shape == (1088, 1456)
    assert frame.meta.width == 1456
    assert frame.meta.height == 1088


async def test_mock_exposure_manual(mock_cam):
    info = await mock_cam.set_exposure(auto=False, time_us=5000)
    assert info.auto is False
    assert info.time_us == 5000
    assert info.range.min == 20
    assert info.range.max == 10_000_000


async def test_mock_exposure_auto(mock_cam):
    info = await mock_cam.set_exposure(auto=True)
    assert info.auto is True
    assert info.auto_available is True


async def test_mock_exposure_out_of_range(mock_cam):
    from server.services.camera_backends import FeatureOutOfRangeError
    with pytest.raises(FeatureOutOfRangeError) as exc_info:
        await mock_cam.set_exposure(auto=False, time_us=999_999_999)
    assert exc_info.value.requested == 999_999_999


async def test_mock_gain_manual(mock_cam):
    info = await mock_cam.set_gain(auto=False, value_db=6.0)
    assert info.auto is False
    assert info.value_db == 6.0


async def test_mock_roi_set_and_get(mock_cam):
    info = await mock_cam.set_roi(width=800, height=600, offset_x=100, offset_y=50)
    assert info.width == 800
    assert info.height == 600
    assert info.offset_x == 100
    assert info.offset_y == 50


async def test_mock_roi_invalidates_frame_rate(mock_cam):
    from server.services.camera_backends import Feature
    info = await mock_cam.set_roi(width=800, height=600)
    assert Feature.FRAME_RATE in info.invalidated


async def test_mock_center_roi(mock_cam):
    await mock_cam.set_roi(width=800, height=600)
    info = await mock_cam.center_roi()
    assert info.offset_x == (1456 - 800) // 2
    assert info.offset_y == (1088 - 600) // 2


async def test_mock_pixel_format(mock_cam):
    info = await mock_cam.set_pixel_format(format="mono12")
    assert info.format == "mono12"
    assert "mono8" in info.available


async def test_mock_frame_rate(mock_cam):
    info = await mock_cam.set_frame_rate(enable=True, value=15.0)
    assert info.enable is True
    assert info.value == 15.0


async def test_mock_trigger_software(mock_cam):
    info = await mock_cam.set_trigger(mode="software")
    assert info.mode == "software"
    await mock_cam.fire_trigger()


async def test_mock_temperature(mock_cam):
    temp = await mock_cam.get_temperature()
    assert 30.0 <= temp <= 50.0


async def test_mock_userset_save_load(mock_cam):
    await mock_cam.set_exposure(auto=False, time_us=8000)
    await mock_cam.save_user_set(slot="UserSet1")
    await mock_cam.set_exposure(auto=False, time_us=1000)
    await mock_cam.load_user_set(slot="UserSet1")
    info = await mock_cam.get_exposure()
    assert info.time_us == 8000


async def test_mock_userset_info(mock_cam):
    info = await mock_cam.get_user_set_info()
    assert "Default" in info.available_slots
    assert "UserSet1" in info.available_slots


async def test_mock_status(mock_cam):
    status = await mock_cam.get_status()
    assert status.connected is True
    assert status.device is not None


async def test_mock_context_manager():
    from server.services.camera_backends.mock_backend import MockCameraBackend
    async with MockCameraBackend() as cam:
        frame = await cam.capture()
        assert frame.array is not None


async def test_mock_disconnected_raises():
    from server.services.camera_backends import CameraDisconnectedError
    from server.services.camera_backends.mock_backend import MockCameraBackend
    cam = MockCameraBackend()
    with pytest.raises(CameraDisconnectedError):
        await cam.capture()
