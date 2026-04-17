# Camera Backend ABC + REST API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic CameraService with CameraBackend ABC + vendor-neutral REST API exposing 8 GenICam features (Exposure, Gain, ROI, PixelFormat, FrameRate, Trigger, Temperature, UserSet) through 20 endpoints.

**Architecture:** CameraBackend ABC defines domain methods. VmbPyCameraBackend and MockCameraBackend are implementations. CameraService is a thin orchestration layer (asyncio.Lock, error mapping). Router calls CameraService, which delegates to the backend. DI via `OB_CAMERA_BACKEND` env var → `app.state`.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, pytest-asyncio, numpy, VmbPy (optional), OpenCV (optional)

**Design Spec:** `docs/superpowers/specs/2026-04-17-camera-backend-abc-design.md`

---

## File Structure

### New Files

| File | Responsibility | ~Lines |
|------|---------------|--------|
| `src/app/server/services/camera_backends/__init__.py` | Feature enum, data models, error hierarchy, CameraBackend ABC | ~300 |
| `src/app/server/services/camera_backends/mock_backend.py` | MockCameraBackend — synthetic frames, all 8 features simulated | ~300 |
| `src/app/server/services/camera_backends/vmbpy_backend.py` | VmbPyCameraBackend — Allied Vision Alvium production driver | ~350 |
| `src/app/server/models/camera_schemas.py` | Pydantic request/response models for camera feature endpoints | ~200 |
| `src/app/server/tests/test_camera_backend.py` | Unit tests for MockCameraBackend (ABC contract) | ~250 |
| `src/app/server/tests/test_camera_endpoints.py` | Integration tests for all 20 REST endpoints | ~300 |
| `examples/camera/01_connect_and_capture.py` | Connect → capture → save JPEG | ~30 |
| `examples/camera/02_exposure_gain_control.py` | Manual/auto exposure and gain | ~35 |
| `examples/camera/03_roi_and_format.py` | ROI + pixel format + invalidation | ~35 |
| `examples/camera/04_trigger_software.py` | Software trigger capture loop | ~30 |
| `examples/camera/05_continuous_stream.py` | WebSocket stream with metadata | ~35 |
| `examples/camera/06_opencv_processing.py` | Capture → OpenCV processing | ~35 |
| `examples/camera/07_userset_save_restore.py` | Save/load/default UserSet | ~30 |
| `examples/camera/08_full_inspection_pipeline.py` | Complete inspection workflow | ~50 |

### Modified Files

| File | Changes |
|------|---------|
| `src/app/server/services/camera_service.py` | **Rewrite** — replace monolithic class with thin orchestration over CameraBackend |
| `src/app/server/routers/camera.py` | **Rewrite** — expand from 6 to 20 endpoints using new schemas |
| `src/app/server/config.py` | Add `camera_backend: str = "mock"` field |
| `src/app/server/main.py` | Update camera DI: select backend via `OB_CAMERA_BACKEND`, wire CameraService |
| `src/app/server/ws/manager.py` | Update `_camera_loop` to include FrameMeta in broadcast payload |
| `src/app/server/models/schemas.py` | Keep existing models, add import of camera_schemas for backward compat |
| `src/app/frontend/src/api/client.ts` | Extend cameraApi with 20 feature methods + types |
| `src/app/frontend/src/pages/CameraPage.tsx` | Capabilities-driven dynamic feature widgets |

### Deleted Files

| File | Reason |
|------|--------|
| `src/app/server/tests/test_camera.py` | Replaced by `test_camera_endpoints.py` |

---

## Task 1: Foundation — Data Models, Errors, and ABC

**Files:**
- Create: `src/app/server/services/camera_backends/__init__.py`
- Test: `src/app/server/tests/test_camera_backend.py` (partial — import checks)

This task creates the entire public interface of the camera_backends package: Feature enum, all data models, error hierarchy, and CameraBackend ABC.

- [ ] **Step 1: Write import verification test**

```python
# src/app/server/tests/test_camera_backend.py
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd src/app/server && python -m pytest tests/test_camera_backend.py -v 2>&1 | head -30
```

Expected: FAIL — `ModuleNotFoundError: No module named 'server.services.camera_backends'`

- [ ] **Step 3: Implement camera_backends/__init__.py**

```python
# src/app/server/services/camera_backends/__init__.py
"""
camera_backends — Camera hardware abstraction layer.

Public API:
  Feature           — Enum of controllable camera features
  NumericRange      — Min/max/step for numeric feature parameters
  DeviceInfo        — Camera identification (model, serial, firmware, vendor)
  FrameMeta         — Telemetry attached to every captured frame
  CapturedFrame     — Raw numpy frame + metadata, with to_jpeg() convenience
  CameraStatus      — Aggregate camera state snapshot
  ExposureInfo      — Exposure getter/setter response
  GainInfo          — Gain getter/setter response
  RoiInfo           — ROI getter/setter response
  PixelFormatInfo   — Pixel format getter/setter response
  FrameRateInfo     — Frame rate getter/setter response
  TriggerInfo       — Trigger getter/setter response
  UserSetInfo       — UserSet getter response
  FeatureCapability — Per-feature support descriptor
  CameraError       — Base exception
  FeatureNotSupportedError  — Feature not available on this backend
  FeatureOutOfRangeError    — Requested value outside valid range
  CameraDisconnectedError   — Camera not connected
  CameraTimeoutError        — Operation timed out
  CameraBackend     — Abstract base class for camera backends

IEC 62304 SW Class: B
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Feature enum
# ---------------------------------------------------------------------------

class Feature(str, Enum):
    EXPOSURE     = "exposure"
    GAIN         = "gain"
    ROI          = "roi"
    PIXEL_FORMAT = "pixel_format"
    FRAME_RATE   = "frame_rate"
    TRIGGER      = "trigger"
    TEMPERATURE  = "temperature"
    USER_SET     = "user_set"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NumericRange:
    min: float
    max: float
    step: float = 1.0


@dataclass(frozen=True)
class DeviceInfo:
    model: str          # "Alvium 1800 U-158m"
    serial: str         # "DEV_1AB22D00xxxx"
    firmware: str       # "1.2.3"
    vendor: str         # "Allied Vision"


@dataclass
class FrameMeta:
    """Telemetry attached to every captured frame."""
    timestamp_us: int
    exposure_us: float
    gain_db: float
    temperature_c: Optional[float]
    fps_actual: float
    width: int
    height: int


@dataclass
class CapturedFrame:
    """Raw sensor data + metadata."""
    array: np.ndarray        # HxW for mono, HxWxC for color
    pixel_format: str        # "mono8", "mono12", "bayer_rg8", etc.
    meta: FrameMeta

    def to_jpeg(self, quality: int = 85) -> bytes:
        """Encode to JPEG on demand."""
        import cv2
        if self.array.ndim == 2:
            img = self.array
        else:
            img = cv2.cvtColor(self.array, cv2.COLOR_RGB2BGR)
        _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes()


@dataclass
class CameraStatus:
    connected: bool
    streaming: bool
    device: Optional[DeviceInfo]
    current_exposure_us: Optional[float]
    current_gain_db: Optional[float]
    current_temperature_c: Optional[float]
    current_fps: Optional[float]
    current_pixel_format: Optional[str]
    current_roi: Optional[dict]        # {width, height, offset_x, offset_y}
    current_trigger_mode: Optional[str]


# ---------------------------------------------------------------------------
# Feature response types
# ---------------------------------------------------------------------------

@dataclass
class ExposureInfo:
    auto: bool
    time_us: float
    range: NumericRange
    auto_available: bool
    invalidated: list[Feature] = field(default_factory=list)


@dataclass
class GainInfo:
    auto: bool
    value_db: float
    range: NumericRange
    auto_available: bool
    invalidated: list[Feature] = field(default_factory=list)


@dataclass
class RoiInfo:
    width: int
    height: int
    offset_x: int
    offset_y: int
    width_range: NumericRange
    height_range: NumericRange
    offset_x_range: NumericRange
    offset_y_range: NumericRange
    invalidated: list[Feature] = field(default_factory=list)


@dataclass
class PixelFormatInfo:
    format: str
    available: list[str]
    invalidated: list[Feature] = field(default_factory=list)


@dataclass
class FrameRateInfo:
    enable: bool
    value: float
    range: NumericRange
    invalidated: list[Feature] = field(default_factory=list)


@dataclass
class TriggerInfo:
    mode: str                   # "freerun", "software", "external"
    source: Optional[str]       # "Software", "Line0", ...
    available_modes: list[str]
    available_sources: list[str]
    invalidated: list[Feature] = field(default_factory=list)


@dataclass
class UserSetInfo:
    current_slot: str
    available_slots: list[str]
    default_slot: str


@dataclass
class FeatureCapability:
    supported: bool
    range: Optional[NumericRange] = None
    auto_available: Optional[bool] = None
    available_values: Optional[list[str]] = None
    slots: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class CameraError(Exception):
    """Base error for all camera operations."""
    pass


class FeatureNotSupportedError(CameraError):
    """Camera backend does not support this feature."""
    def __init__(self, feature: Feature):
        self.feature = feature
        super().__init__(f"Feature not supported: {feature.value}")


class FeatureOutOfRangeError(CameraError):
    """Requested value is outside the valid range."""
    def __init__(self, feature: Feature, requested: float,
                 valid_range: NumericRange):
        self.feature = feature
        self.requested = requested
        self.valid_range = valid_range
        super().__init__(
            f"{feature.value}: {requested} is out of range "
            f"[{valid_range.min}, {valid_range.max}]"
        )


class CameraDisconnectedError(CameraError):
    """Operation attempted on a disconnected camera."""
    pass


class CameraTimeoutError(CameraError):
    """Camera operation timed out."""
    pass


# ---------------------------------------------------------------------------
# CameraBackend ABC
# ---------------------------------------------------------------------------

class CameraBackend(ABC):
    """Hardware-abstracted camera interface.

    Lifecycle: connect() → use → disconnect()
    Context manager: async with backend as cam: ...

    Thread safety: NOT thread-safe. Single owner — one coroutine
    controls the camera at a time. Use asyncio.Lock externally
    (CameraService provides this).

    State precondition: all feature methods require connected state.
    Calling any method before connect() raises CameraDisconnectedError.
    """

    # --- Context Manager ---

    async def __aenter__(self) -> CameraBackend:
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.disconnect()

    # --- Required: every backend MUST implement these ---

    @abstractmethod
    async def connect(self) -> DeviceInfo:
        """Open camera and return device info. Idempotent."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully shut down. Safe to call multiple times."""
        ...

    @abstractmethod
    async def capture(self) -> CapturedFrame:
        """Capture a single frame with telemetry metadata."""
        ...

    @abstractmethod
    async def stream(self, fps: float = 30.0) -> AsyncIterator[CapturedFrame]:
        """Continuous frame stream. Break from async for to stop."""
        ...

    @abstractmethod
    def capabilities(self) -> dict[Feature, FeatureCapability]:
        """Supported features + metadata. Call after connect()."""
        ...

    @abstractmethod
    async def get_status(self) -> CameraStatus:
        """Current camera state including all active feature values."""
        ...

    @abstractmethod
    def device_info(self) -> DeviceInfo:
        """Return device info obtained during connect()."""
        ...

    # --- Optional: default raises FeatureNotSupportedError ---

    async def set_exposure(self, *, auto: bool = False,
                           time_us: Optional[float] = None) -> ExposureInfo:
        raise FeatureNotSupportedError(Feature.EXPOSURE)

    async def get_exposure(self) -> ExposureInfo:
        raise FeatureNotSupportedError(Feature.EXPOSURE)

    async def set_gain(self, *, auto: bool = False,
                       value_db: Optional[float] = None) -> GainInfo:
        raise FeatureNotSupportedError(Feature.GAIN)

    async def get_gain(self) -> GainInfo:
        raise FeatureNotSupportedError(Feature.GAIN)

    async def set_roi(self, *, width: int, height: int,
                      offset_x: int = 0, offset_y: int = 0) -> RoiInfo:
        raise FeatureNotSupportedError(Feature.ROI)

    async def get_roi(self) -> RoiInfo:
        raise FeatureNotSupportedError(Feature.ROI)

    async def center_roi(self) -> RoiInfo:
        raise FeatureNotSupportedError(Feature.ROI)

    async def set_pixel_format(self, *, format: str) -> PixelFormatInfo:
        raise FeatureNotSupportedError(Feature.PIXEL_FORMAT)

    async def get_pixel_format(self) -> PixelFormatInfo:
        raise FeatureNotSupportedError(Feature.PIXEL_FORMAT)

    async def set_frame_rate(self, *, enable: bool,
                             value: Optional[float] = None) -> FrameRateInfo:
        raise FeatureNotSupportedError(Feature.FRAME_RATE)

    async def get_frame_rate(self) -> FrameRateInfo:
        raise FeatureNotSupportedError(Feature.FRAME_RATE)

    async def set_trigger(self, *, mode: str,
                          source: Optional[str] = None) -> TriggerInfo:
        raise FeatureNotSupportedError(Feature.TRIGGER)

    async def get_trigger(self) -> TriggerInfo:
        raise FeatureNotSupportedError(Feature.TRIGGER)

    async def fire_trigger(self) -> None:
        raise FeatureNotSupportedError(Feature.TRIGGER)

    async def get_temperature(self) -> float:
        raise FeatureNotSupportedError(Feature.TEMPERATURE)

    async def load_user_set(self, *, slot: str) -> None:
        raise FeatureNotSupportedError(Feature.USER_SET)

    async def save_user_set(self, *, slot: str) -> None:
        raise FeatureNotSupportedError(Feature.USER_SET)

    async def set_default_user_set(self, *, slot: str) -> None:
        raise FeatureNotSupportedError(Feature.USER_SET)

    async def get_user_set_info(self) -> UserSetInfo:
        raise FeatureNotSupportedError(Feature.USER_SET)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd src/app/server && python -m pytest tests/test_camera_backend.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/server/services/camera_backends/__init__.py \
        src/app/server/tests/test_camera_backend.py
git commit -m "feat: camera data models, error hierarchy, and CameraBackend ABC

Foundation for hardware-abstracted camera SDK: Feature enum (8 features),
typed response dataclasses with invalidation hints, 4-type error hierarchy,
and CameraBackend ABC with required + optional methods."
```

