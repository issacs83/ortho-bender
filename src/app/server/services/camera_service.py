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

    def capabilities_raw(self) -> dict:
        """Raw Feature→FeatureCapability dict for schema serialization."""
        return self._backend.capabilities()

    def device_info(self) -> dict:
        d = self._backend.device_info()
        return {"model": d.model, "serial": d.serial,
                "firmware": d.firmware, "vendor": d.vendor}

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
