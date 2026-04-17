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