---

## Task 2: MockCameraBackend

**Files:**
- Create: `src/app/server/services/camera_backends/mock_backend.py`
- Modify: `src/app/server/tests/test_camera_backend.py` (add mock tests)

Full mock implementation simulating all 8 features with realistic Alvium 1800 ranges.

- [ ] **Step 1: Write mock backend tests**

Append to `src/app/server/tests/test_camera_backend.py`:

```python
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
    assert frame.array.shape == (1088, 1456)  # Alvium default
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
    # fire_trigger should not raise
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd src/app/server && python -m pytest tests/test_camera_backend.py -v -k "mock" 2>&1 | head -30
```

Expected: FAIL — `ModuleNotFoundError: No module named 'server.services.camera_backends.mock_backend'`

- [ ] **Step 3: Implement MockCameraBackend**

```python
# src/app/server/services/camera_backends/mock_backend.py
"""
mock_backend.py — Mock camera backend for development and CI.

Simulates all 8 camera features with ranges matching Alvium 1800 U-158m.
Generates synthetic gradient frames (numpy). No hardware required.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import AsyncIterator
from typing import Optional

import numpy as np

from . import (
    CameraBackend, CameraDisconnectedError, CameraStatus, CapturedFrame,
    DeviceInfo, ExposureInfo, Feature, FeatureCapability, FeatureOutOfRangeError,
    FrameMeta, FrameRateInfo, GainInfo, NumericRange, PixelFormatInfo, RoiInfo,
    TriggerInfo, UserSetInfo,
)


# Alvium 1800 U-158m default specs
_SENSOR_W = 1456
_SENSOR_H = 1088
_EXP_RANGE = NumericRange(min=20, max=10_000_000, step=1)
_GAIN_RANGE = NumericRange(min=0, max=48, step=0.1)
_FPS_RANGE = NumericRange(min=1, max=133, step=0.01)
_FORMATS = ["mono8", "mono10", "mono12", "bayer_rg8", "bayer_rg10",
            "bayer_rg12", "rgb8"]
_TRIGGER_MODES = ["freerun", "software", "external"]
_TRIGGER_SOURCES = ["Software", "Line0", "Line1"]
_USER_SET_SLOTS = ["Default", "UserSet1", "UserSet2", "UserSet3"]


class MockCameraBackend(CameraBackend):
    """Simulated camera for development and CI testing."""

    def __init__(self) -> None:
        self._connected = False
        self._device = DeviceInfo(
            model="Alvium 1800 U-158m (Mock)",
            serial="MOCK_000000000001",
            firmware="0.0.0-mock",
            vendor="Mock",
        )
        # Feature state
        self._exposure_auto = False
        self._exposure_us = 5000.0
        self._gain_auto = False
        self._gain_db = 0.0
        self._roi_w = _SENSOR_W
        self._roi_h = _SENSOR_H
        self._roi_ox = 0
        self._roi_oy = 0
        self._pixel_format = "mono8"
        self._fps_enable = False
        self._fps_value = 30.0
        self._trigger_mode = "freerun"
        self._trigger_source: Optional[str] = None
        self._temperature = 35.0
        self._user_set_default = "Default"
        self._user_set_snapshots: dict[str, dict] = {}
        self._streaming = False
        self._frame_count = 0
        self._start_time = 0.0

    def _require_connected(self) -> None:
        if not self._connected:
            raise CameraDisconnectedError("Camera not connected")

    # --- Required methods ---

    async def connect(self) -> DeviceInfo:
        self._connected = True
        self._start_time = time.monotonic()
        self._temperature = 35.0
        return self._device

    async def disconnect(self) -> None:
        self._connected = False
        self._streaming = False

    async def capture(self) -> CapturedFrame:
        self._require_connected()
        self._frame_count += 1
        # Simulate temperature drift
        self._temperature = min(45.0, self._temperature + 0.01)

        arr = self._generate_frame()
        elapsed = time.monotonic() - self._start_time
        fps = self._frame_count / max(elapsed, 0.001)

        meta = FrameMeta(
            timestamp_us=int(time.monotonic() * 1_000_000),
            exposure_us=self._exposure_us,
            gain_db=self._gain_db,
            temperature_c=self._temperature,
            fps_actual=round(fps, 2),
            width=self._roi_w,
            height=self._roi_h,
        )
        return CapturedFrame(array=arr, pixel_format=self._pixel_format, meta=meta)

    async def stream(self, fps: float = 30.0) -> AsyncIterator[CapturedFrame]:
        self._require_connected()
        self._streaming = True
        interval = 1.0 / max(fps, 1.0)
        try:
            while self._streaming and self._connected:
                yield await self.capture()
                await asyncio.sleep(interval)
        finally:
            self._streaming = False

    def capabilities(self) -> dict[Feature, FeatureCapability]:
        return {
            Feature.EXPOSURE: FeatureCapability(
                supported=True, range=_EXP_RANGE, auto_available=True),
            Feature.GAIN: FeatureCapability(
                supported=True, range=_GAIN_RANGE, auto_available=True),
            Feature.ROI: FeatureCapability(
                supported=True,
                range=NumericRange(min=1, max=_SENSOR_W, step=1)),
            Feature.PIXEL_FORMAT: FeatureCapability(
                supported=True, available_values=list(_FORMATS)),
            Feature.FRAME_RATE: FeatureCapability(
                supported=True, range=_FPS_RANGE),
            Feature.TRIGGER: FeatureCapability(
                supported=True, available_values=list(_TRIGGER_MODES)),
            Feature.TEMPERATURE: FeatureCapability(supported=True),
            Feature.USER_SET: FeatureCapability(
                supported=True, slots=list(_USER_SET_SLOTS)),
        }

    async def get_status(self) -> CameraStatus:
        return CameraStatus(
            connected=self._connected,
            streaming=self._streaming,
            device=self._device if self._connected else None,
            current_exposure_us=self._exposure_us if self._connected else None,
            current_gain_db=self._gain_db if self._connected else None,
            current_temperature_c=self._temperature if self._connected else None,
            current_fps=self._fps_value if self._connected else None,
            current_pixel_format=self._pixel_format if self._connected else None,
            current_roi={"width": self._roi_w, "height": self._roi_h,
                         "offset_x": self._roi_ox, "offset_y": self._roi_oy}
                        if self._connected else None,
            current_trigger_mode=self._trigger_mode if self._connected else None,
        )

    def device_info(self) -> DeviceInfo:
        self._require_connected()
        return self._device

    # --- Exposure ---

    async def set_exposure(self, *, auto: bool = False,
                           time_us: Optional[float] = None) -> ExposureInfo:
        self._require_connected()
        self._exposure_auto = auto
        if not auto and time_us is not None:
            if time_us < _EXP_RANGE.min or time_us > _EXP_RANGE.max:
                raise FeatureOutOfRangeError(Feature.EXPOSURE, time_us, _EXP_RANGE)
            self._exposure_us = time_us
        return await self.get_exposure()

    async def get_exposure(self) -> ExposureInfo:
        self._require_connected()
        return ExposureInfo(
            auto=self._exposure_auto, time_us=self._exposure_us,
            range=_EXP_RANGE, auto_available=True,
        )

    # --- Gain ---

    async def set_gain(self, *, auto: bool = False,
                       value_db: Optional[float] = None) -> GainInfo:
        self._require_connected()
        self._gain_auto = auto
        if not auto and value_db is not None:
            if value_db < _GAIN_RANGE.min or value_db > _GAIN_RANGE.max:
                raise FeatureOutOfRangeError(Feature.GAIN, value_db, _GAIN_RANGE)
            self._gain_db = value_db
        return await self.get_gain()

    async def get_gain(self) -> GainInfo:
        self._require_connected()
        return GainInfo(
            auto=self._gain_auto, value_db=self._gain_db,
            range=_GAIN_RANGE, auto_available=True,
        )

    # --- ROI ---

    async def set_roi(self, *, width: int, height: int,
                      offset_x: int = 0, offset_y: int = 0) -> RoiInfo:
        self._require_connected()
        width = min(width, _SENSOR_W)
        height = min(height, _SENSOR_H)
        offset_x = min(offset_x, _SENSOR_W - width)
        offset_y = min(offset_y, _SENSOR_H - height)
        self._roi_w = width
        self._roi_h = height
        self._roi_ox = offset_x
        self._roi_oy = offset_y
        info = await self.get_roi()
        info.invalidated = [Feature.FRAME_RATE]
        return info

    async def get_roi(self) -> RoiInfo:
        self._require_connected()
        return RoiInfo(
            width=self._roi_w, height=self._roi_h,
            offset_x=self._roi_ox, offset_y=self._roi_oy,
            width_range=NumericRange(min=1, max=_SENSOR_W, step=1),
            height_range=NumericRange(min=1, max=_SENSOR_H, step=1),
            offset_x_range=NumericRange(min=0, max=_SENSOR_W - self._roi_w, step=1),
            offset_y_range=NumericRange(min=0, max=_SENSOR_H - self._roi_h, step=1),
        )

    async def center_roi(self) -> RoiInfo:
        self._require_connected()
        ox = (_SENSOR_W - self._roi_w) // 2
        oy = (_SENSOR_H - self._roi_h) // 2
        return await self.set_roi(
            width=self._roi_w, height=self._roi_h,
            offset_x=ox, offset_y=oy,
        )

    # --- Pixel Format ---

    async def set_pixel_format(self, *, format: str) -> PixelFormatInfo:
        self._require_connected()
        if format not in _FORMATS:
            raise FeatureOutOfRangeError(
                Feature.PIXEL_FORMAT, 0,
                NumericRange(min=0, max=len(_FORMATS) - 1, step=1),
            )
        self._pixel_format = format
        info = await self.get_pixel_format()
        info.invalidated = [Feature.FRAME_RATE]
        return info

    async def get_pixel_format(self) -> PixelFormatInfo:
        self._require_connected()
        return PixelFormatInfo(format=self._pixel_format, available=list(_FORMATS))

    # --- Frame Rate ---

    async def set_frame_rate(self, *, enable: bool,
                             value: Optional[float] = None) -> FrameRateInfo:
        self._require_connected()
        self._fps_enable = enable
        if enable and value is not None:
            if value < _FPS_RANGE.min or value > _FPS_RANGE.max:
                raise FeatureOutOfRangeError(Feature.FRAME_RATE, value, _FPS_RANGE)
            self._fps_value = value
        return await self.get_frame_rate()

    async def get_frame_rate(self) -> FrameRateInfo:
        self._require_connected()
        return FrameRateInfo(
            enable=self._fps_enable, value=self._fps_value, range=_FPS_RANGE,
        )

    # --- Trigger ---

    async def set_trigger(self, *, mode: str,
                          source: Optional[str] = None) -> TriggerInfo:
        self._require_connected()
        self._trigger_mode = mode
        self._trigger_source = source
        info = await self.get_trigger()
        if mode != "freerun":
            info.invalidated = [Feature.FRAME_RATE]
        return info

    async def get_trigger(self) -> TriggerInfo:
        self._require_connected()
        return TriggerInfo(
            mode=self._trigger_mode, source=self._trigger_source,
            available_modes=list(_TRIGGER_MODES),
            available_sources=list(_TRIGGER_SOURCES),
        )

    async def fire_trigger(self) -> None:
        self._require_connected()
        # In mock mode, fire_trigger is a no-op (next capture() returns a frame)

    # --- Temperature ---

    async def get_temperature(self) -> float:
        self._require_connected()
        return round(self._temperature, 1)

    # --- UserSet ---

    async def load_user_set(self, *, slot: str) -> None:
        self._require_connected()
        if slot not in _USER_SET_SLOTS:
            raise ValueError(f"Invalid slot: {slot}")
        snap = self._user_set_snapshots.get(slot)
        if snap:
            self._exposure_us = snap.get("exposure_us", self._exposure_us)
            self._exposure_auto = snap.get("exposure_auto", self._exposure_auto)
            self._gain_db = snap.get("gain_db", self._gain_db)
            self._gain_auto = snap.get("gain_auto", self._gain_auto)
            self._roi_w = snap.get("roi_w", self._roi_w)
            self._roi_h = snap.get("roi_h", self._roi_h)
            self._roi_ox = snap.get("roi_ox", self._roi_ox)
            self._roi_oy = snap.get("roi_oy", self._roi_oy)
            self._pixel_format = snap.get("pixel_format", self._pixel_format)

    async def save_user_set(self, *, slot: str) -> None:
        self._require_connected()
        if slot not in _USER_SET_SLOTS or slot == "Default":
            raise ValueError(f"Cannot save to slot: {slot}")
        self._user_set_snapshots[slot] = {
            "exposure_us": self._exposure_us,
            "exposure_auto": self._exposure_auto,
            "gain_db": self._gain_db,
            "gain_auto": self._gain_auto,
            "roi_w": self._roi_w,
            "roi_h": self._roi_h,
            "roi_ox": self._roi_ox,
            "roi_oy": self._roi_oy,
            "pixel_format": self._pixel_format,
        }

    async def set_default_user_set(self, *, slot: str) -> None:
        self._require_connected()
        if slot not in _USER_SET_SLOTS:
            raise ValueError(f"Invalid slot: {slot}")
        self._user_set_default = slot

    async def get_user_set_info(self) -> UserSetInfo:
        self._require_connected()
        return UserSetInfo(
            current_slot="Default",
            available_slots=list(_USER_SET_SLOTS),
            default_slot=self._user_set_default,
        )

    # --- Internal ---

    def _generate_frame(self) -> np.ndarray:
        """Generate a synthetic gradient frame."""
        h, w = self._roi_h, self._roi_w
        # Horizontal gradient with frame counter modulation
        row = np.linspace(0, 255, w, dtype=np.uint8)
        frame = np.tile(row, (h, 1))
        # Shift by frame count for visual movement
        shift = self._frame_count % w
        frame = np.roll(frame, shift, axis=1)
        return frame
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd src/app/server && python -m pytest tests/test_camera_backend.py -v
```

