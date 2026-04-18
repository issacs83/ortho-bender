"""
auto_backend.py -- Hot-plug auto-selecting camera backend wrapper.

AutoCameraBackend scans the USB bus periodically and selects the matching
sub-backend (Allied Vision VmbPy or NOVITEC libusb) based on the vendor ID
(VID) currently present.  When the user swaps cameras at runtime, the
wrapper:

  1. Disconnects the previous sub-backend.
  2. Emits ``camera_disconnected`` on the WebSocket event callback.
  3. Connects the new sub-backend matching the newly detected VID.
  4. Emits ``camera_connected`` with device info payload.

The wrapper implements the full CameraBackend ABC and transparently
delegates all feature calls to the currently active sub-backend.
When no camera is present every feature call raises
``CameraDisconnectedError``; ``capabilities()`` returns an empty dict and
``get_status()`` returns a disconnected snapshot.

USB detection order of preference:
  1. ``usb.core`` (pyusb) -- preferred, no subprocess.
  2. ``lsusb`` subprocess parse -- fallback when pyusb is absent.

Thread safety:
  - All public methods are async and take an internal asyncio.Lock when
    they need to swap the sub-backend.  Individual feature calls delegate
    without additional locking (the owning CameraService already provides
    coarse-grained serialisation).

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Optional

from . import (
    CameraBackend,
    CameraDisconnectedError,
    CameraError,
    CameraStatus,
    CapturedFrame,
    DeviceInfo,
    Feature,
    FeatureCapability,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vendor map -- VID -> (backend short name, friendly model family)
# ---------------------------------------------------------------------------

_VENDOR_MAP: dict[int, tuple[str, str]] = {
    0x1AB2: ("vmbpy",   "Alvium"),    # Allied Vision
    0x2B00: ("novitec", "u-Nova2"),   # NOVITEC
}


# Priority order when multiple cameras are attached simultaneously.
# First match wins -- Alvium is preferred because it has the richer SDK.
_VENDOR_PRIORITY: tuple[int, ...] = (0x1AB2, 0x2B00)


# Default scan cadence (seconds).  Overridden by OB_CAMERA_SCAN_INTERVAL.
_DEFAULT_SCAN_INTERVAL = 2.0


WsEventCallback = Callable[[dict], Awaitable[None]]


# ---------------------------------------------------------------------------
# USB scanning helpers
# ---------------------------------------------------------------------------

def _scan_usb_pyusb() -> Optional[set[int]]:
    """
    Return the set of all VIDs currently on the USB bus via pyusb.

    Returns None when pyusb is not installed (caller falls back to lsusb).
    Returns an empty set when pyusb works but no devices are attached.
    """
    try:
        import usb.core  # type: ignore
    except ImportError:
        return None
    try:
        vids: set[int] = set()
        for dev in usb.core.find(find_all=True):
            try:
                vids.add(int(dev.idVendor))
            except Exception:
                continue
        return vids
    except Exception as exc:
        log.debug("pyusb scan raised: %s", exc)
        return None


_LSUSB_RE = re.compile(r"ID\s+([0-9a-fA-F]{4}):([0-9a-fA-F]{4})")


def _scan_usb_lsusb() -> set[int]:
    """Fallback USB scan using ``lsusb``.

    Returns an empty set when lsusb is not installed or returns non-zero.
    """
    try:
        result = subprocess.run(
            ["lsusb"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
    except FileNotFoundError:
        log.warning("lsusb not found -- cannot scan USB bus")
        return set()
    except subprocess.TimeoutExpired:
        log.warning("lsusb timed out")
        return set()
    except Exception as exc:
        log.warning("lsusb failed: %s", exc)
        return set()

    if result.returncode != 0:
        log.debug("lsusb returned %d: %s", result.returncode, result.stderr)
        return set()

    vids: set[int] = set()
    for match in _LSUSB_RE.finditer(result.stdout or ""):
        try:
            vids.add(int(match.group(1), 16))
        except ValueError:
            continue
    return vids


def _scan_usb() -> set[int]:
    """Scan the USB bus, preferring pyusb, falling back to lsusb."""
    vids = _scan_usb_pyusb()
    if vids is not None:
        return vids
    return _scan_usb_lsusb()


def _pick_desired_vid(detected: set[int]) -> Optional[int]:
    """Choose the preferred VID from detected USB devices."""
    for vid in _VENDOR_PRIORITY:
        if vid in detected:
            return vid
    return None


# ---------------------------------------------------------------------------
# Sub-backend factory (lazy imports keep optional deps truly optional)
# ---------------------------------------------------------------------------

def _build_sub_backend(vid: int) -> Optional[CameraBackend]:
    """Instantiate the sub-backend matching *vid*.

    Returns None when the backend module or its external dependency is
    unavailable (e.g. VmbPy not installed on this target).
    """
    name, _model = _VENDOR_MAP[vid]
    try:
        if name == "vmbpy":
            from .vmbpy_backend import VmbPyCameraBackend
            return VmbPyCameraBackend()
        if name == "novitec":
            from .novitec_backend import NovitecBackend
            return NovitecBackend()
    except ImportError as exc:
        log.warning(
            "Sub-backend %s unavailable (%s) -- skipping", name, exc)
        return None
    except Exception as exc:
        log.warning(
            "Sub-backend %s construction failed: %s", name, exc)
        return None
    return None


# ---------------------------------------------------------------------------
# AutoCameraBackend
# ---------------------------------------------------------------------------

class AutoCameraBackend(CameraBackend):
    """Hot-plug aware wrapper that auto-selects a CameraBackend by USB VID.

    Consumers interact with this class exactly like any other CameraBackend.
    When no camera is attached every feature call raises
    ``CameraDisconnectedError``; once a recognised camera is plugged in the
    scan loop transparently connects the matching sub-backend.
    """

    def __init__(
        self,
        ws_event_callback: Optional[WsEventCallback] = None,
        scan_interval: Optional[float] = None,
        scan_fn: Optional[Callable[[], set[int]]] = None,
        backend_factory: Optional[Callable[[int], Optional[CameraBackend]]] = None,
    ) -> None:
        """
        :param ws_event_callback: Optional async callable invoked with event
            payload dicts on camera_connected / camera_disconnected.
        :param scan_interval: Polling interval in seconds.  Defaults to 2.0
            or the value of OB_CAMERA_SCAN_INTERVAL.
        :param scan_fn: Injection point for tests -- callable returning the
            current set of USB VIDs.  Defaults to real pyusb/lsusb scanner.
        :param backend_factory: Injection point for tests -- callable
            building a sub-backend for a given VID.  Defaults to
            :func:`_build_sub_backend`.
        """
        self._ws_callback = ws_event_callback
        self._scan_fn = scan_fn or _scan_usb
        self._factory = backend_factory or _build_sub_backend

        # Resolve scan interval from arg > env > default.
        if scan_interval is None:
            env_val = os.environ.get("OB_CAMERA_SCAN_INTERVAL")
            if env_val:
                try:
                    scan_interval = float(env_val)
                except ValueError:
                    log.warning(
                        "Invalid OB_CAMERA_SCAN_INTERVAL=%r, using default",
                        env_val,
                    )
                    scan_interval = _DEFAULT_SCAN_INTERVAL
            else:
                scan_interval = _DEFAULT_SCAN_INTERVAL
        self._scan_interval = max(0.1, float(scan_interval))

        self._active: Optional[CameraBackend] = None
        self._active_vid: Optional[int] = None
        self._active_device: Optional[DeviceInfo] = None

        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._scan_task: Optional[asyncio.Task] = None
        self._started = False

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    async def _emit(self, event: dict) -> None:
        if self._ws_callback is None:
            return
        try:
            await self._ws_callback(event)
        except Exception as exc:
            log.debug("ws_event_callback raised: %s", exc)

    @staticmethod
    def _backend_name_for_vid(vid: Optional[int]) -> Optional[str]:
        if vid is None or vid not in _VENDOR_MAP:
            return None
        return _VENDOR_MAP[vid][0]

    # ------------------------------------------------------------------
    # Scan loop -- core of the hot-plug behaviour
    # ------------------------------------------------------------------

    async def _run_scan_once(self) -> None:
        """Perform a single scan / transition step.

        Exposed as a separate coroutine so tests can drive transitions
        deterministically without touching the background task.
        """
        try:
            detected = await asyncio.to_thread(self._scan_fn)
        except Exception as exc:
            log.debug("USB scan raised: %s", exc)
            detected = set()

        desired = _pick_desired_vid(detected)

        if desired == self._active_vid:
            return

        async with self._lock:
            # Re-check inside the lock -- another scan may have transitioned
            # while we were waiting.
            if desired == self._active_vid:
                return

            # Tear down previous sub-backend (if any).
            if self._active is not None:
                prev_vid = self._active_vid
                prev_name = self._backend_name_for_vid(prev_vid)
                try:
                    await self._active.disconnect()
                except Exception as exc:
                    log.warning(
                        "Sub-backend disconnect raised during swap: %s", exc)
                log.info(
                    "AutoCamera: disconnected previous backend vid=0x%x (%s)",
                    prev_vid or 0, prev_name)
                await self._emit({
                    "type":     "camera_disconnected",
                    "vid_hex":  f"0x{prev_vid:x}" if prev_vid is not None else None,
                    "backend":  prev_name,
                })
                self._active = None
                self._active_vid = None
                self._active_device = None

            # Bring up the new sub-backend matching the detected VID.
            if desired is not None:
                backend = self._factory(desired)
                if backend is None:
                    # Factory refused (missing dependency etc.)
                    return
                new_name = self._backend_name_for_vid(desired)
                try:
                    info = await backend.connect()
                except CameraError as exc:
                    log.warning(
                        "Sub-backend %s connect failed: %s", new_name, exc)
                    try:
                        await backend.disconnect()
                    except Exception:
                        pass
                    return
                except Exception as exc:
                    log.warning(
                        "Sub-backend %s connect raised: %s", new_name, exc)
                    try:
                        await backend.disconnect()
                    except Exception:
                        pass
                    return

                # Some sub-backends (NovitecBackend) return a placeholder
                # DeviceInfo when the camera is not yet live.  Only accept
                # the swap when the backend is actually connected.
                reports_connected = True
                try:
                    reports_connected = bool(
                        getattr(backend, "is_connected", True))
                except Exception:
                    reports_connected = True

                if not reports_connected:
                    # Hardware is advertising on the bus but the sub-backend
                    # could not open it.  Bail out; next scan cycle retries.
                    try:
                        await backend.disconnect()
                    except Exception:
                        pass
                    return

                self._active = backend
                self._active_vid = desired
                self._active_device = info
                log.info(
                    "AutoCamera: activated %s for vid=0x%x (model=%s serial=%s)",
                    new_name, desired, info.model, info.serial)
                await self._emit({
                    "type":     "camera_connected",
                    "vid_hex":  f"0x{desired:x}",
                    "backend":  new_name,
                    "model":    info.model,
                    "serial":   info.serial,
                    "firmware": info.firmware,
                    "vendor":   info.vendor,
                })

    async def _scan_loop(self) -> None:
        log.info(
            "AutoCamera scan loop started (interval=%.2fs)",
            self._scan_interval)
        while not self._stop_event.is_set():
            try:
                await self._run_scan_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                # Never kill the loop -- maintain heartbeat even on errors.
                log.warning("AutoCamera scan iteration failed: %s", exc)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._scan_interval)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
        log.info("AutoCamera scan loop exited")

    # ------------------------------------------------------------------
    # CameraBackend -- lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> DeviceInfo:
        """Start the background scan loop and attempt an immediate scan.

        Returns the device info of the currently active sub-backend when a
        camera is present, otherwise a blank DeviceInfo so that FastAPI
        startup still succeeds on an empty bus.
        """
        if not self._started:
            self._stop_event.clear()
            self._scan_task = asyncio.create_task(
                self._scan_loop(), name="auto-camera-scan")
            self._started = True
            log.info("AutoCameraBackend started")

        # Do a synchronous first scan so the caller sees an up-to-date
        # connection state before returning.
        await self._run_scan_once()

        if self._active_device is not None:
            return self._active_device
        return DeviceInfo(model="", serial="", firmware="", vendor="")

    async def disconnect(self) -> None:
        """Stop the scan loop and tear down the current sub-backend."""
        self._stop_event.set()
        task = self._scan_task
        self._scan_task = None
        self._started = False
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        async with self._lock:
            if self._active is not None:
                try:
                    await self._active.disconnect()
                except Exception as exc:
                    log.warning(
                        "Sub-backend disconnect raised during shutdown: %s",
                        exc)
                prev_vid = self._active_vid
                prev_name = self._backend_name_for_vid(prev_vid)
                self._active = None
                self._active_vid = None
                self._active_device = None
                await self._emit({
                    "type":     "camera_disconnected",
                    "vid_hex":  f"0x{prev_vid:x}" if prev_vid is not None else None,
                    "backend":  prev_name,
                })
        log.info("AutoCameraBackend stopped")

    # ------------------------------------------------------------------
    # Delegation helpers
    # ------------------------------------------------------------------

    def _require_active(self) -> CameraBackend:
        backend = self._active
        if backend is None:
            raise CameraDisconnectedError(
                "No camera detected -- waiting for hot-plug")
        return backend

    async def _handle_disconnect_during_call(self) -> None:
        """Mark the current sub-backend as gone after a disconnect error."""
        async with self._lock:
            if self._active is None:
                return
            prev_vid = self._active_vid
            prev_name = self._backend_name_for_vid(prev_vid)
            try:
                await self._active.disconnect()
            except Exception:
                pass
            self._active = None
            self._active_vid = None
            self._active_device = None
            await self._emit({
                "type":    "camera_disconnected",
                "vid_hex": f"0x{prev_vid:x}" if prev_vid is not None else None,
                "backend": prev_name,
            })

    # ------------------------------------------------------------------
    # CameraBackend -- frame API (with disconnect detection)
    # ------------------------------------------------------------------

    async def capture(self) -> CapturedFrame:
        backend = self._require_active()
        try:
            return await backend.capture()
        except CameraDisconnectedError:
            await self._handle_disconnect_during_call()
            raise

    async def stream(self, fps: float = 30.0) -> AsyncIterator[CapturedFrame]:
        backend = self._require_active()
        try:
            async for frame in backend.stream(fps=fps):
                yield frame
        except CameraDisconnectedError:
            await self._handle_disconnect_during_call()
            raise

    # ------------------------------------------------------------------
    # CameraBackend -- introspection
    # ------------------------------------------------------------------

    def capabilities(self) -> dict[Feature, FeatureCapability]:
        backend = self._active
        if backend is None:
            return {}
        try:
            return backend.capabilities()
        except Exception as exc:
            log.debug("Sub-backend capabilities raised: %s", exc)
            return {}

    async def get_status(self) -> CameraStatus:
        backend = self._active
        if backend is None:
            return CameraStatus(
                connected=False,
                streaming=False,
                device=None,
                current_exposure_us=None,
                current_gain_db=None,
                current_temperature_c=None,
                current_fps=None,
                current_pixel_format=None,
                current_roi=None,
                current_trigger_mode=None,
            )
        return await backend.get_status()

    def device_info(self) -> DeviceInfo:
        backend = self._active
        if backend is None:
            raise CameraDisconnectedError("No camera detected")
        return backend.device_info()

    # ------------------------------------------------------------------
    # Feature delegation -- forward to active sub-backend or raise
    # ------------------------------------------------------------------

    async def set_exposure(self, *, auto: bool = False,
                           time_us: Optional[float] = None):
        return await self._require_active().set_exposure(
            auto=auto, time_us=time_us)

    async def get_exposure(self):
        return await self._require_active().get_exposure()

    async def set_gain(self, *, auto: bool = False,
                       value_db: Optional[float] = None):
        return await self._require_active().set_gain(
            auto=auto, value_db=value_db)

    async def get_gain(self):
        return await self._require_active().get_gain()

    async def set_roi(self, *, width: int, height: int,
                      offset_x: int = 0, offset_y: int = 0):
        return await self._require_active().set_roi(
            width=width, height=height,
            offset_x=offset_x, offset_y=offset_y,
        )

    async def get_roi(self):
        return await self._require_active().get_roi()

    async def center_roi(self):
        return await self._require_active().center_roi()

    async def set_pixel_format(self, *, format: str):
        return await self._require_active().set_pixel_format(format=format)

    async def get_pixel_format(self):
        return await self._require_active().get_pixel_format()

    async def set_frame_rate(self, *, enable: bool,
                             value: Optional[float] = None):
        return await self._require_active().set_frame_rate(
            enable=enable, value=value)

    async def get_frame_rate(self):
        return await self._require_active().get_frame_rate()

    async def set_trigger(self, *, mode: str,
                          source: Optional[str] = None):
        return await self._require_active().set_trigger(
            mode=mode, source=source)

    async def get_trigger(self):
        return await self._require_active().get_trigger()

    async def fire_trigger(self) -> None:
        await self._require_active().fire_trigger()

    async def get_temperature(self) -> float:
        return await self._require_active().get_temperature()

    async def load_user_set(self, *, slot: str) -> None:
        await self._require_active().load_user_set(slot=slot)

    async def save_user_set(self, *, slot: str) -> None:
        await self._require_active().save_user_set(slot=slot)

    async def set_default_user_set(self, *, slot: str) -> None:
        await self._require_active().set_default_user_set(slot=slot)

    async def get_user_set_info(self):
        return await self._require_active().get_user_set_info()

    # ------------------------------------------------------------------
    # Compatibility -- CameraService reads this for hot-plug status
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        backend = self._active
        if backend is None:
            return False
        try:
            inner = getattr(backend, "is_connected", True)
            return bool(inner)
        except Exception:
            return True

    @property
    def active_backend_name(self) -> Optional[str]:
        return self._backend_name_for_vid(self._active_vid)

    @property
    def active_vid(self) -> Optional[int]:
        return self._active_vid
