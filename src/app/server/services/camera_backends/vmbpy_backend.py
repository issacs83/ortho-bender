# src/app/server/services/camera_backends/vmbpy_backend.py
"""
vmbpy_backend.py — Allied Vision Alvium camera backend via VmbPy SDK.

Targets Alvium 1800 U-158m (USB3 Vision). A dedicated OS thread owns the
VmbSystem + Camera `with` contexts for their entire lifetime. All VmbPy
calls (frame acquisition AND feature reads/writes) are marshalled onto
that thread through a command queue. This avoids VmbPy's cross-thread
context failure mode where `Called X outside of 'with' context` triggers
when calls straddle asyncio executor workers.

Requires: vmbpy (Vimba X Python SDK)

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import concurrent.futures as _cf
import logging
import queue as _queue
import threading as _threading
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
    """Allied Vision Alvium camera via VmbPy.

    Architecture
    ------------
    A single dedicated OS thread (_camera_thread) owns the full VmbPy
    lifecycle: it enters `with VmbSystem: with Camera:` once and runs
    get_frame_generator in a tight loop until stop is requested.

    All other VmbPy operations (feature reads/writes, USB commands) are
    submitted through _cmd_queue; the camera thread drains the queue
    between frames. This guarantees every VmbPy call happens from the
    SAME thread that holds the active context, which is what the SDK
    assumes internally despite `_context_entered` being a plain bool.

    Why not asyncio.run_in_executor(None, ...):
    Different executor workers caused `Camera.get_frame_generator()
    outside of 'with' context` errors even though _context_entered
    was True — VmbPy's native handle has thread affinity.
    """

    def __init__(self) -> None:
        self._vmb = None           # VmbSystem instance (owned by camera thread)
        self._cam = None           # Camera instance (owned by camera thread)
        self._device: Optional[DeviceInfo] = None
        self._connected = False
        self._streaming = False
        self._frame_count = 0
        self._start_time = 0.0
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Camera thread + signalling
        self._camera_thread: Optional[_threading.Thread] = None
        self._ready_event: Optional[_threading.Event] = None
        self._stop_event: Optional[_threading.Event] = None
        self._cmd_queue: Optional[_queue.Queue] = None
        self._thread_error: Optional[BaseException] = None
        # When set, the producer exits its frame generator and waits. Used
        # for operations that mutate acquisition-critical features (UserSetLoad)
        # which break an active stream otherwise.
        self._acq_pause_event: Optional[_threading.Event] = None

        # Frame broadcast subscribers (asyncio.Queue feeding /capture, /stream, /ws)
        self._broadcast_subs: list = []

        # Telemetry cache (updated from each captured frame)
        self._meta_cache = (None, None, None, "Mono8")
        self._status_roi_cache: Optional[dict] = None
        self._status_trigger_cache: Optional[str] = "freerun"

    # --- Internal: command dispatch to camera thread ---

    def _require_connected(self) -> None:
        if not self._connected or self._cam is None:
            raise CameraDisconnectedError("Camera not connected")

    def _submit(self, fn, *args, **kwargs) -> _cf.Future:
        """Queue fn to run on the camera thread. Returns a Future."""
        fut: _cf.Future = _cf.Future()
        if self._cmd_queue is None or not self._connected:
            fut.set_exception(CameraDisconnectedError("Camera not connected"))
            return fut

        def _wrapped():
            return fn(*args, **kwargs)
        try:
            self._cmd_queue.put_nowait((fut, _wrapped))
        except Exception as exc:
            fut.set_exception(exc)
        return fut

    async def _run_sync(self, fn, *args, **kwargs):
        """Run fn on the camera thread (async wrapper)."""
        fut = self._submit(fn, *args, **kwargs)
        return await asyncio.wrap_future(fut, loop=self._loop)

    # --- Connection ---

    async def connect(self) -> DeviceInfo:
        if self._connected:
            return self._device
        self._loop = asyncio.get_event_loop()

        self._ready_event = _threading.Event()
        self._stop_event = _threading.Event()
        self._acq_pause_event = _threading.Event()
        self._cmd_queue = _queue.Queue()
        self._thread_error = None
        self._frame_count = 0
        self._start_time = time.monotonic()

        self._camera_thread = _threading.Thread(
            target=self._camera_main, daemon=True, name="vmbpy-camera",
        )
        self._camera_thread.start()

        # Wait for thread to either complete camera open or report error.
        ready = await self._loop.run_in_executor(None, self._ready_event.wait, 20.0)
        if not ready:
            self._stop_event.set()
            raise CameraDisconnectedError("Camera thread did not become ready")
        if self._thread_error is not None:
            err = self._thread_error
            self._thread_error = None
            # Thread has already exited; clear state.
            self._connected = False
            self._cmd_queue = None
            raise err if isinstance(err, Exception) else CameraDisconnectedError(str(err))

        self._connected = True
        log.info("VmbPy connected: %s %s", self._device.vendor, self._device.model)
        return self._device

    async def disconnect(self) -> None:
        if not self._connected and (self._camera_thread is None):
            return
        self._connected = False
        self._streaming = False
        if self._stop_event is not None:
            self._stop_event.set()
        if self._camera_thread is not None and self._camera_thread.is_alive():
            loop = self._loop or asyncio.get_event_loop()
            await loop.run_in_executor(None, self._camera_thread.join, 10.0)
        self._camera_thread = None
        self._cam = None
        self._vmb = None
        self._cmd_queue = None
        log.info("VmbPy disconnected")

    # --- Camera thread main loop ---

    def _camera_main(self) -> None:
        """Owns VmbSystem + Camera contexts. Pumps frames and commands."""
        import vmbpy
        import cv2

        try:
            vmb = vmbpy.VmbSystem.get_instance()
            with vmb:
                self._vmb = vmb
                cams = vmb.get_all_cameras()
                if not cams:
                    self._thread_error = CameraDisconnectedError("No cameras found")
                    self._ready_event.set()
                    return
                cam = cams[0]
                with cam:
                    # Clear any lingering acquisition state from a prior
                    # crashed producer. Without this, get_frame_generator
                    # fails with VmbError.Already(-33).
                    try:
                        cam.stop_streaming()
                    except Exception:
                        pass
                    try:
                        cam.get_feature_by_name("AcquisitionStop").run()
                    except Exception:
                        pass

                    def _safe(name: str, default: str = "unknown") -> str:
                        try:
                            return str(cam.get_feature_by_name(name).get())
                        except Exception:
                            return default

                    self._cam = cam
                    self._device = DeviceInfo(
                        model=cam.get_model(),
                        serial=cam.get_serial(),
                        firmware=_safe("DeviceFirmwareVersion", "0.0.0"),
                        vendor=_safe("DeviceVendorName", "Unknown"),
                    )
                    # Seed meta cache with current feature values (safe: no acq).
                    try:
                        self._meta_cache = (
                            float(cam.get_feature_by_name("ExposureTime").get())
                                if self._meta_cache[0] is None else self._meta_cache[0],
                            float(cam.get_feature_by_name("Gain").get())
                                if self._meta_cache[1] is None else self._meta_cache[1],
                            float(cam.get_feature_by_name("DeviceTemperature").get())
                                if self._meta_cache[2] is None else self._meta_cache[2],
                            str(cam.get_feature_by_name("PixelFormat").get()),
                        )
                    except Exception:
                        pass

                    self._ready_event.set()
                    log.info("Camera thread: context entered, ready")

                    # Main pump: run commands and frame acquisition together.
                    mono_fmt = vmbpy.PixelFormat.Mono8
                    restart_delay = 0.0
                    # Refresh Gain / DeviceTemperature / PixelFormat every 2s
                    # directly on this thread (we own the context).
                    last_meta_refresh = 0.0
                    META_REFRESH_INTERVAL = 2.0
                    while not self._stop_event.is_set():
                        self._drain_cmds(budget_s=0.02)
                        if self._stop_event.is_set():
                            break
                        # If paused, stay out of the frame generator entirely.
                        # Commands (e.g. UserSetLoad) still run via _drain_cmds.
                        if self._acq_pause_event is not None and \
                                self._acq_pause_event.is_set():
                            self._streaming = False
                            time.sleep(0.05)
                            continue
                        if restart_delay > 0:
                            time.sleep(min(restart_delay, 0.5))
                            restart_delay = max(0.0, restart_delay - 0.5)
                            continue
                        self._streaming = True
                        frame_idx = 0
                        # Timeout must exceed the longest possible exposure —
                        # Alvium auto-exposure can climb to 10s in dim light.
                        try:
                            for frame in cam.get_frame_generator(limit=None, timeout_ms=15000):
                                if self._stop_event.is_set():
                                    break
                                if self._acq_pause_event is not None and \
                                        self._acq_pause_event.is_set():
                                    break
                                frame_idx += 1
                                # Process any queued commands between frames.
                                self._drain_cmds(budget_s=0.0)
                                try:
                                    frame.convert_pixel_format(mono_fmt)
                                    arr = frame.as_numpy_ndarray()
                                except Exception as exc:
                                    log.warning("Frame convert failed (idx=%d): %s",
                                                frame_idx, exc)
                                    continue
                                # Refresh exposure from the frame itself.
                                try:
                                    if hasattr(frame, "get_exposure_time"):
                                        self._meta_cache = (
                                            float(frame.get_exposure_time()),
                                            self._meta_cache[1],
                                            self._meta_cache[2],
                                            self._meta_cache[3],
                                        )
                                except Exception:
                                    pass
                                # Periodic refresh of Gain / Temperature /
                                # PixelFormat — safe here since we own the
                                # camera context on this thread.
                                now_mono = time.monotonic()
                                if now_mono - last_meta_refresh >= META_REFRESH_INTERVAL:
                                    last_meta_refresh = now_mono
                                    try:
                                        g = float(cam.get_feature_by_name("Gain").get())
                                    except Exception:
                                        g = self._meta_cache[1]
                                    try:
                                        t = float(cam.get_feature_by_name("DeviceTemperature").get())
                                    except Exception:
                                        t = self._meta_cache[2]
                                    try:
                                        pf = str(cam.get_feature_by_name("PixelFormat").get())
                                    except Exception:
                                        pf = self._meta_cache[3]
                                    self._meta_cache = (
                                        self._meta_cache[0], g, t, pf,
                                    )
                                # JPEG encode once per frame, share across consumers.
                                try:
                                    img = arr if arr.ndim == 2 else cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                                    ok, buf = cv2.imencode('.jpg', img,
                                                           [cv2.IMWRITE_JPEG_QUALITY, 70])
                                    jpeg = buf.tobytes() if ok else None
                                except Exception as exc:
                                    log.warning("JPEG encode failed: %s", exc)
                                    jpeg = None
                                payload = (arr.copy(), jpeg, arr.shape[1], arr.shape[0])
                                self._dispatch_to_subs(payload)
                                if frame_idx % 60 == 0:
                                    log.info("Producer heartbeat: frame=%d subs=%d",
                                             frame_idx, len(self._broadcast_subs))
                        except Exception as exc:
                            log.exception("Acquisition error (idx=%d): %s",
                                          frame_idx, exc)
                            self._streaming = False
                            # Try to recover: stop streaming, pause, re-enter generator.
                            try:
                                cam.stop_streaming()
                            except Exception:
                                pass
                            try:
                                cam.get_feature_by_name("AcquisitionStop").run()
                            except Exception:
                                pass
                            restart_delay = 1.0
                        else:
                            self._streaming = False
                            # Clean stop when we exited the generator normally
                            # (e.g. pause requested). Leaving the stream open
                            # would prevent operations like UserSetLoad.
                            try:
                                cam.stop_streaming()
                            except Exception:
                                pass
                            try:
                                cam.get_feature_by_name("AcquisitionStop").run()
                            except Exception:
                                pass

                    self._streaming = False
                    # Final cleanup before dropping out of context.
                    try:
                        cam.stop_streaming()
                    except Exception:
                        pass
                    try:
                        cam.get_feature_by_name("AcquisitionStop").run()
                    except Exception:
                        pass
        except Exception as exc:
            log.exception("Camera thread fatal: %s", exc)
            self._thread_error = exc
            if self._ready_event is not None and not self._ready_event.is_set():
                self._ready_event.set()
        finally:
            self._streaming = False
            self._connected = False
            self._cam = None
            self._vmb = None
            # Drain any remaining commands with a disconnected error.
            if self._cmd_queue is not None:
                while True:
                    try:
                        fut, _ = self._cmd_queue.get_nowait()
                    except _queue.Empty:
                        break
                    try:
                        fut.set_exception(CameraDisconnectedError(
                            "Camera thread exited"))
                    except Exception:
                        pass
            # Close subscriber queues.
            loop = self._loop
            if loop is not None:
                def _close_all():
                    for q in list(self._broadcast_subs):
                        try:
                            q.put_nowait(None)
                        except Exception:
                            pass
                    self._broadcast_subs.clear()
                try:
                    loop.call_soon_threadsafe(_close_all)
                except Exception:
                    pass
            log.info("Camera thread exited")

    def _drain_cmds(self, budget_s: float) -> None:
        """Run queued feature commands on the camera thread.

        budget_s=0 -> only drain what's ready right now (get_nowait).
        budget_s>0 -> block up to that many seconds for the first item.
        """
        if self._cmd_queue is None:
            return
        deadline = time.monotonic() + budget_s if budget_s > 0 else 0.0
        first = True
        while True:
            try:
                if first and budget_s > 0:
                    timeout = max(0.001, deadline - time.monotonic())
                    fut, fn = self._cmd_queue.get(timeout=timeout)
                else:
                    fut, fn = self._cmd_queue.get_nowait()
            except _queue.Empty:
                return
            first = False
            if fut.cancelled():
                continue
            try:
                result = fn()
                fut.set_result(result)
            except BaseException as exc:
                try:
                    fut.set_exception(exc)
                except Exception:
                    pass
            if budget_s <= 0:
                # Keep draining whatever else is ready.
                continue
            if time.monotonic() >= deadline:
                return

    def _dispatch_to_subs(self, payload) -> None:
        """Enqueue a frame payload onto every subscriber's asyncio.Queue."""
        loop = self._loop
        if loop is None:
            return

        def _dispatch():
            dead = []
            for q in list(self._broadcast_subs):
                if q.full():
                    try:
                        q.get_nowait()
                    except Exception:
                        pass
                try:
                    q.put_nowait(payload)
                except Exception:
                    dead.append(q)
            for q in dead:
                try:
                    self._broadcast_subs.remove(q)
                except ValueError:
                    pass
        try:
            loop.call_soon_threadsafe(_dispatch)
        except RuntimeError:
            pass

    # --- Frame capture ---

    async def capture(self) -> CapturedFrame:
        self._require_connected()
        self._frame_count += 1

        # Subscribe to the broadcast producer and wait for one frame.
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        self._broadcast_subs.append(queue)
        # Timeout must be > 2x the longest exposure so a concurrent capture
        # that just missed a frame can still wait for the next one.
        exp_s = (self._meta_cache[0] or 0.0) / 1_000_000.0
        cap_timeout = max(5.0, 2.5 * exp_s + 2.0)
        try:
            item = await asyncio.wait_for(queue.get(), timeout=cap_timeout)
        except asyncio.TimeoutError as exc:
            raise CameraTimeoutError("Broadcast frame wait timed out") from exc
        finally:
            try:
                self._broadcast_subs.remove(queue)
            except ValueError:
                pass
        if item is None:
            raise CameraTimeoutError("Broadcast producer stopped")
        arr, jpeg, w, h = item

        elapsed = time.monotonic() - self._start_time
        fps = self._frame_count / max(elapsed, 0.001)
        exp_us, gain_db, temp, pf = self._meta_cache
        meta = FrameMeta(
            timestamp_us=int(time.monotonic() * 1_000_000),
            exposure_us=exp_us,
            gain_db=gain_db,
            temperature_c=temp,
            fps_actual=round(fps, 2),
            width=w,
            height=h,
        )
        cf = CapturedFrame(
            array=arr,
            pixel_format=_FORMAT_MAP_INV.get(pf, pf),
            meta=meta,
        )
        if jpeg is not None:
            cf.__dict__["_cached_jpeg"] = jpeg
        return cf

    async def stream(self, fps: float = 30.0) -> AsyncIterator[CapturedFrame]:
        self._require_connected()
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        self._broadcast_subs.append(queue)
        try:
            while self._connected:
                item = await queue.get()
                if item is None:
                    break
                arr, jpeg, w, h = item
                self._frame_count += 1
                elapsed = time.monotonic() - self._start_time
                actual = self._frame_count / max(elapsed, 0.001)

                exp_us, gain_db, temp, pf = self._meta_cache
                meta = FrameMeta(
                    timestamp_us=int(time.monotonic() * 1_000_000),
                    exposure_us=exp_us,
                    gain_db=gain_db,
                    temperature_c=temp,
                    fps_actual=round(actual, 2),
                    width=w,
                    height=h,
                )
                cf = CapturedFrame(
                    array=arr,
                    pixel_format=_FORMAT_MAP_INV.get(pf, pf),
                    meta=meta,
                )
                if jpeg is not None:
                    cf.__dict__["_cached_jpeg"] = jpeg
                yield cf
        finally:
            try:
                self._broadcast_subs.remove(queue)
            except ValueError:
                pass

    # --- Capabilities (sync helpers — called via command queue) ---

    def capabilities(self) -> dict[Feature, FeatureCapability]:
        self._require_connected()
        # These helpers currently touch self._cam directly. Because the
        # context is held for the thread's lifetime _context_entered
        # stays True, so a quick touch from the asyncio thread is
        # normally fine; but for correctness we still prefer the queue.
        fut = self._submit(self._capabilities_sync)
        try:
            return fut.result(timeout=5.0)
        except Exception:
            return {}

    def _capabilities_sync(self) -> dict[Feature, FeatureCapability]:
        caps = {}
        caps[Feature.EXPOSURE] = FeatureCapability(
            supported=True,
            range=self._get_numeric_range("ExposureTime"),
            auto_available=self._has_feature("ExposureAuto"),
        )
        caps[Feature.GAIN] = FeatureCapability(
            supported=self._has_feature("Gain"),
            range=self._get_numeric_range("Gain") if self._has_feature("Gain") else None,
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
        # During active acquisition, reading live GenICam features races
        # with the frame generator and produces VmbError.Already/NotFound
        # floods. Use the cached meta (refreshed per frame) instead.
        if self._streaming:
            exp, gain, temp, pf = self._meta_cache
            elapsed = time.monotonic() - self._start_time
            fps_live = round(self._frame_count / max(elapsed, 0.001), 2) \
                       if self._frame_count else None
            return CameraStatus(
                connected=True, streaming=True, device=self._device,
                current_exposure_us=exp, current_gain_db=gain,
                current_temperature_c=temp, current_fps=fps_live,
                current_pixel_format=_FORMAT_MAP_INV.get(pf, pf) if pf else None,
                current_roi=self._status_roi_cache,
                current_trigger_mode=self._status_trigger_cache or "freerun",
            )
        try:
            exp = await self._get_feature_value("ExposureTime")
        except Exception:
            exp = None
        try:
            gain = await self._get_feature_value("Gain")
        except Exception:
            gain = None
        try:
            temp = await self._get_feature_value("DeviceTemperature")
        except Exception:
            temp = None
        try:
            fps = await self._get_feature_value("AcquisitionFrameRate")
        except Exception:
            fps = None
        try:
            pf = await self._get_feature_value_str("PixelFormat")
        except Exception:
            pf = "Mono8"
        try:
            w = int(await self._get_feature_value("Width"))
            h = int(await self._get_feature_value("Height"))
            ox = int(await self._get_feature_value("OffsetX"))
            oy = int(await self._get_feature_value("OffsetY"))
            roi = {"width": w, "height": h, "offset_x": ox, "offset_y": oy}
        except Exception:
            roi = None
        try:
            trigger_mode = await self._get_feature_value_str("TriggerMode")
            trig = "freerun" if trigger_mode == "Off" else trigger_mode.lower()
        except Exception:
            trig = "freerun"
        self._status_roi_cache = roi
        self._status_trigger_cache = trig
        self._meta_cache = (exp, gain, temp, pf)
        return CameraStatus(
            connected=True, streaming=self._streaming, device=self._device,
            current_exposure_us=exp, current_gain_db=gain,
            current_temperature_c=temp, current_fps=fps,
            current_pixel_format=_FORMAT_MAP_INV.get(pf, pf) if pf else None,
            current_roi=roi,
            current_trigger_mode=trig,
        )

    def device_info(self) -> DeviceInfo:
        self._require_connected()
        return self._device

    # --- Exposure ---

    async def set_exposure(self, *, auto: bool = False,
                           time_us: Optional[float] = None) -> ExposureInfo:
        self._require_connected()
        if auto:
            if not self._has_feature_async("ExposureAuto"):
                from . import FeatureNotSupportedError
                raise FeatureNotSupportedError(Feature.EXPOSURE)
            await self._set_feature_str("ExposureAuto", "Continuous")
        else:
            if self._has_feature_async("ExposureAuto"):
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
        has_auto = self._has_feature_async("ExposureAuto")
        if has_auto:
            auto_str = await self._get_feature_value_str("ExposureAuto")
            is_auto = auto_str != "Off"
        else:
            is_auto = False
        return ExposureInfo(
            auto=is_auto,
            time_us=val,
            range=self._get_numeric_range("ExposureTime"),
            auto_available=has_auto,
        )

    # --- Gain ---

    async def set_gain(self, *, auto: bool = False,
                       value_db: Optional[float] = None) -> GainInfo:
        from . import FeatureNotSupportedError
        self._require_connected()
        if not self._has_feature_async("Gain"):
            raise FeatureNotSupportedError(Feature.GAIN)
        if auto:
            if not self._has_feature_async("GainAuto"):
                raise FeatureNotSupportedError(Feature.GAIN)
            await self._set_feature_str("GainAuto", "Continuous")
        else:
            if self._has_feature_async("GainAuto"):
                await self._set_feature_str("GainAuto", "Off")
            if value_db is not None:
                r = self._get_numeric_range("Gain")
                if value_db < r.min or value_db > r.max:
                    raise FeatureOutOfRangeError(Feature.GAIN, value_db, r)
                await self._set_feature_value("Gain", value_db)
                self._meta_cache = (
                    self._meta_cache[0], float(value_db),
                    self._meta_cache[2], self._meta_cache[3],
                )
        return await self.get_gain()

    async def get_gain(self) -> GainInfo:
        from . import FeatureNotSupportedError
        self._require_connected()
        if not self._has_feature_async("Gain"):
            raise FeatureNotSupportedError(Feature.GAIN)
        val = await self._get_feature_value("Gain")
        has_auto = self._has_feature_async("GainAuto")
        if has_auto:
            auto_str = await self._get_feature_value_str("GainAuto")
            is_auto = auto_str != "Off"
        else:
            is_auto = False
        return GainInfo(
            auto=is_auto,
            value_db=val,
            range=self._get_numeric_range("Gain"),
            auto_available=has_auto,
        )

    # --- ROI ---

    async def set_roi(self, *, width: int, height: int,
                      offset_x: int = 0, offset_y: int = 0) -> RoiInfo:
        self._require_connected()
        await self._set_feature_value("OffsetX", 0)
        await self._set_feature_value("OffsetY", 0)
        await self._set_feature_value("Width", width)
        await self._set_feature_value("Height", height)
        await self._set_feature_value("OffsetX", offset_x)
        await self._set_feature_value("OffsetY", offset_y)
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
        max_w = int(await self._get_feature_value("WidthMax"))
        max_h = int(await self._get_feature_value("HeightMax"))
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
        await self._set_feature_str("PixelFormat", vmb_name)
        self._meta_cache = (
            self._meta_cache[0], self._meta_cache[1],
            self._meta_cache[2], vmb_name,
        )
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
        if self._has_feature_async("AcquisitionFrameRateEnable"):
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
        if self._has_feature_async("AcquisitionFrameRateEnable"):
            enable = bool(await self._get_feature_value("AcquisitionFrameRateEnable"))
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

        def _fire():
            self._cam.get_feature_by_name("TriggerSoftware").run()
        await self._run_sync(_fire)

    # --- Temperature ---

    async def get_temperature(self) -> float:
        self._require_connected()
        return await self._get_feature_value("DeviceTemperature")

    # --- UserSet ---

    async def load_user_set(self, *, slot: str) -> None:
        """Factory-reset helper: loads a UserSet slot safely.

        UserSetLoad mutates acquisition-critical features (pixel format,
        ROI, payload size) — running it during an active frame generator
        triggers VmbError.InternalFault and breaks the stream. We pause
        the producer first, load the set, then resume.
        """
        self._require_connected()
        if self._acq_pause_event is None:
            raise CameraDisconnectedError("Camera not connected")

        self._acq_pause_event.set()
        try:
            # Wait for producer to exit the frame generator and stop the
            # stream. 0.3s covers the typical frame interval (15 fps = 66 ms)
            # plus the stop_streaming round-trip.
            await asyncio.sleep(0.3)
            # Now-safe: selector + load run while no acquisition is active.
            await self._set_feature_str("UserSetSelector", slot)

            def _load():
                self._cam.get_feature_by_name("UserSetLoad").run()
            await self._run_sync(_load)
            # Give the camera a moment to settle after load — some features
            # reconfigure asynchronously inside the firmware.
            await asyncio.sleep(0.4)
            # Re-seed meta cache from the loaded values so status endpoints
            # reflect the reset immediately.

            def _reseed():
                try:
                    self._meta_cache = (
                        float(self._cam.get_feature_by_name("ExposureTime").get()),
                        float(self._cam.get_feature_by_name("Gain").get()),
                        float(self._cam.get_feature_by_name("DeviceTemperature").get()),
                        str(self._cam.get_feature_by_name("PixelFormat").get()),
                    )
                except Exception:
                    pass
            await self._run_sync(_reseed)
        finally:
            self._acq_pause_event.clear()

    async def save_user_set(self, *, slot: str) -> None:
        self._require_connected()
        await self._set_feature_str("UserSetSelector", slot)

        def _save():
            self._cam.get_feature_by_name("UserSetSave").run()
        await self._run_sync(_save)

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
        """Sync probe — must be called from camera thread."""
        try:
            self._cam.get_feature_by_name(name)
            return True
        except Exception:
            return False

    def _has_feature_async(self, name: str) -> bool:
        """Probe feature existence via command queue (blocks briefly)."""
        try:
            fut = self._submit(self._has_feature, name)
            return bool(fut.result(timeout=2.0))
        except Exception:
            return False

    def _get_numeric_range(self, name: str) -> NumericRange:
        """Numeric range probe. Called via _capabilities_sync (camera thread)."""
        try:
            feat = self._cam.get_feature_by_name(name)
            r = feat.get_range()
            inc = feat.get_increment() if hasattr(feat, 'get_increment') else 1
            return NumericRange(min=r[0], max=r[1], step=inc if inc else 1)
        except Exception:
            return NumericRange(min=0, max=0, step=1)

    def _get_enum_entries(self, name: str) -> list[str]:
        """Enum entries probe."""
        try:
            feat = self._cam.get_feature_by_name(name)
            entries = feat.get_available_entries()
            return [str(e) for e in entries]
        except Exception:
            return []

    async def _get_feature_value(self, name: str):
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