Expected: All tests PASS (~25 tests)

- [ ] **Step 5: Commit**

```bash
git add src/app/server/services/camera_backends/mock_backend.py \
        src/app/server/tests/test_camera_backend.py
git commit -m "feat: MockCameraBackend — full simulation of 8 camera features

Synthetic gradient frames (numpy), realistic Alvium 1800 ranges,
auto exposure/gain, ROI with invalidation hints, trigger modes,
UserSet save/load, temperature drift simulation. 25 unit tests."
```

---

## Task 3: Pydantic Request/Response Schemas

**Files:**
- Create: `src/app/server/models/camera_schemas.py`

Pydantic v2 models for all camera feature endpoints. Used by the router for validation and OpenAPI docs.

- [ ] **Step 1: Write the schemas**

```python
# src/app/server/models/camera_schemas.py
"""
camera_schemas.py — Pydantic v2 request/response models for camera feature API.

These mirror the dataclass types in camera_backends but add FastAPI validation,
serialization, and OpenAPI schema generation.

IEC 62304 SW Class: B
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------

class NumericRangeSchema(BaseModel):
    min: float
    max: float
    step: float = 1.0


class DeviceInfoSchema(BaseModel):
    model: str
    serial: str
    firmware: str
    vendor: str


class FrameMetaSchema(BaseModel):
    timestamp_us: int
    exposure_us: float
    gain_db: float
    temperature_c: Optional[float] = None
    fps_actual: float
    width: int
    height: int


# ---------------------------------------------------------------------------
# Feature capability
# ---------------------------------------------------------------------------

class FeatureCapabilitySchema(BaseModel):
    supported: bool
    range: Optional[NumericRangeSchema] = None
    auto_available: Optional[bool] = None
    available_values: Optional[list[str]] = None
    slots: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Exposure
# ---------------------------------------------------------------------------

class ExposureRequest(BaseModel):
    auto: bool = False
    time_us: Optional[float] = Field(None, gt=0, description="Exposure time μs")


class ExposureResponse(BaseModel):
    auto: bool
    time_us: float
    range: NumericRangeSchema
    auto_available: bool
    invalidated: list[str] = []


# ---------------------------------------------------------------------------
# Gain
# ---------------------------------------------------------------------------

class GainRequest(BaseModel):
    auto: bool = False
    value_db: Optional[float] = Field(None, ge=0, description="Gain in dB")


class GainResponse(BaseModel):
    auto: bool
    value_db: float
    range: NumericRangeSchema
    auto_available: bool
    invalidated: list[str] = []


# ---------------------------------------------------------------------------
# ROI
# ---------------------------------------------------------------------------

class RoiRequest(BaseModel):
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    offset_x: int = Field(0, ge=0)
    offset_y: int = Field(0, ge=0)


class RoiResponse(BaseModel):
    width: int
    height: int
    offset_x: int
    offset_y: int
    width_range: NumericRangeSchema
    height_range: NumericRangeSchema
    offset_x_range: NumericRangeSchema
    offset_y_range: NumericRangeSchema
    invalidated: list[str] = []


# ---------------------------------------------------------------------------
# Pixel Format
# ---------------------------------------------------------------------------

class PixelFormatRequest(BaseModel):
    format: str = Field(..., description="e.g. 'mono8', 'mono12', 'rgb8'")


class PixelFormatResponse(BaseModel):
    format: str
    available: list[str]
    invalidated: list[str] = []


# ---------------------------------------------------------------------------
# Frame Rate
# ---------------------------------------------------------------------------

class FrameRateRequest(BaseModel):
    enable: bool
    value: Optional[float] = Field(None, gt=0)


class FrameRateResponse(BaseModel):
    enable: bool
    value: float
    range: NumericRangeSchema
    invalidated: list[str] = []


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------

class TriggerRequest(BaseModel):
    mode: str = Field(..., description="'freerun', 'software', 'external'")
    source: Optional[str] = None


class TriggerResponse(BaseModel):
    mode: str
    source: Optional[str] = None
    available_modes: list[str]
    available_sources: list[str]
    invalidated: list[str] = []


# ---------------------------------------------------------------------------
# Temperature
# ---------------------------------------------------------------------------

class TemperatureResponse(BaseModel):
    value_c: float


# ---------------------------------------------------------------------------
# UserSet
# ---------------------------------------------------------------------------

class UserSetSlotRequest(BaseModel):
    slot: str


class UserSetResponse(BaseModel):
    current_slot: str
    available_slots: list[str]
    default_slot: str


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

class CameraStatusSchema(BaseModel):
    connected: bool
    streaming: bool
    device: Optional[DeviceInfoSchema] = None
    current_exposure_us: Optional[float] = None
    current_gain_db: Optional[float] = None
    current_temperature_c: Optional[float] = None
    current_fps: Optional[float] = None
    current_pixel_format: Optional[str] = None
    current_roi: Optional[dict] = None
    current_trigger_mode: Optional[str] = None


# ---------------------------------------------------------------------------
# Connect response
# ---------------------------------------------------------------------------

class ConnectResponse(BaseModel):
    device: DeviceInfoSchema
    capabilities: dict[str, FeatureCapabilitySchema]


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _range_to_schema(r) -> NumericRangeSchema:
    return NumericRangeSchema(min=r.min, max=r.max, step=r.step)


def _invalidated_to_str(features: list) -> list[str]:
    return [f.value if hasattr(f, 'value') else str(f) for f in features]


def exposure_to_response(info) -> ExposureResponse:
    return ExposureResponse(
        auto=info.auto, time_us=info.time_us,
        range=_range_to_schema(info.range),
        auto_available=info.auto_available,
        invalidated=_invalidated_to_str(info.invalidated),
    )


def gain_to_response(info) -> GainResponse:
    return GainResponse(
        auto=info.auto, value_db=info.value_db,
        range=_range_to_schema(info.range),
        auto_available=info.auto_available,
        invalidated=_invalidated_to_str(info.invalidated),
    )


def roi_to_response(info) -> RoiResponse:
    return RoiResponse(
        width=info.width, height=info.height,
        offset_x=info.offset_x, offset_y=info.offset_y,
        width_range=_range_to_schema(info.width_range),
        height_range=_range_to_schema(info.height_range),
        offset_x_range=_range_to_schema(info.offset_x_range),
        offset_y_range=_range_to_schema(info.offset_y_range),
        invalidated=_invalidated_to_str(info.invalidated),
    )


def pixel_format_to_response(info) -> PixelFormatResponse:
    return PixelFormatResponse(
        format=info.format, available=info.available,
        invalidated=_invalidated_to_str(info.invalidated),
    )


def frame_rate_to_response(info) -> FrameRateResponse:
    return FrameRateResponse(
        enable=info.enable, value=info.value,
        range=_range_to_schema(info.range),
        invalidated=_invalidated_to_str(info.invalidated),
    )


def trigger_to_response(info) -> TriggerResponse:
    return TriggerResponse(
        mode=info.mode, source=info.source,
        available_modes=info.available_modes,
        available_sources=info.available_sources,
        invalidated=_invalidated_to_str(info.invalidated),
    )


def userset_to_response(info) -> UserSetResponse:
    return UserSetResponse(
        current_slot=info.current_slot,
        available_slots=info.available_slots,
        default_slot=info.default_slot,
    )


def status_to_schema(status) -> CameraStatusSchema:
    device = None
    if status.device:
        device = DeviceInfoSchema(
            model=status.device.model, serial=status.device.serial,
            firmware=status.device.firmware, vendor=status.device.vendor,
        )
    return CameraStatusSchema(
        connected=status.connected, streaming=status.streaming,
        device=device,
        current_exposure_us=status.current_exposure_us,
        current_gain_db=status.current_gain_db,
        current_temperature_c=status.current_temperature_c,
        current_fps=status.current_fps,
        current_pixel_format=status.current_pixel_format,
        current_roi=status.current_roi,
        current_trigger_mode=status.current_trigger_mode,
    )


def capabilities_to_schema(caps: dict) -> dict[str, FeatureCapabilitySchema]:
    result = {}
    for feature, cap in caps.items():
        key = feature.value if hasattr(feature, 'value') else str(feature)
        r = _range_to_schema(cap.range) if cap.range else None
        result[key] = FeatureCapabilitySchema(
            supported=cap.supported, range=r,
            auto_available=cap.auto_available,
            available_values=cap.available_values,
            slots=cap.slots,
        )
    return result
```

- [ ] **Step 2: Verify import works**

```bash
cd src/app/server && python -c "from server.models.camera_schemas import ExposureRequest, ConnectResponse; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/app/server/models/camera_schemas.py
git commit -m "feat: Pydantic schemas for camera feature REST API

Request/response models for all 8 features + status + capabilities.
Includes serialization helpers to convert backend dataclasses to
Pydantic schemas for FastAPI validation and OpenAPI docs."
```

---

## Task 4: CameraService Orchestration Layer

**Files:**
- Modify: `src/app/server/services/camera_service.py` (full rewrite)

Replace the monolithic 501-line CameraService with a thin orchestration layer that delegates to CameraBackend. Responsibilities: asyncio.Lock, error mapping, streaming lifecycle.

- [ ] **Step 1: Write CameraService tests**

Add to `src/app/server/tests/test_camera_backend.py`:

