"""
mock_backend.py — Mock camera backend for development and CI.

Simulates all 8 camera features with ranges matching Alvium 1800 U-158m.
Generates synthetic gradient frames (numpy). No hardware required.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
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


_SENSOR_W = 1456
_SENSOR_H = 1088
_EXP_RANGE = NumericRange(min=20, max=10_000_000, step=1)
_GAIN_RANGE = NumericRange(min=0, max=48, step=0.1)
_FPS_RANGE = NumericRange(min=1, max=133, step=0.01)
_FORMATS = ["mono8", "mono10", "mono12", "bayer_rg8", "bayer_rg10", "bayer_rg12", "rgb8"]
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
            Feature.EXPOSURE: FeatureCapability(supported=True, range=_EXP_RANGE, auto_available=True),
            Feature.GAIN: FeatureCapability(supported=True, range=_GAIN_RANGE, auto_available=True),
            Feature.ROI: FeatureCapability(supported=True, range=NumericRange(min=1, max=_SENSOR_W, step=1)),
            Feature.PIXEL_FORMAT: FeatureCapability(supported=True, available_values=list(_FORMATS)),
            Feature.FRAME_RATE: FeatureCapability(supported=True, range=_FPS_RANGE),
            Feature.TRIGGER: FeatureCapability(supported=True, available_values=list(_TRIGGER_MODES)),
            Feature.TEMPERATURE: FeatureCapability(supported=True),
            Feature.USER_SET: FeatureCapability(supported=True, slots=list(_USER_SET_SLOTS)),
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
                         "offset_x": self._roi_ox, "offset_y": self._roi_oy} if self._connected else None,
            current_trigger_mode=self._trigger_mode if self._connected else None,
        )

    def device_info(self) -> DeviceInfo:
        self._require_connected()
        return self._device

    async def set_exposure(self, *, auto: bool = False, time_us: Optional[float] = None) -> ExposureInfo:
        self._require_connected()
        self._exposure_auto = auto
        if not auto and time_us is not None:
            if time_us < _EXP_RANGE.min or time_us > _EXP_RANGE.max:
                raise FeatureOutOfRangeError(Feature.EXPOSURE, time_us, _EXP_RANGE)
            self._exposure_us = time_us
        return await self.get_exposure()

    async def get_exposure(self) -> ExposureInfo:
        self._require_connected()
        return ExposureInfo(auto=self._exposure_auto, time_us=self._exposure_us, range=_EXP_RANGE, auto_available=True)

    async def set_gain(self, *, auto: bool = False, value_db: Optional[float] = None) -> GainInfo:
        self._require_connected()
        self._gain_auto = auto
        if not auto and value_db is not None:
            if value_db < _GAIN_RANGE.min or value_db > _GAIN_RANGE.max:
                raise FeatureOutOfRangeError(Feature.GAIN, value_db, _GAIN_RANGE)
            self._gain_db = value_db
        return await self.get_gain()

    async def get_gain(self) -> GainInfo:
        self._require_connected()
        return GainInfo(auto=self._gain_auto, value_db=self._gain_db, range=_GAIN_RANGE, auto_available=True)

    async def set_roi(self, *, width: int, height: int, offset_x: int = 0, offset_y: int = 0) -> RoiInfo:
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
        return await self.set_roi(width=self._roi_w, height=self._roi_h, offset_x=ox, offset_y=oy)

    async def set_pixel_format(self, *, format: str) -> PixelFormatInfo:
        self._require_connected()
        if format not in _FORMATS:
            raise FeatureOutOfRangeError(Feature.PIXEL_FORMAT, 0, NumericRange(min=0, max=len(_FORMATS) - 1, step=1))
        self._pixel_format = format
        info = await self.get_pixel_format()
        info.invalidated = [Feature.FRAME_RATE]
        return info

    async def get_pixel_format(self) -> PixelFormatInfo:
        self._require_connected()
        return PixelFormatInfo(format=self._pixel_format, available=list(_FORMATS))

    async def set_frame_rate(self, *, enable: bool, value: Optional[float] = None) -> FrameRateInfo:
        self._require_connected()
        self._fps_enable = enable
        if enable and value is not None:
            if value < _FPS_RANGE.min or value > _FPS_RANGE.max:
                raise FeatureOutOfRangeError(Feature.FRAME_RATE, value, _FPS_RANGE)
            self._fps_value = value
        return await self.get_frame_rate()

    async def get_frame_rate(self) -> FrameRateInfo:
        self._require_connected()
        return FrameRateInfo(enable=self._fps_enable, value=self._fps_value, range=_FPS_RANGE)

    async def set_trigger(self, *, mode: str, source: Optional[str] = None) -> TriggerInfo:
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
            available_modes=list(_TRIGGER_MODES), available_sources=list(_TRIGGER_SOURCES),
        )

    async def fire_trigger(self) -> None:
        self._require_connected()

    async def get_temperature(self) -> float:
        self._require_connected()
        return round(self._temperature, 1)

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

    def _generate_frame(self) -> np.ndarray:
        """Generate a synthetic gradient frame."""
        h, w = self._roi_h, self._roi_w
        row = np.linspace(0, 255, w, dtype=np.uint8)
        frame = np.tile(row, (h, 1))
        shift = self._frame_count % w
        frame = np.roll(frame, shift, axis=1)
        return frame
