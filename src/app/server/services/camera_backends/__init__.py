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
    model: str
    serial: str
    firmware: str
    vendor: str


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
    array: np.ndarray
    pixel_format: str
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
    current_roi: Optional[dict]
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
    mode: str
    source: Optional[str]
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

    Lifecycle: connect() -> use -> disconnect()
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