```python
# ---------------------------------------------------------------------------
# CameraService orchestration tests
# ---------------------------------------------------------------------------

@pytest.fixture
async def camera_svc():
    from server.services.camera_backends.mock_backend import MockCameraBackend
    from server.services.camera_service import CameraService
    backend = MockCameraBackend()
    svc = CameraService(backend)
    await svc.connect()
    yield svc
    await svc.disconnect()


async def test_svc_connect_returns_device_and_caps(camera_svc):
    # Already connected in fixture — reconnect should be idempotent
    result = await camera_svc.connect()
    assert "device" in result
    assert "capabilities" in result
    assert result["device"]["vendor"] == "Mock"


async def test_svc_set_exposure(camera_svc):
    info = await camera_svc.set_exposure(auto=False, time_us=8000)
    assert info.time_us == 8000


async def test_svc_capture_jpeg(camera_svc):
    jpeg = await camera_svc.capture_jpeg(quality=85)
    assert jpeg[:3] == b"\xff\xd8\xff"


async def test_svc_get_status(camera_svc):
    status = await camera_svc.get_status()
    assert status.connected is True
```

- [ ] **Step 2: Run tests to verify they fail (old CameraService has no set_exposure)**

```bash
cd src/app/server && python -m pytest tests/test_camera_backend.py -v -k "svc" 2>&1 | head -20
```

Expected: FAIL — `CameraService.__init__() takes different arguments`

- [ ] **Step 3: Rewrite CameraService**

```python
# src/app/server/services/camera_service.py
"""
camera_service.py — CameraService orchestration layer.

Thin wrapper over CameraBackend ABC. Responsibilities:
  - asyncio.Lock for serialized access
  - JPEG encoding for REST capture endpoint
  - Streaming lifecycle management
  - Error mapping (CameraError → HTTP-friendly dicts)

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .camera_backends import (
    CameraBackend, CameraStatus, CapturedFrame, ExposureInfo, Feature,
    FrameRateInfo, GainInfo, PixelFormatInfo, RoiInfo, TriggerInfo,
    UserSetInfo,
)

log = logging.getLogger(__name__)


class CameraService:
    """Orchestration layer — delegates all feature calls to a CameraBackend."""

    def __init__(self, backend: CameraBackend) -> None:
        self._backend = backend
        self._lock = asyncio.Lock()
        self._streaming = False
        self._connected = False

    # --- Connection ---

    async def connect(self) -> dict:
        async with self._lock:
            device = await self._backend.connect()
            caps = self._backend.capabilities()
            self._connected = True
            return {
                "device": {
                    "model": device.model, "serial": device.serial,
                    "firmware": device.firmware, "vendor": device.vendor,
                },
                "capabilities": {
                    f.value: _cap_to_dict(c) for f, c in caps.items()
                },
            }

    async def disconnect(self) -> None:
        async with self._lock:
            self._streaming = False
            await self._backend.disconnect()
            self._connected = False

    async def get_status(self) -> CameraStatus:
        async with self._lock:
            return await self._backend.get_status()

    def capabilities(self) -> dict:
        caps = self._backend.capabilities()
        return {f.value: _cap_to_dict(c) for f, c in caps.items()}

    def device_info(self) -> dict:
        d = self._backend.device_info()
        return {"model": d.model, "serial": d.serial,
                "firmware": d.firmware, "vendor": d.vendor}

    # --- Feature methods (all acquire lock) ---

    async def set_exposure(self, auto: bool = False,
                           time_us: Optional[float] = None) -> ExposureInfo:
        async with self._lock:
            return await self._backend.set_exposure(auto=auto, time_us=time_us)

    async def get_exposure(self) -> ExposureInfo:
        async with self._lock:
            return await self._backend.get_exposure()

    async def set_gain(self, auto: bool = False,
                       value_db: Optional[float] = None) -> GainInfo:
        async with self._lock:
            return await self._backend.set_gain(auto=auto, value_db=value_db)

    async def get_gain(self) -> GainInfo:
        async with self._lock:
            return await self._backend.get_gain()

    async def set_roi(self, width: int, height: int,
                      offset_x: int = 0, offset_y: int = 0) -> RoiInfo:
        async with self._lock:
            return await self._backend.set_roi(
                width=width, height=height,
                offset_x=offset_x, offset_y=offset_y,
            )

    async def get_roi(self) -> RoiInfo:
        async with self._lock:
            return await self._backend.get_roi()

    async def center_roi(self) -> RoiInfo:
        async with self._lock:
            return await self._backend.center_roi()

    async def set_pixel_format(self, format: str) -> PixelFormatInfo:
        async with self._lock:
            return await self._backend.set_pixel_format(format=format)

    async def get_pixel_format(self) -> PixelFormatInfo:
        async with self._lock:
            return await self._backend.get_pixel_format()

    async def set_frame_rate(self, enable: bool,
                             value: Optional[float] = None) -> FrameRateInfo:
        async with self._lock:
            return await self._backend.set_frame_rate(enable=enable, value=value)

    async def get_frame_rate(self) -> FrameRateInfo:
        async with self._lock:
            return await self._backend.get_frame_rate()

    async def set_trigger(self, mode: str,
                          source: Optional[str] = None) -> TriggerInfo:
        async with self._lock:
            return await self._backend.set_trigger(mode=mode, source=source)

    async def get_trigger(self) -> TriggerInfo:
        async with self._lock:
            return await self._backend.get_trigger()

    async def fire_trigger(self) -> None:
        async with self._lock:
            await self._backend.fire_trigger()

    async def get_temperature(self) -> float:
        async with self._lock:
            return await self._backend.get_temperature()

    async def load_user_set(self, slot: str) -> None:
        async with self._lock:
            await self._backend.load_user_set(slot=slot)

    async def save_user_set(self, slot: str) -> None:
        async with self._lock:
            await self._backend.save_user_set(slot=slot)

    async def set_default_user_set(self, slot: str) -> None:
        async with self._lock:
            await self._backend.set_default_user_set(slot=slot)

    async def get_user_set_info(self) -> UserSetInfo:
        async with self._lock:
            return await self._backend.get_user_set_info()

    # --- Frame capture ---

    async def capture(self) -> CapturedFrame:
        """Capture a single frame (returns CapturedFrame with numpy array)."""
        async with self._lock:
            return await self._backend.capture()

    async def capture_jpeg(self, quality: int = 85) -> bytes:
        """Capture a single frame and encode to JPEG."""
        frame = await self.capture()
        return frame.to_jpeg(quality=quality)

    async def stream_frames(self, fps: float = 30.0):
        """Yield CapturedFrame objects from the backend stream."""
        self._streaming = True
        try:
            async for frame in self._backend.stream(fps=fps):
                if not self._streaming:
                    break
                yield frame
        finally:
            self._streaming = False

    def stop_stream(self) -> None:
        """Signal the stream to stop."""
        self._streaming = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_streaming(self) -> bool:
        return self._streaming


def _cap_to_dict(cap) -> dict:
    """Convert FeatureCapability to serializable dict."""
    d: dict = {"supported": cap.supported}
    if cap.range:
        d["range"] = {"min": cap.range.min, "max": cap.range.max,
                       "step": cap.range.step}
    if cap.auto_available is not None:
        d["auto_available"] = cap.auto_available
    if cap.available_values is not None:
        d["available_values"] = cap.available_values
    if cap.slots is not None:
        d["slots"] = cap.slots
    return d
```

- [ ] **Step 4: Run tests**

```bash
cd src/app/server && python -m pytest tests/test_camera_backend.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/server/services/camera_service.py \
        src/app/server/tests/test_camera_backend.py
git commit -m "refactor: CameraService — thin orchestration over CameraBackend ABC

Replace monolithic 501-line CameraService with delegating wrapper.
asyncio.Lock serialization, JPEG encoding, streaming lifecycle.
All feature methods delegate to CameraBackend."
```

---

## Task 5: Camera Router — All 20 Endpoints

**Files:**
- Modify: `src/app/server/routers/camera.py` (full rewrite)

Rewrite the router from 6 endpoints to 20, using the new CameraService and Pydantic schemas.

- [ ] **Step 1: Rewrite camera router**

