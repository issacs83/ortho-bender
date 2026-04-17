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