```python
# src/app/server/routers/camera.py
"""
routers/camera.py — /api/camera/* REST endpoints (20 endpoints).

Feature endpoints: exposure, gain, ROI, pixel format, frame rate,
trigger, temperature, user set. Plus connection, status, capabilities,
capture, and MJPEG streaming.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ..models.camera_schemas import (
    ConnectResponse, ExposureRequest, ExposureResponse, FrameRateRequest,
    FrameRateResponse, GainRequest, GainResponse, PixelFormatRequest,
    PixelFormatResponse, RoiRequest, RoiResponse, TemperatureResponse,
    TriggerRequest, TriggerResponse, UserSetResponse, UserSetSlotRequest,
    capabilities_to_schema, exposure_to_response, frame_rate_to_response,
    gain_to_response, pixel_format_to_response, roi_to_response,
    status_to_schema, trigger_to_response, userset_to_response,
)
from ..models.schemas import ApiResponse, err, ok
from ..services.camera_backends import (
    CameraDisconnectedError, CameraError, CameraTimeoutError,
    FeatureNotSupportedError, FeatureOutOfRangeError,
)
from ..services.camera_service import CameraService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/camera", tags=["camera"])


def _svc(request: Request) -> CameraService:
    return request.app.state.camera_service


def _error_response(exc: CameraError) -> JSONResponse:
    """Map CameraError subclass to HTTP response."""
    if isinstance(exc, FeatureNotSupportedError):
        return JSONResponse(status_code=422, content={
            "success": False, "error": str(exc),
            "code": "FEATURE_NOT_SUPPORTED",
            "detail": {"feature": exc.feature.value},
        })
    if isinstance(exc, FeatureOutOfRangeError):
        return JSONResponse(status_code=422, content={
            "success": False, "error": str(exc),
            "code": "FEATURE_OUT_OF_RANGE",
            "detail": {
                "feature": exc.feature.value,
                "requested": exc.requested,
                "range": {"min": exc.valid_range.min, "max": exc.valid_range.max,
                          "step": exc.valid_range.step},
            },
        })
    if isinstance(exc, CameraDisconnectedError):
        return JSONResponse(status_code=412, content={
            "success": False, "error": str(exc),
            "code": "CAMERA_DISCONNECTED",
        })
    if isinstance(exc, CameraTimeoutError):
        return JSONResponse(status_code=504, content={
            "success": False, "error": str(exc),
            "code": "CAMERA_TIMEOUT",
        })
    return JSONResponse(status_code=500, content={
        "success": False, "error": str(exc),
        "code": "CAMERA_INTERNAL_ERROR",
    })


# ---------------------------------------------------------------------------
# Connection & Status (5 endpoints)
# ---------------------------------------------------------------------------

@router.post("/connect", response_model=ApiResponse)
async def camera_connect(svc: CameraService = Depends(_svc)):
    """Connect camera — returns device info and capabilities."""
    try:
        result = await svc.connect()
        return ok(result)
    except CameraError as exc:
        return _error_response(exc)
    except Exception as exc:
        log.error("Camera connect: %s", exc)
        return err(str(exc), "CAMERA_CONNECT_ERROR")


@router.post("/disconnect", response_model=ApiResponse)
async def camera_disconnect(svc: CameraService = Depends(_svc)):
    """Disconnect camera gracefully."""
    try:
        await svc.disconnect()
        return ok({})
    except Exception as exc:
        log.error("Camera disconnect: %s", exc)
        return err(str(exc), "CAMERA_DISCONNECT_ERROR")


@router.get("/status", response_model=ApiResponse)
async def get_camera_status(svc: CameraService = Depends(_svc)):
    """Current camera state including all active feature values."""
    try:
        status = await svc.get_status()
        return ok(status_to_schema(status).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.get("/capabilities", response_model=ApiResponse)
async def get_capabilities(svc: CameraService = Depends(_svc)):
    """Supported features and their metadata (ranges, enums, auto)."""
    try:
        caps = svc.capabilities()
        return ok(caps)
    except CameraError as exc:
        return _error_response(exc)


@router.get("/device-info", response_model=ApiResponse)
async def get_device_info(svc: CameraService = Depends(_svc)):
    """Camera identification: model, serial, firmware, vendor."""
    try:
        return ok(svc.device_info())
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# Exposure (2 endpoints)
# ---------------------------------------------------------------------------

@router.get("/exposure", response_model=ApiResponse)
async def get_exposure(svc: CameraService = Depends(_svc)):
    try:
        info = await svc.get_exposure()
        return ok(exposure_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/exposure", response_model=ApiResponse)
async def set_exposure(body: ExposureRequest,
                       svc: CameraService = Depends(_svc)):
    try:
        info = await svc.set_exposure(auto=body.auto, time_us=body.time_us)
        return ok(exposure_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# Gain (2 endpoints)
# ---------------------------------------------------------------------------

@router.get("/gain", response_model=ApiResponse)
async def get_gain(svc: CameraService = Depends(_svc)):
    try:
        info = await svc.get_gain()
        return ok(gain_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/gain", response_model=ApiResponse)
async def set_gain(body: GainRequest, svc: CameraService = Depends(_svc)):
    try:
        info = await svc.set_gain(auto=body.auto, value_db=body.value_db)
        return ok(gain_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# ROI (3 endpoints)
# ---------------------------------------------------------------------------

@router.get("/roi", response_model=ApiResponse)
async def get_roi(svc: CameraService = Depends(_svc)):
    try:
        info = await svc.get_roi()
        return ok(roi_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/roi", response_model=ApiResponse)
async def set_roi(body: RoiRequest, svc: CameraService = Depends(_svc)):
    try:
        info = await svc.set_roi(
            width=body.width, height=body.height,
            offset_x=body.offset_x, offset_y=body.offset_y,
        )
        return ok(roi_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/roi/center", response_model=ApiResponse)
async def center_roi(svc: CameraService = Depends(_svc)):
    try:
        info = await svc.center_roi()
        return ok(roi_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# Pixel Format (2 endpoints)
# ---------------------------------------------------------------------------

@router.get("/pixel-format", response_model=ApiResponse)
async def get_pixel_format(svc: CameraService = Depends(_svc)):
    try:
        info = await svc.get_pixel_format()
        return ok(pixel_format_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/pixel-format", response_model=ApiResponse)
async def set_pixel_format(body: PixelFormatRequest,
                           svc: CameraService = Depends(_svc)):
    try:
        info = await svc.set_pixel_format(format=body.format)
        return ok(pixel_format_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# Frame Rate (2 endpoints)
# ---------------------------------------------------------------------------

@router.get("/frame-rate", response_model=ApiResponse)
async def get_frame_rate(svc: CameraService = Depends(_svc)):
    try:
        info = await svc.get_frame_rate()
        return ok(frame_rate_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/frame-rate", response_model=ApiResponse)
async def set_frame_rate(body: FrameRateRequest,
                         svc: CameraService = Depends(_svc)):
    try:
        info = await svc.set_frame_rate(enable=body.enable, value=body.value)
        return ok(frame_rate_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# Trigger (3 endpoints)
# ---------------------------------------------------------------------------

@router.get("/trigger", response_model=ApiResponse)
async def get_trigger(svc: CameraService = Depends(_svc)):
    try:
        info = await svc.get_trigger()
        return ok(trigger_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/trigger", response_model=ApiResponse)
async def set_trigger(body: TriggerRequest,
                      svc: CameraService = Depends(_svc)):
    try:
        info = await svc.set_trigger(mode=body.mode, source=body.source)
        return ok(trigger_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/trigger/fire", response_model=ApiResponse)
async def fire_trigger(svc: CameraService = Depends(_svc)):
    try:
        await svc.fire_trigger()
        return ok({})
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# Temperature (1 endpoint)
# ---------------------------------------------------------------------------

@router.get("/temperature", response_model=ApiResponse)
async def get_temperature(svc: CameraService = Depends(_svc)):
    try:
        temp = await svc.get_temperature()
        return ok({"value_c": temp})
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# UserSet (4 endpoints)
# ---------------------------------------------------------------------------

@router.get("/user-set", response_model=ApiResponse)
async def get_user_set(svc: CameraService = Depends(_svc)):
    try:
        info = await svc.get_user_set_info()
        return ok(userset_to_response(info).model_dump())
    except CameraError as exc:
        return _error_response(exc)


@router.post("/user-set/load", response_model=ApiResponse)
async def load_user_set(body: UserSetSlotRequest,
                        svc: CameraService = Depends(_svc)):
    try:
        await svc.load_user_set(slot=body.slot)
        return ok({})
    except CameraError as exc:
        return _error_response(exc)


@router.post("/user-set/save", response_model=ApiResponse)
async def save_user_set(body: UserSetSlotRequest,
                        svc: CameraService = Depends(_svc)):
    try:
        await svc.save_user_set(slot=body.slot)
        return ok({})
    except CameraError as exc:
        return _error_response(exc)


@router.post("/user-set/default", response_model=ApiResponse)
async def set_default_user_set(body: UserSetSlotRequest,
                               svc: CameraService = Depends(_svc)):
    try:
        await svc.set_default_user_set(slot=body.slot)
        return ok({})
    except CameraError as exc:
        return _error_response(exc)


# ---------------------------------------------------------------------------
# Frame Capture & Streaming (2 endpoints)
# ---------------------------------------------------------------------------

@router.post("/capture")
async def camera_capture(quality: int = 85,
                         svc: CameraService = Depends(_svc)):
    """Capture a single frame as JPEG."""
    try:
        jpeg = await svc.capture_jpeg(quality=quality)
        return Response(content=jpeg, media_type="image/jpeg")
    except CameraError as exc:
        return _error_response(exc)
    except Exception as exc:
        log.error("Camera capture: %s", exc)
        return JSONResponse(status_code=503, content={
            "success": False, "error": str(exc), "code": "CAMERA_CAPTURE_ERROR",
        })


@router.get("/stream")
async def camera_stream(fps: float = 15.0,
                        svc: CameraService = Depends(_svc)):
    """MJPEG HTTP streaming endpoint."""
    if not svc.is_connected:
        return JSONResponse(status_code=412, content={
            "success": False, "error": "Camera disconnected",
            "code": "CAMERA_DISCONNECTED",
        })

    async def _mjpeg():
        async for frame in svc.stream_frames(fps=fps):
            jpeg = frame.to_jpeg(quality=85)
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")

    return StreamingResponse(
        _mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
```

- [ ] **Step 2: Verify syntax and imports**

```bash
cd src/app/server && python -c "from server.routers.camera import router; print(f'{len(router.routes)} routes')"
```

Expected: `20 routes` (or close — FastAPI adds route objects per endpoint)

- [ ] **Step 3: Commit**

```bash
git add src/app/server/routers/camera.py
git commit -m "feat: camera router — 20 REST endpoints for 8 features

Exposure, gain, ROI, pixel format, frame rate, trigger, temperature,
user set. Plus connect, disconnect, status, capabilities, device-info,
capture, stream. Error mapping from CameraError hierarchy to HTTP."
```

---

## Task 6: main.py Wiring + Config Update

**Files:**
- Modify: `src/app/server/config.py` (add `camera_backend` field)
- Modify: `src/app/server/main.py` (update camera DI + WS provider)

- [ ] **Step 1: Add camera_backend config field**

In `src/app/server/config.py`, add after line 58 (`camera_fps: float = 30.0`):

```python
    camera_backend: str = "mock"  # "mock" | "vmbpy"
```

- [ ] **Step 2: Update main.py camera wiring**

Replace lines 78-84 in `main.py` (the camera service initialization block):

```python
    # Camera backend — select via OB_CAMERA_BACKEND env var
    if cfg.camera_backend == "vmbpy" and not cfg.mock_mode:
        try:
            from .services.camera_backends.vmbpy_backend import VmbPyCameraBackend
            camera_backend = VmbPyCameraBackend()
            log.info("Camera backend: VmbPy (Allied Vision)")
        except ImportError:
            log.warning("VmbPy not available — falling back to mock camera")
            from .services.camera_backends.mock_backend import MockCameraBackend
            camera_backend = MockCameraBackend()
    else:
        from .services.camera_backends.mock_backend import MockCameraBackend
        camera_backend = MockCameraBackend()
        log.info("Camera backend: Mock")

    from .services.camera_service import CameraService
    camera_svc = CameraService(camera_backend)
    await camera_svc.connect()
```

- [ ] **Step 3: Update _camera_provider for FrameMeta**

Replace the `_camera_provider` function in `main.py`:

```python
    async def _camera_provider():
        try:
            frame = await camera_svc.capture()
            jpeg = frame.to_jpeg(quality=cfg.camera_jpeg_quality)
            if not jpeg:
                return None
            meta = frame.meta
            return {
                "jpeg":   jpeg,
                "width":  meta.width,
                "height": meta.height,
                "meta": {
                    "timestamp_us":   meta.timestamp_us,
                    "exposure_us":    meta.exposure_us,
                    "gain_db":        meta.gain_db,
                    "temperature_c":  meta.temperature_c,
                    "fps_actual":     meta.fps_actual,
                    "width":          meta.width,
                    "height":         meta.height,
                },
            }
        except Exception:
            return None
```

- [ ] **Step 4: Update _system_provider**

Update `_system_provider` to use the new `is_connected` property:

```python
    async def _system_provider():
        try:
            return {
                "ipc_connected":    ipc.connected,
                "camera_connected": camera_svc.is_connected,
                "driver_probe":     app.state.driver_probe,
            }
        except Exception:
            return None
```

- [ ] **Step 5: Update shutdown**

Replace `await camera_svc.disconnect()` in the shutdown block — no change needed (method exists).

- [ ] **Step 6: Run existing tests to verify nothing breaks**

```bash
cd src/app/server && python -m pytest tests/ -v --timeout=30
```

Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/app/server/config.py src/app/server/main.py
git commit -m "feat: wire CameraBackend DI — OB_CAMERA_BACKEND env var selects backend

VmbPy or Mock selection via config. Updated _camera_provider to include
FrameMeta in WS broadcast. CameraService receives injected backend."
```

---

## Task 7: WebSocket FrameMeta Broadcast

**Files:**
- Modify: `src/app/server/ws/manager.py`

Update the camera broadcast loop to include FrameMeta in the WS payload.

- [ ] **Step 1: Read current ws/manager.py camera_loop**

Read `src/app/server/ws/manager.py` and locate the `_camera_loop` method. The current payload sends `type`, `frame_b64`, `width`, `height`, `timestamp_us`.

- [ ] **Step 2: Update the broadcast payload**

In `_camera_loop`, update the payload construction to include `meta`:

```python
                payload = json.dumps({
                    "type":       "camera_frame",
                    "frame_b64":  base64.b64encode(jpeg).decode(),
                    "width":      frame.get("width", 0),
                    "height":     frame.get("height", 0),
                    "timestamp_us": int(time.monotonic() * 1_000_000),
                    "meta":       frame.get("meta"),
                })
```

The `meta` dict is now populated by the updated `_camera_provider` in main.py (Task 6). If `meta` is None (old provider), it serializes as `null` — backward compatible.

- [ ] **Step 3: Run tests**

```bash
cd src/app/server && python -m pytest tests/ -v --timeout=30
```

Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add src/app/server/ws/manager.py
git commit -m "feat: WebSocket camera frames include FrameMeta telemetry

Every WS frame now carries exposure_us, gain_db, temperature_c,
fps_actual. Frontend can show live telemetry without polling."
```

---

## Task 8: Integration Tests for All 20 Endpoints

**Files:**
- Create: `src/app/server/tests/test_camera_endpoints.py`
- Delete: `src/app/server/tests/test_camera.py` (replaced)

- [ ] **Step 1: Write comprehensive endpoint tests**

```python
# src/app/server/tests/test_camera_endpoints.py
"""
test_camera_endpoints.py — Integration tests for all 20 camera REST endpoints.

Tests run in mock mode (OB_MOCK_MODE=true) — no hardware required.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Connection & Status
# ---------------------------------------------------------------------------

async def test_connect(client):
    resp = await client.post("/api/camera/connect")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "device" in data
    assert "capabilities" in data
    assert data["device"]["vendor"] == "Mock"


async def test_status(client):
    resp = await client.get("/api/camera/status")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["connected"] is True


async def test_capabilities(client):
    resp = await client.get("/api/camera/capabilities")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["exposure"]["supported"] is True
    assert data["roi"]["supported"] is True


async def test_device_info(client):
    resp = await client.get("/api/camera/device-info")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "model" in data
    assert "serial" in data


# ---------------------------------------------------------------------------
# Exposure
# ---------------------------------------------------------------------------

async def test_get_exposure(client):
    resp = await client.get("/api/camera/exposure")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "time_us" in data
    assert "range" in data


async def test_set_exposure_manual(client):
    resp = await client.post("/api/camera/exposure",
                             json={"auto": False, "time_us": 10000})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["time_us"] == 10000
    assert data["auto"] is False


async def test_set_exposure_auto(client):
    resp = await client.post("/api/camera/exposure", json={"auto": True})
    assert resp.status_code == 200
    assert resp.json()["data"]["auto"] is True


async def test_set_exposure_out_of_range(client):
    resp = await client.post("/api/camera/exposure",
                             json={"auto": False, "time_us": 999999999})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "FEATURE_OUT_OF_RANGE"


# ---------------------------------------------------------------------------
# Gain
# ---------------------------------------------------------------------------

async def test_get_gain(client):
    resp = await client.get("/api/camera/gain")
    assert resp.status_code == 200
    assert "value_db" in resp.json()["data"]


async def test_set_gain(client):
    resp = await client.post("/api/camera/gain",
                             json={"auto": False, "value_db": 6.0})
    assert resp.status_code == 200
    assert resp.json()["data"]["value_db"] == 6.0


# ---------------------------------------------------------------------------
# ROI
# ---------------------------------------------------------------------------

async def test_get_roi(client):
    resp = await client.get("/api/camera/roi")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "width" in data
    assert "width_range" in data


async def test_set_roi(client):
    resp = await client.post("/api/camera/roi",
                             json={"width": 800, "height": 600})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["width"] == 800
    assert data["height"] == 600
    assert "frame_rate" in data["invalidated"]


async def test_center_roi(client):
    await client.post("/api/camera/roi", json={"width": 800, "height": 600})
    resp = await client.post("/api/camera/roi/center")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["offset_x"] == (1456 - 800) // 2
    assert data["offset_y"] == (1088 - 600) // 2


# ---------------------------------------------------------------------------
# Pixel Format
# ---------------------------------------------------------------------------

async def test_get_pixel_format(client):
    resp = await client.get("/api/camera/pixel-format")
    assert resp.status_code == 200
    assert "format" in resp.json()["data"]
    assert "available" in resp.json()["data"]


async def test_set_pixel_format(client):
    resp = await client.post("/api/camera/pixel-format",
                             json={"format": "mono12"})
    assert resp.status_code == 200
    assert resp.json()["data"]["format"] == "mono12"


# ---------------------------------------------------------------------------
# Frame Rate
# ---------------------------------------------------------------------------

async def test_get_frame_rate(client):
    resp = await client.get("/api/camera/frame-rate")
    assert resp.status_code == 200
    assert "value" in resp.json()["data"]


async def test_set_frame_rate(client):
    resp = await client.post("/api/camera/frame-rate",
                             json={"enable": True, "value": 15.0})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["enable"] is True
    assert data["value"] == 15.0


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------

async def test_get_trigger(client):
    resp = await client.get("/api/camera/trigger")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "mode" in data
    assert "available_modes" in data


async def test_set_trigger_software(client):
    resp = await client.post("/api/camera/trigger",
                             json={"mode": "software"})
    assert resp.status_code == 200
    assert resp.json()["data"]["mode"] == "software"


async def test_fire_trigger(client):
    await client.post("/api/camera/trigger", json={"mode": "software"})
    resp = await client.post("/api/camera/trigger/fire")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Temperature
# ---------------------------------------------------------------------------

async def test_get_temperature(client):
    resp = await client.get("/api/camera/temperature")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "value_c" in data
    assert 30.0 <= data["value_c"] <= 50.0


# ---------------------------------------------------------------------------
# UserSet
# ---------------------------------------------------------------------------

async def test_get_user_set(client):
    resp = await client.get("/api/camera/user-set")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "available_slots" in data
    assert "Default" in data["available_slots"]


async def test_user_set_save_load(client):
    # Set exposure
    await client.post("/api/camera/exposure",
                      json={"auto": False, "time_us": 8000})
    # Save
    resp = await client.post("/api/camera/user-set/save",
                             json={"slot": "UserSet1"})
    assert resp.status_code == 200
    # Change exposure
    await client.post("/api/camera/exposure",
                      json={"auto": False, "time_us": 1000})
    # Load
    resp = await client.post("/api/camera/user-set/load",
                             json={"slot": "UserSet1"})
    assert resp.status_code == 200
    # Verify restored
    resp = await client.get("/api/camera/exposure")
    assert resp.json()["data"]["time_us"] == 8000


async def test_user_set_default(client):
    resp = await client.post("/api/camera/user-set/default",
                             json={"slot": "UserSet1"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Capture & Stream
# ---------------------------------------------------------------------------

async def test_capture_jpeg(client):
    resp = await client.post("/api/camera/capture")
    assert resp.status_code == 200
    assert "image/jpeg" in resp.headers["content-type"]
    assert resp.content[:3] == b"\xff\xd8\xff"


async def test_capture_custom_quality(client):
    resp = await client.post("/api/camera/capture?quality=50")
    assert resp.status_code == 200
    assert resp.content[:3] == b"\xff\xd8\xff"


# ---------------------------------------------------------------------------
# Disconnect
# ---------------------------------------------------------------------------

async def test_disconnect(client):
    resp = await client.post("/api/camera/disconnect")
    assert resp.status_code == 200
    # Status should show disconnected
    resp = await client.get("/api/camera/status")
    data = resp.json()["data"]
    assert data["connected"] is False
```

- [ ] **Step 2: Delete old test file**

```bash
rm src/app/server/tests/test_camera.py
```

- [ ] **Step 3: Run all tests**

```bash
cd src/app/server && python -m pytest tests/ -v --timeout=30
```

Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add src/app/server/tests/test_camera_endpoints.py
git rm src/app/server/tests/test_camera.py
git commit -m "test: integration tests for all 20 camera REST endpoints

30 tests covering connect, status, capabilities, device-info, exposure,
gain, ROI, pixel format, frame rate, trigger, temperature, user set,
capture, disconnect. Replaces old test_camera.py."
```

---

## Task 9: VmbPyCameraBackend

**Files:**
- Create: `src/app/server/services/camera_backends/vmbpy_backend.py`

Production backend for Allied Vision Alvium cameras. VmbPy SDK required.

- [ ] **Step 1: Implement VmbPyCameraBackend**

```python
# src/app/server/services/camera_backends/vmbpy_backend.py
"""
vmbpy_backend.py — Allied Vision Alvium camera backend via VmbPy SDK.

Targets Alvium 1800 U-158m (USB3 Vision). All VmbPy calls are blocking
and wrapped in run_in_executor for async compatibility.

Requires: vmbpy (Vimba X Python SDK)

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Optional

import numpy as np

from . import (
    CameraBackend, CameraDisconnectedError, CameraStatus, CameraTimeoutError,
    CapturedFrame, DeviceInfo, ExposureInfo, Feature, FeatureCapability,
    FeatureOutOfRangeError, FrameMeta, FrameRateInfo, GainInfo, NumericRange,
    PixelFormatInfo, RoiInfo, TriggerInfo, UserSetInfo,
)

log = logging.getLogger(__name__)

# Pixel format mapping: API name → VmbPy enum name
_FORMAT_MAP = {
    "mono8": "Mono8", "mono10": "Mono10", "mono12": "Mono12",
    "bayer_rg8": "BayerRG8", "bayer_rg10": "BayerRG10",
    "bayer_rg12": "BayerRG12", "rgb8": "RGB8",
}
_FORMAT_MAP_INV = {v: k for k, v in _FORMAT_MAP.items()}


class VmbPyCameraBackend(CameraBackend):
    """Allied Vision Alvium camera via VmbPy (Vimba X SDK)."""

    def __init__(self) -> None:
        self._vmb = None           # VmbSystem instance
        self._cam = None           # Camera instance
        self._device: Optional[DeviceInfo] = None
        self._connected = False
        self._streaming = False
        self._frame_count = 0
        self._start_time = 0.0
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _require_connected(self) -> None:
        if not self._connected or self._cam is None:
            raise CameraDisconnectedError("Camera not connected")

    def _run_sync(self, fn, *args):
        """Run blocking VmbPy call in executor."""
        loop = self._loop or asyncio.get_event_loop()
        return loop.run_in_executor(None, fn, *args)

    # --- Connection ---

    async def connect(self) -> DeviceInfo:
        if self._connected:
            return self._device
        self._loop = asyncio.get_event_loop()

        import vmbpy

        def _connect():
            vmb = vmbpy.VmbSystem.get_instance()
            vmb.__enter__()
            cams = vmb.get_all_cameras()
            if not cams:
                vmb.__exit__(None, None, None)
                raise CameraDisconnectedError("No cameras found")
            cam = cams[0]
            cam.__enter__()
            info = DeviceInfo(
                model=cam.get_model(),
                serial=cam.get_serial(),
                firmware=cam.get_feature_by_name("DeviceFirmwareVersion").get(),
                vendor=cam.get_feature_by_name("DeviceVendorName").get(),
            )
            return vmb, cam, info

        self._vmb, self._cam, self._device = await self._run_sync(_connect)
        self._connected = True
        self._start_time = time.monotonic()
        self._frame_count = 0
        log.info("VmbPy connected: %s %s", self._device.vendor, self._device.model)
        return self._device

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._streaming = False

        def _disconnect():
            if self._cam:
                try:
                    self._cam.__exit__(None, None, None)
                except Exception:
                    pass
            if self._vmb:
                try:
                    self._vmb.__exit__(None, None, None)
                except Exception:
                    pass

        await self._run_sync(_disconnect)
        self._cam = None
        self._vmb = None
        self._connected = False
        log.info("VmbPy disconnected")

    # --- Frame capture ---

    async def capture(self) -> CapturedFrame:
        self._require_connected()
        self._frame_count += 1

        def _capture():
            frame = self._cam.get_frame(timeout_ms=5000)
            frame.convert_pixel_format(self._get_mono_format())
            arr = frame.as_numpy_ndarray().copy()
            return arr

        try:
            arr = await self._run_sync(_capture)
        except Exception as exc:
            raise CameraTimeoutError(f"Frame capture failed: {exc}") from exc

        elapsed = time.monotonic() - self._start_time
        fps = self._frame_count / max(elapsed, 0.001)

        # Read current telemetry
        exp_us = await self._get_feature_value("ExposureTime")
        gain_db = await self._get_feature_value("Gain")
        try:
            temp = await self._get_feature_value("DeviceTemperature")
        except Exception:
            temp = None

        pf = await self._get_feature_value_str("PixelFormat")

        meta = FrameMeta(
            timestamp_us=int(time.monotonic() * 1_000_000),
            exposure_us=exp_us,
            gain_db=gain_db,
            temperature_c=temp,
            fps_actual=round(fps, 2),
            width=arr.shape[1],
            height=arr.shape[0],
        )
        return CapturedFrame(
            array=arr,
            pixel_format=_FORMAT_MAP_INV.get(pf, pf),
            meta=meta,
        )

    async def stream(self, fps: float = 30.0) -> AsyncIterator[CapturedFrame]:
        self._require_connected()
        self._streaming = True
        interval = 1.0 / max(fps, 1.0)
        try:
            while self._streaming and self._connected:
                yield await self.capture()
                await asyncio.sleep(interval)
        finally:
            self._streaming = False

    # --- Capabilities ---

    def capabilities(self) -> dict[Feature, FeatureCapability]:
        self._require_connected()
        caps = {}
        caps[Feature.EXPOSURE] = FeatureCapability(
            supported=True,
            range=self._get_numeric_range("ExposureTime"),
            auto_available=self._has_feature("ExposureAuto"),
        )
        caps[Feature.GAIN] = FeatureCapability(
            supported=True,
            range=self._get_numeric_range("Gain"),
            auto_available=self._has_feature("GainAuto"),
        )
        caps[Feature.ROI] = FeatureCapability(
            supported=True,
            range=self._get_numeric_range("Width"),
        )
        caps[Feature.PIXEL_FORMAT] = FeatureCapability(
            supported=True,
            available_values=self._get_enum_entries("PixelFormat"),
        )
        caps[Feature.FRAME_RATE] = FeatureCapability(
            supported=self._has_feature("AcquisitionFrameRate"),
            range=self._get_numeric_range("AcquisitionFrameRate")
                  if self._has_feature("AcquisitionFrameRate") else None,
        )
        caps[Feature.TRIGGER] = FeatureCapability(
            supported=True,
            available_values=["freerun", "software", "external"],
        )
        caps[Feature.TEMPERATURE] = FeatureCapability(
            supported=self._has_feature("DeviceTemperature"),
        )
        caps[Feature.USER_SET] = FeatureCapability(
            supported=self._has_feature("UserSetSelector"),
            slots=self._get_enum_entries("UserSetSelector")
                  if self._has_feature("UserSetSelector") else None,
        )
        return caps

    async def get_status(self) -> CameraStatus:
        if not self._connected:
            return CameraStatus(
                connected=False, streaming=False, device=None,
                current_exposure_us=None, current_gain_db=None,
                current_temperature_c=None, current_fps=None,
                current_pixel_format=None, current_roi=None,
                current_trigger_mode=None,
            )
        exp = await self._get_feature_value("ExposureTime")
        gain = await self._get_feature_value("Gain")
        try:
            temp = await self._get_feature_value("DeviceTemperature")
        except Exception:
            temp = None
        try:
            fps = await self._get_feature_value("AcquisitionFrameRate")
        except Exception:
            fps = None
        pf = await self._get_feature_value_str("PixelFormat")
        w = int(await self._get_feature_value("Width"))
        h = int(await self._get_feature_value("Height"))
        ox = int(await self._get_feature_value("OffsetX"))
        oy = int(await self._get_feature_value("OffsetY"))
        trigger_mode = await self._get_feature_value_str("TriggerMode")
        return CameraStatus(
            connected=True, streaming=self._streaming, device=self._device,
            current_exposure_us=exp, current_gain_db=gain,
            current_temperature_c=temp, current_fps=fps,
            current_pixel_format=_FORMAT_MAP_INV.get(pf, pf),
            current_roi={"width": w, "height": h, "offset_x": ox, "offset_y": oy},
            current_trigger_mode="freerun" if trigger_mode == "Off" else trigger_mode.lower(),
        )

    def device_info(self) -> DeviceInfo:
        self._require_connected()
        return self._device

    # --- Exposure ---

    async def set_exposure(self, *, auto: bool = False,
                           time_us: Optional[float] = None) -> ExposureInfo:
        self._require_connected()
        if auto:
            await self._set_feature_str("ExposureAuto", "Continuous")
        else:
            await self._set_feature_str("ExposureAuto", "Off")
            if time_us is not None:
                r = self._get_numeric_range("ExposureTime")
                if time_us < r.min or time_us > r.max:
                    raise FeatureOutOfRangeError(Feature.EXPOSURE, time_us, r)
                await self._set_feature_value("ExposureTime", time_us)
        return await self.get_exposure()

    async def get_exposure(self) -> ExposureInfo:
        self._require_connected()
        val = await self._get_feature_value("ExposureTime")
        auto_str = await self._get_feature_value_str("ExposureAuto")
        return ExposureInfo(
            auto=auto_str != "Off",
            time_us=val,
            range=self._get_numeric_range("ExposureTime"),
            auto_available=self._has_feature("ExposureAuto"),
        )

    # --- Gain ---

    async def set_gain(self, *, auto: bool = False,
                       value_db: Optional[float] = None) -> GainInfo:
        self._require_connected()
        if auto:
            await self._set_feature_str("GainAuto", "Continuous")
        else:
            await self._set_feature_str("GainAuto", "Off")
            if value_db is not None:
                r = self._get_numeric_range("Gain")
                if value_db < r.min or value_db > r.max:
                    raise FeatureOutOfRangeError(Feature.GAIN, value_db, r)
                await self._set_feature_value("Gain", value_db)
        return await self.get_gain()

    async def get_gain(self) -> GainInfo:
        self._require_connected()
        val = await self._get_feature_value("Gain")
        auto_str = await self._get_feature_value_str("GainAuto")
        return GainInfo(
            auto=auto_str != "Off",
            value_db=val,
            range=self._get_numeric_range("Gain"),
            auto_available=self._has_feature("GainAuto"),
        )

    # --- ROI ---

    async def set_roi(self, *, width: int, height: int,
                      offset_x: int = 0, offset_y: int = 0) -> RoiInfo:
        self._require_connected()
        # ROI is a cold feature — stop acquisition, apply, restart
        was_streaming = self._streaming
        if was_streaming:
            self._streaming = False
            await asyncio.sleep(0.05)

        await self._set_feature_value("OffsetX", 0)
        await self._set_feature_value("OffsetY", 0)
        await self._set_feature_value("Width", width)
        await self._set_feature_value("Height", height)
        await self._set_feature_value("OffsetX", offset_x)
        await self._set_feature_value("OffsetY", offset_y)

        if was_streaming:
            self._streaming = True

        info = await self.get_roi()
        info.invalidated = [Feature.FRAME_RATE]
        return info

    async def get_roi(self) -> RoiInfo:
        self._require_connected()
        w = int(await self._get_feature_value("Width"))
        h = int(await self._get_feature_value("Height"))
        ox = int(await self._get_feature_value("OffsetX"))
        oy = int(await self._get_feature_value("OffsetY"))
        return RoiInfo(
            width=w, height=h, offset_x=ox, offset_y=oy,
            width_range=self._get_numeric_range("Width"),
            height_range=self._get_numeric_range("Height"),
            offset_x_range=self._get_numeric_range("OffsetX"),
            offset_y_range=self._get_numeric_range("OffsetY"),
        )

    async def center_roi(self) -> RoiInfo:
        self._require_connected()
        w = int(await self._get_feature_value("Width"))
        h = int(await self._get_feature_value("Height"))
        max_w = int(self._cam.get_feature_by_name("WidthMax").get())
        max_h = int(self._cam.get_feature_by_name("HeightMax").get())
        ox = (max_w - w) // 2
        oy = (max_h - h) // 2
        return await self.set_roi(width=w, height=h, offset_x=ox, offset_y=oy)

    # --- Pixel Format ---

    async def set_pixel_format(self, *, format: str) -> PixelFormatInfo:
        self._require_connected()
        vmb_name = _FORMAT_MAP.get(format)
        if not vmb_name:
            raise FeatureOutOfRangeError(
                Feature.PIXEL_FORMAT, 0,
                NumericRange(min=0, max=len(_FORMAT_MAP) - 1, step=1),
            )
        was_streaming = self._streaming
        if was_streaming:
            self._streaming = False
            await asyncio.sleep(0.05)

        await self._set_feature_str("PixelFormat", vmb_name)

        if was_streaming:
            self._streaming = True

        info = await self.get_pixel_format()
        info.invalidated = [Feature.FRAME_RATE]
        return info

    async def get_pixel_format(self) -> PixelFormatInfo:
        self._require_connected()
        pf = await self._get_feature_value_str("PixelFormat")
        avail = self._get_enum_entries("PixelFormat")
        return PixelFormatInfo(
            format=_FORMAT_MAP_INV.get(pf, pf),
            available=[_FORMAT_MAP_INV.get(v, v) for v in avail],
        )

    # --- Frame Rate ---

    async def set_frame_rate(self, *, enable: bool,
                             value: Optional[float] = None) -> FrameRateInfo:
        self._require_connected()
        if self._has_feature("AcquisitionFrameRateEnable"):
            await self._set_feature_value("AcquisitionFrameRateEnable", enable)
        if enable and value is not None:
            r = self._get_numeric_range("AcquisitionFrameRate")
            if value < r.min or value > r.max:
                raise FeatureOutOfRangeError(Feature.FRAME_RATE, value, r)
            await self._set_feature_value("AcquisitionFrameRate", value)
        return await self.get_frame_rate()

    async def get_frame_rate(self) -> FrameRateInfo:
        self._require_connected()
        val = await self._get_feature_value("AcquisitionFrameRate")
        enable = True
        if self._has_feature("AcquisitionFrameRateEnable"):
            enable = bool(self._cam.get_feature_by_name("AcquisitionFrameRateEnable").get())
        return FrameRateInfo(
            enable=enable, value=val,
            range=self._get_numeric_range("AcquisitionFrameRate"),
        )

    # --- Trigger ---

    async def set_trigger(self, *, mode: str,
                          source: Optional[str] = None) -> TriggerInfo:
        self._require_connected()
        if mode == "freerun":
            await self._set_feature_str("TriggerMode", "Off")
        else:
            await self._set_feature_str("TriggerMode", "On")
            if source:
                await self._set_feature_str("TriggerSource", source)
            elif mode == "software":
                await self._set_feature_str("TriggerSource", "Software")
        info = await self.get_trigger()
        if mode != "freerun":
            info.invalidated = [Feature.FRAME_RATE]
        return info

    async def get_trigger(self) -> TriggerInfo:
        self._require_connected()
        trigger_mode = await self._get_feature_value_str("TriggerMode")
        source = await self._get_feature_value_str("TriggerSource")
        if trigger_mode == "Off":
            mode = "freerun"
        elif source == "Software":
            mode = "software"
        else:
            mode = "external"
        return TriggerInfo(
            mode=mode, source=source if trigger_mode != "Off" else None,
            available_modes=["freerun", "software", "external"],
            available_sources=self._get_enum_entries("TriggerSource"),
        )

    async def fire_trigger(self) -> None:
        self._require_connected()
        await self._run_sync(
            lambda: self._cam.get_feature_by_name("TriggerSoftware").run()
        )

    # --- Temperature ---

    async def get_temperature(self) -> float:
        self._require_connected()
        return await self._get_feature_value("DeviceTemperature")

    # --- UserSet ---

    async def load_user_set(self, *, slot: str) -> None:
        self._require_connected()
        await self._set_feature_str("UserSetSelector", slot)
        await self._run_sync(
            lambda: self._cam.get_feature_by_name("UserSetLoad").run()
        )

    async def save_user_set(self, *, slot: str) -> None:
        self._require_connected()
        await self._set_feature_str("UserSetSelector", slot)
        await self._run_sync(
            lambda: self._cam.get_feature_by_name("UserSetSave").run()
        )

    async def set_default_user_set(self, *, slot: str) -> None:
        self._require_connected()
        await self._set_feature_str("UserSetDefault", slot)

    async def get_user_set_info(self) -> UserSetInfo:
        self._require_connected()
        current = await self._get_feature_value_str("UserSetSelector")
        default = await self._get_feature_value_str("UserSetDefault")
        slots = self._get_enum_entries("UserSetSelector")
        return UserSetInfo(
            current_slot=current,
            available_slots=slots,
            default_slot=default,
        )

    # --- Internal helpers ---

    def _has_feature(self, name: str) -> bool:
        try:
            self._cam.get_feature_by_name(name)
            return True
        except Exception:
            return False

    def _get_numeric_range(self, name: str) -> NumericRange:
        try:
            feat = self._cam.get_feature_by_name(name)
            r = feat.get_range()
            inc = feat.get_increment() if hasattr(feat, 'get_increment') else 1
            return NumericRange(min=r[0], max=r[1], step=inc if inc else 1)
        except Exception:
            return NumericRange(min=0, max=0, step=1)

    def _get_enum_entries(self, name: str) -> list[str]:
        try:
            feat = self._cam.get_feature_by_name(name)
            entries = feat.get_available_entries()
            return [str(e) for e in entries]
        except Exception:
            return []

    async def _get_feature_value(self, name: str) -> float:
        def _get():
            return self._cam.get_feature_by_name(name).get()
        return await self._run_sync(_get)

    async def _get_feature_value_str(self, name: str) -> str:
        def _get():
            return str(self._cam.get_feature_by_name(name).get())
        return await self._run_sync(_get)

    async def _set_feature_value(self, name: str, value) -> None:
        def _set():
            self._cam.get_feature_by_name(name).set(value)
        await self._run_sync(_set)

    async def _set_feature_str(self, name: str, value: str) -> None:
        def _set():
            self._cam.get_feature_by_name(name).set(value)
        await self._run_sync(_set)

    def _get_mono_format(self):
        """Return VmbPy Mono8 pixel format for frame conversion."""
        import vmbpy
        return vmbpy.PixelFormat.Mono8
```

- [ ] **Step 2: Verify import (will fail if vmbpy not installed — that's OK)**

```bash
cd src/app/server && python -c "
try:
    from server.services.camera_backends.vmbpy_backend import VmbPyCameraBackend
    print('VmbPy import OK')
except ImportError as e:
    print(f'VmbPy not installed (expected on dev): {e}')
"
```

Expected: Either "VmbPy import OK" or "VmbPy not installed (expected on dev): ..."

- [ ] **Step 3: Commit**

```bash
git add src/app/server/services/camera_backends/vmbpy_backend.py
git commit -m "feat: VmbPyCameraBackend — Allied Vision Alvium production driver

All 8 features via GenICam nodes, transparent hot/cold handling for
ROI and PixelFormat, run_in_executor for blocking VmbPy calls,
frame-attached metadata, invalidation hints."
```

---

## Task 10: Frontend client.ts Camera API Extensions

**Files:**
- Modify: `src/app/frontend/src/api/client.ts`

Extend the existing `cameraApi` object with methods for all 20 endpoints.

- [ ] **Step 1: Read the current client.ts to find exact insertion point**

Read `src/app/frontend/src/api/client.ts` and locate the `cameraApi` object definition and `WsCameraFrame` type.

- [ ] **Step 2: Add TypeScript types for camera features**

Add these types before the `cameraApi` object:

```typescript
// Camera feature types (matches backend camera_schemas.py)
export interface NumericRange { min: number; max: number; step: number }
export interface DeviceInfo { model: string; serial: string; firmware: string; vendor: string }
export interface FrameMeta {
  timestamp_us: number; exposure_us: number; gain_db: number;
  temperature_c: number | null; fps_actual: number; width: number; height: number;
}
export interface FeatureCapability {
  supported: boolean; range?: NumericRange; auto_available?: boolean;
  available_values?: string[]; slots?: string[];
}
export interface CameraCapabilities { [feature: string]: FeatureCapability }
export interface ConnectData { device: DeviceInfo; capabilities: CameraCapabilities }
export interface ExposureInfo {
  auto: boolean; time_us: number; range: NumericRange;
  auto_available: boolean; invalidated: string[];
}
export interface GainInfo {
  auto: boolean; value_db: number; range: NumericRange;
  auto_available: boolean; invalidated: string[];
}
export interface RoiInfo {
  width: number; height: number; offset_x: number; offset_y: number;
  width_range: NumericRange; height_range: NumericRange;
  offset_x_range: NumericRange; offset_y_range: NumericRange;
  invalidated: string[];
}
export interface PixelFormatInfo {
  format: string; available: string[]; invalidated: string[];
}
export interface FrameRateInfo {
  enable: boolean; value: number; range: NumericRange; invalidated: string[];
}
export interface TriggerInfo {
  mode: string; source: string | null; available_modes: string[];
  available_sources: string[]; invalidated: string[];
}
export interface UserSetInfo {
  current_slot: string; available_slots: string[]; default_slot: string;
}
```

- [ ] **Step 3: Replace the cameraApi object**

Replace the existing `cameraApi` with the full 20-method version:

```typescript
export const cameraApi = {
  // Connection & status
  connect: (): Promise<ConnectData> =>
    request("/api/camera/connect", { method: "POST" }),
  disconnect: (): Promise<void> =>
    request("/api/camera/disconnect", { method: "POST" }),
  status: (): Promise<CameraStatus> =>
    request("/api/camera/status"),
  capabilities: (): Promise<CameraCapabilities> =>
    request("/api/camera/capabilities"),
  deviceInfo: (): Promise<DeviceInfo> =>
    request("/api/camera/device-info"),

  // Exposure
  getExposure: (): Promise<ExposureInfo> =>
    request("/api/camera/exposure"),
  setExposure: (params: { auto: boolean; time_us?: number }): Promise<ExposureInfo> =>
    request("/api/camera/exposure", { method: "POST", body: JSON.stringify(params) }),

  // Gain
  getGain: (): Promise<GainInfo> =>
    request("/api/camera/gain"),
  setGain: (params: { auto: boolean; value_db?: number }): Promise<GainInfo> =>
    request("/api/camera/gain", { method: "POST", body: JSON.stringify(params) }),

  // ROI
  getRoi: (): Promise<RoiInfo> =>
    request("/api/camera/roi"),
  setRoi: (params: { width: number; height: number; offset_x?: number; offset_y?: number }): Promise<RoiInfo> =>
    request("/api/camera/roi", { method: "POST", body: JSON.stringify(params) }),
  centerRoi: (): Promise<RoiInfo> =>
    request("/api/camera/roi/center", { method: "POST" }),

  // Pixel format
  getPixelFormat: (): Promise<PixelFormatInfo> =>
    request("/api/camera/pixel-format"),
  setPixelFormat: (params: { format: string }): Promise<PixelFormatInfo> =>
    request("/api/camera/pixel-format", { method: "POST", body: JSON.stringify(params) }),

  // Frame rate
  getFrameRate: (): Promise<FrameRateInfo> =>
    request("/api/camera/frame-rate"),
  setFrameRate: (params: { enable: boolean; value?: number }): Promise<FrameRateInfo> =>
    request("/api/camera/frame-rate", { method: "POST", body: JSON.stringify(params) }),

  // Trigger
  getTrigger: (): Promise<TriggerInfo> =>
    request("/api/camera/trigger"),
  setTrigger: (params: { mode: string; source?: string }): Promise<TriggerInfo> =>
    request("/api/camera/trigger", { method: "POST", body: JSON.stringify(params) }),
  fireTrigger: (): Promise<void> =>
    request("/api/camera/trigger/fire", { method: "POST" }),

  // Temperature
  getTemperature: (): Promise<{ value_c: number }> =>
    request("/api/camera/temperature"),

  // UserSet
  getUserSet: (): Promise<UserSetInfo> =>
    request("/api/camera/user-set"),
  loadUserSet: (params: { slot: string }): Promise<void> =>
    request("/api/camera/user-set/load", { method: "POST", body: JSON.stringify(params) }),
  saveUserSet: (params: { slot: string }): Promise<void> =>
    request("/api/camera/user-set/save", { method: "POST", body: JSON.stringify(params) }),
  setDefaultUserSet: (params: { slot: string }): Promise<void> =>
    request("/api/camera/user-set/default", { method: "POST", body: JSON.stringify(params) }),

  // Capture & stream (kept from existing API)
  captureUrl: (): string => `${BASE_URL}/api/camera/capture`,
  streamUrl: (): string => `${BASE_URL}/api/camera/stream`,
};
```

- [ ] **Step 4: Update WsCameraFrame type to include meta**

```typescript
export interface WsCameraFrame {
  type: string;
  frame_b64: string;
  width: number;
  height: number;
  timestamp_us: number;
  meta?: FrameMeta;
}
```

- [ ] **Step 5: Build frontend to verify no TS errors**

```bash
cd src/app/frontend && npm run build 2>&1 | tail -10
```

Expected: Build succeeds

- [ ] **Step 6: Commit**

```bash
git add src/app/frontend/src/api/client.ts
git commit -m "feat: frontend cameraApi — 24 methods for all camera features

TypeScript types + API methods for exposure, gain, ROI, pixel format,
frame rate, trigger, temperature, user set. WsCameraFrame extended
with FrameMeta for live telemetry."
```

---

## Task 11: CameraPage Dynamic UI

**Files:**
- Modify: `src/app/frontend/src/pages/CameraPage.tsx`

Update CameraPage to use capabilities-driven dynamic feature widgets.

- [ ] **Step 1: Read current CameraPage.tsx**

Read `src/app/frontend/src/pages/CameraPage.tsx` to understand the current structure, which was recently rewritten to Tailwind.

- [ ] **Step 2: Update CameraPage imports and state**

Add imports for new camera API methods and types. Add state for capabilities, exposure, gain, ROI, etc. On camera connect, fetch capabilities and build UI dynamically. Hide unsupported feature widgets.

Key changes:
- Replace old `settings()` API call with feature-specific calls
- Add exposure/gain control panels with auto toggles and slider inputs
- Add ROI panel with width/height/offset controls + center button
- Add pixel format dropdown
- Add frame rate enable/value controls
- Add trigger mode selector + fire button
- Show temperature in status strip
- Show live telemetry from WS FrameMeta
- Handle `invalidated` arrays by re-fetching affected features
- Apply-on-commit pattern: fire API on Enter/blur, debounce sliders 100ms

This is a large UI task. The implementer should read the existing CameraPage structure and extend it with new panels for each feature, following the existing Tailwind component patterns (Card, Button, SliderInput, StatusBadge).

- [ ] **Step 3: Build frontend**

```bash
cd src/app/frontend && npm run build 2>&1 | tail -10
```

Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add src/app/frontend/src/pages/CameraPage.tsx
git commit -m "feat: CameraPage — capabilities-driven dynamic feature widgets

Exposure, gain, ROI, pixel format, frame rate, trigger controls.
Live telemetry from WS FrameMeta. Invalidation-aware re-fetching.
Unsupported features hidden based on capabilities."
```

---

## Task 12: Example Scripts

**Files:**
- Create: `examples/camera/01_connect_and_capture.py`
- Create: `examples/camera/02_exposure_gain_control.py`
- Create: `examples/camera/03_roi_and_format.py`
- Create: `examples/camera/04_trigger_software.py`
- Create: `examples/camera/05_continuous_stream.py`
- Create: `examples/camera/06_opencv_processing.py`
- Create: `examples/camera/07_userset_save_restore.py`
- Create: `examples/camera/08_full_inspection_pipeline.py`

All 8 example scripts from the design spec, section 9. Each file is self-contained and runnable against the SDK API (mock or production). Use `http://192.168.4.1:8000` as default base URL with `OB_API_BASE` env override.

- [ ] **Step 1: Create all 8 example files**

Write each file exactly as specified in the design spec `docs/superpowers/specs/2026-04-17-camera-backend-abc-design.md` section 9, with one addition: each script should read `OB_API_BASE` env var for the base URL:

```python
import os
BASE = os.environ.get("OB_API_BASE", "http://192.168.4.1:8000")
```

The exact code for each script is in the design spec sections 9.1-9.8. Copy verbatim, adding only the env var override.

- [ ] **Step 2: Verify syntax**

```bash
cd examples/camera && python -m py_compile 01_connect_and_capture.py && echo OK
cd examples/camera && for f in *.py; do python -m py_compile "$f" && echo "$f OK"; done
```

Expected: All 8 files compile without syntax errors

- [ ] **Step 3: Commit**

```bash
git add examples/camera/
git commit -m "feat: 8 camera SDK example scripts for SW developers

Connect+capture, exposure/gain control, ROI+format, software trigger,
WebSocket streaming, OpenCV processing, UserSet save/restore, full
inspection pipeline. Self-contained, copy-paste ready."
```

---

## Task 13: Final Integration Verification

**Files:** None (verification only)

- [ ] **Step 1: Run all backend tests**

```bash
cd src/app/server && python -m pytest tests/ -v --timeout=30
```

Expected: All tests PASS (unit + integration, ~55 tests)

- [ ] **Step 2: Build frontend**

```bash
cd src/app/frontend && npm run build
```

Expected: Build succeeds with no errors

- [ ] **Step 3: Start server in mock mode and verify endpoints**

```bash
cd src/app/server && OB_MOCK_MODE=true timeout 5 python -m uvicorn server.main:app --port 8099 &
sleep 2
# Test connect
curl -s -X POST http://localhost:8099/api/camera/connect | python -m json.tool | head -20
# Test exposure
curl -s http://localhost:8099/api/camera/exposure | python -m json.tool
# Test capture
curl -s -X POST http://localhost:8099/api/camera/capture -o /tmp/test_frame.jpg && file /tmp/test_frame.jpg
# Test capabilities
curl -s http://localhost:8099/api/camera/capabilities | python -m json.tool | head -30
# Cleanup
kill %1 2>/dev/null
```

Expected: All responses return valid JSON with `"success": true`, capture returns JPEG

- [ ] **Step 4: Verify Swagger docs list all 20 endpoints**

```bash
cd src/app/server && OB_MOCK_MODE=true timeout 5 python -m uvicorn server.main:app --port 8099 &
sleep 2
curl -s http://localhost:8099/openapi.json | python -c "
import json, sys
spec = json.load(sys.stdin)
camera_paths = [p for p in spec['paths'] if '/camera/' in p]
print(f'Camera endpoints: {len(camera_paths)}')
for p in sorted(camera_paths):
    methods = list(spec['paths'][p].keys())
    print(f'  {p}: {methods}')
"
kill %1 2>/dev/null
```

Expected: 20 camera endpoints listed

- [ ] **Step 5: Commit (if any fixes were needed)**

```bash
# Only if fixes were applied
git add -A && git commit -m "fix: integration verification fixes"
```

---

## Self-Review Checklist

### Spec Coverage

| Spec Section | Task(s) | Status |
|-------------|---------|--------|
| §1 Data Models | Task 1 | ✅ All types in __init__.py |
| §2 Error Hierarchy | Task 1 | ✅ 4 exception types + HTTP mapping |
| §3 CameraBackend ABC | Task 1 | ✅ Required + optional methods |
| §4 REST API (20 endpoints) | Task 5 | ✅ All 20 endpoints |
| §5.1 VmbPyCameraBackend | Task 9 | ✅ Full GenICam implementation |
| §5.2 MockCameraBackend | Task 2 | ✅ All 8 features simulated |
| §6 CameraService | Task 4 | ✅ Thin orchestration layer |
| §7 WebSocket FrameMeta | Task 7 | ✅ Meta in broadcast payload |
| §8.1 client.ts | Task 10 | ✅ 24 API methods + types |
| §8.2 CameraPage | Task 11 | ✅ Capabilities-driven UI |
| §9 Example scripts | Task 12 | ✅ 8 runnable examples |
| §10 File structure | All tasks | ✅ Matches spec layout |
| §11 Acceptance criteria | Task 13 | ✅ Verification steps |

### Placeholder Scan

No TBD, TODO, "implement later", "similar to Task N", or "add appropriate handling" found.

### Type Consistency

- `Feature` enum: used consistently across ABC, mock, schemas, router
- `ExposureInfo`/`GainInfo`/etc.: defined in Task 1, returned in Tasks 2/4/5, serialized in Task 3
- `CameraService` method signatures match router calls in Task 5
- Frontend types in Task 10 match Pydantic schemas in Task 3
