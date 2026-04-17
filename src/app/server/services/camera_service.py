"""
camera_service.py — Camera abstraction for Allied Vision Alvium 1800 U-158m.

Pipeline priority (highest to lowest):
  1. VmbPy (Vimba X Python SDK)         (production: USB3 Vision)
  2. Vimba X SDK via GStreamer plugin   (avtsrc, if OpenCV+GStreamer available)
  3. GStreamer v4l2src                  (fallback for USB UVC mode)
  4. OpenCV VideoCapture(0)             (development fallback)

All capture methods return raw JPEG bytes for transport efficiency.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)

# VmbPy — Allied Vision Vimba X Python SDK
try:
    import vmbpy
    import numpy as np
    from PIL import Image
    _VMBPY_AVAILABLE = True
except ImportError:
    _VMBPY_AVAILABLE = False
    log.info("VmbPy not available — will try OpenCV/GStreamer backends")

# Optional OpenCV fallback
try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False
    log.warning("OpenCV not available — camera will return synthetic frames")

# Vimba X transport layer path (set by env or /opt/vimba-x)
_GENICAM_PATH = os.environ.get("GENICAM_GENTL64_PATH", "/opt/VimbaX_2026-1/cti")
if _VMBPY_AVAILABLE and _GENICAM_PATH:
    os.environ.setdefault("GENICAM_GENTL64_PATH", _GENICAM_PATH)


class CameraBackend(str, Enum):
    VIMBA_X    = "vimba_x"
    GSTREAMER  = "gstreamer"
    UVC        = "uvc_fallback"
    MOCK       = "mock"


class CameraService:
    """
    Thread-safe async camera service.

    Instantiate once at startup and pass to routers via FastAPI dependency.
    """

    def __init__(self, mock: bool = False) -> None:
        self._mock = mock
        self._cap: Optional[object] = None      # cv2.VideoCapture or None
        self._vmb: Optional[object] = None      # vmbpy.VmbSystem context
        self._vmb_cam: Optional[object] = None  # vmbpy.Camera context
        self._backend = CameraBackend.MOCK
        self._connected = False
        self._width = 0
        self._height = 0
        self._exposure_us: float = 5000.0
        self._gain_db: float = 0.0
        self._pixel_format: str = "mono8"
        self._fps: float = 0.0
        self._frame_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._last_frame_ts: float = 0.0
        self._power_state: str = "off"   # "on" | "standby" | "off"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """
        Attempt to open the camera.  Returns True on success.
        Tries VmbPy first, then GStreamer/UVC fallbacks.
        Idempotent — a no-op if already connected.
        """
        async with self._state_lock:
            if self._connected:
                return True

            if self._mock:
                log.warning("CameraService: running in MOCK mode")
                self._backend = CameraBackend.MOCK
                self._connected = True
                self._width = 1456
                self._height = 1088
                self._power_state = "on"
                return True

            ok = False
            if _VMBPY_AVAILABLE and await self._try_vmbpy():
                ok = True
            elif not _CV2_AVAILABLE:
                log.error("No camera backend available (VmbPy and OpenCV both missing)")
                ok = False
            elif await self._try_vimba_x_gstreamer():
                ok = True
            elif await self._try_gstreamer_v4l2():
                ok = True
            elif await self._try_uvc():
                ok = True

            if ok:
                self._power_state = "on"
            else:
                log.error("CameraService: all backends failed — no camera available")
            return ok

    async def disconnect(self) -> None:
        """
        Gracefully shut the camera down via the Vimba X SDK native sequence.
        Releases the frame handle and exits both the camera and VmbSystem
        contexts. Safe to call multiple times.
        """
        async with self._state_lock:
            # Drain any in-flight capture before tearing down handles.
            async with self._frame_lock:
                if self._cap is not None:
                    loop = asyncio.get_running_loop()
                    cap = self._cap
                    await loop.run_in_executor(None, cap.release)
                    self._cap = None
                if self._vmb_cam is not None:
                    try:
                        self._vmb_cam.__exit__(None, None, None)
                    except Exception as exc:
                        log.debug("VmbPy camera __exit__ failed: %s", exc)
                    self._vmb_cam = None
                if self._vmb is not None:
                    try:
                        self._vmb.__exit__(None, None, None)
                    except Exception as exc:
                        log.debug("VmbPy system __exit__ failed: %s", exc)
                    self._vmb = None
                self._connected = False
                self._power_state = "off"
                self._backend = CameraBackend.MOCK if self._mock else self._backend

    async def __aenter__(self) -> "CameraService":
        await self.connect()
        return self

    async def __aexit__(self, *_) -> None:
        await self.disconnect()

    # ------------------------------------------------------------------
    # Backend probing
    # ------------------------------------------------------------------

    async def _try_vmbpy(self) -> bool:
        """Try native VmbPy (Vimba X Python SDK) — USB3 Vision."""
        loop = asyncio.get_running_loop()

        def _open():
            try:
                vmb = vmbpy.VmbSystem.get_instance()
                vmb.__enter__()
                cams = vmb.get_all_cameras()
                if not cams:
                    vmb.__exit__(None, None, None)
                    return None, None
                # Only accept real cameras — reject simulators
                real_cams = [c for c in cams if 'Simulator' not in c.get_model()]
                if not real_cams:
                    log.info("VmbPy: %d camera(s) found but all are simulators — ignoring", len(cams))
                    vmb.__exit__(None, None, None)
                    return None, None
                cam = real_cams[0]
                log.info("VmbPy: selected camera %s (%s), %d total (%d real)",
                         cam.get_name(), cam.get_model(), len(cams), len(real_cams))
                cam.__enter__()
                # Configure pixel format for mono camera
                try:
                    cam.set_pixel_format(vmbpy.PixelFormat.Mono8)
                except Exception:
                    pass
                return vmb, cam
            except Exception as exc:
                log.debug("VmbPy open failed: %s", exc)
                return None, None

        vmb, cam = await loop.run_in_executor(None, _open)
        if cam is None:
            return False

        self._vmb = vmb
        self._vmb_cam = cam
        self._backend = CameraBackend.VIMBA_X
        self._connected = True
        self._width = 1456   # Alvium 1800 U-158m native resolution
        self._height = 1088
        self._fps = 30.0     # Alvium 1800 U-158m supports up to 133 fps
        log.info("CameraService: opened via VmbPy (Vimba X USB3 Vision)")
        return True

    async def _try_vimba_x_gstreamer(self) -> bool:
        """Try the Allied Vision avtsrc GStreamer element."""
        pipeline = (
            "avtsrc ! "
            "videoconvert ! "
            "video/x-raw,format=GRAY8 ! "
            "appsink drop=true max-buffers=1"
        )
        return await self._try_gstreamer_pipeline(pipeline, CameraBackend.VIMBA_X)

    async def _try_gstreamer_v4l2(self) -> bool:
        """Try a generic v4l2src GStreamer pipeline."""
        pipeline = (
            "v4l2src device=/dev/video0 ! "
            "videoconvert ! "
            "appsink drop=true max-buffers=1"
        )
        return await self._try_gstreamer_pipeline(pipeline, CameraBackend.GSTREAMER)

    async def _try_gstreamer_pipeline(
        self, pipeline: str, backend: CameraBackend
    ) -> bool:
        loop = asyncio.get_running_loop()

        def _open():
            cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
            if not cap.isOpened():
                return None
            # Read a test frame to verify a real sensor is behind the device
            ok, _ = cap.read()
            if not ok:
                cap.release()
                return None
            return cap

        cap = await loop.run_in_executor(None, _open)
        if cap is None:
            log.debug("Camera backend %s not available", backend.value)
            return False

        self._cap = cap
        self._backend = backend
        self._connected = True
        self._width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._fps = cap.get(cv2.CAP_PROP_FPS)
        log.info("CameraService: opened via %s (%dx%d @ %.1f fps)",
                 backend.value, self._width, self._height, self._fps)
        return True

    async def _try_uvc(self) -> bool:
        """Try plain UVC VideoCapture."""
        if not _CV2_AVAILABLE:
            return False

        loop = asyncio.get_running_loop()

        def _open():
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                return None
            # Read a test frame — ISI/CSI nodes without a sensor open
            # successfully but fail to deliver frames.
            ok, _ = cap.read()
            if not ok:
                cap.release()
                return None
            return cap

        cap = await loop.run_in_executor(None, _open)
        if cap is None:
            return False

        self._cap = cap
        self._backend = CameraBackend.UVC
        self._connected = True
        self._width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._fps = cap.get(cv2.CAP_PROP_FPS)
        log.info("CameraService: opened via UVC fallback (%dx%d)", self._width, self._height)
        return True

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        device_id = None
        if self._connected and self._vmb_cam is not None:
            try:
                device_id = self._vmb_cam.get_model()
            except Exception:
                device_id = "Alvium_1800_U-158m"
        return {
            "connected":    self._connected,
            "device_id":    device_id,
            "width":        self._width or None,
            "height":       self._height or None,
            "exposure_us":  self._exposure_us,
            "gain_db":      self._gain_db,
            "format":       self._pixel_format,
            "backend":      self._backend.value,
            "fps":          self._fps or None,
            "power_state":  self._power_state,
        }

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    async def capture_jpeg(self, quality: int = 85) -> bytes:
        """
        Capture a single frame and return it as a JPEG byte string.
        Raises RuntimeError if camera is not connected.
        """
        async with self._frame_lock:
            if self._power_state != "on":
                raise RuntimeError("Camera is offline (power_state != 'on')")

            if self._mock:
                return self._synthetic_frame(quality)

            if not self._connected:
                raise RuntimeError("Camera not connected")

            loop = asyncio.get_running_loop()

            # VmbPy path
            if self._backend == CameraBackend.VIMBA_X and self._vmb_cam is not None:
                frame_bytes = await loop.run_in_executor(None, self._read_frame_vmbpy, quality)
                if frame_bytes is not None:
                    self._last_frame_ts = time.monotonic()
                    return frame_bytes
                raise RuntimeError("VmbPy frame capture failed")

            # OpenCV/GStreamer path
            if self._cap is None:
                raise RuntimeError("Camera not connected")
            frame = await loop.run_in_executor(None, self._read_frame_cv2)
            if frame is None:
                raise RuntimeError("Failed to capture frame from camera")

            self._last_frame_ts = time.monotonic()
            return self._encode_jpeg_cv2(frame, quality)

    def _read_frame_vmbpy(self, quality: int) -> Optional[bytes]:
        """Blocking VmbPy frame capture — called from thread executor."""
        try:
            frame = self._vmb_cam.get_frame(timeout_ms=2000)
            frame.convert_pixel_format(vmbpy.PixelFormat.Mono8)
            img_array = frame.as_numpy_ndarray()
            # Encode via Pillow (no OpenCV dependency)
            img = Image.fromarray(img_array.squeeze(), mode="L")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            return buf.getvalue()
        except Exception as exc:
            log.warning("VmbPy capture error: %s", exc)
            return None

    def _read_frame_cv2(self):
        """Blocking OpenCV frame read — called from thread executor."""
        ret, frame = self._cap.read()
        return frame if ret else None

    @staticmethod
    def _encode_jpeg_cv2(frame, quality: int) -> bytes:
        """Encode a numpy frame to JPEG bytes via OpenCV."""
        ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ret:
            raise RuntimeError("JPEG encoding failed")
        return bytes(buf)

    def _synthetic_frame(self, quality: int) -> bytes:
        """
        Generate a synthetic grayscale frame for mock/dev mode.
        Returns a minimal valid JPEG byte sequence if OpenCV is not available.
        """
        if _CV2_AVAILABLE:
            # Simple gradient for visual feedback
            import numpy as np
            w, h = 640, 480
            t = time.monotonic()
            frame = np.zeros((h, w), dtype=np.uint8)
            for y in range(h):
                val = int(128 + 127 * ((y / h + t * 0.1) % 1.0))
                frame[y, :] = val
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            return bytes(buf)

        # Minimal 1x1 white JPEG (hardcoded for zero-dependency fallback)
        return (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n"
            b"\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d"
            b"\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1edA\x14\x14"
            b"\x1d-=#\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4"
            b"\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5"
            b"\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01"
            b"\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07\"q\x142\x81\x91\xa1\x08"
            b"#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%&'()*456789:"
            b"CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92"
            b"\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa"
            b"\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9"
            b"\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7"
            b"\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x08"
            b"\x01\x01\x00\x00?\x00\xfb\xd4P\x00\x00\x00\x1f\xff\xd9"
        )

    # ------------------------------------------------------------------
    # MJPEG streaming generator
    # ------------------------------------------------------------------

    async def mjpeg_generator(self, fps: float = 15.0):
        """
        Async generator yielding MJPEG multipart frames.

        Usage::

            async for chunk in camera_service.mjpeg_generator():
                yield chunk
        """
        interval = 1.0 / fps
        boundary = b"--frame\r\n"
        while True:
            t0 = time.monotonic()
            try:
                jpeg = await self.capture_jpeg(quality=75)
            except RuntimeError as e:
                log.warning("MJPEG: capture failed: %s", e)
                await asyncio.sleep(interval)
                continue

            yield (
                boundary
                + b"Content-Type: image/jpeg\r\n"
                + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                + jpeg
                + b"\r\n"
            )

            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0.0, interval - elapsed))

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    async def apply_settings(
        self,
        exposure_us: Optional[float] = None,
        gain_db: Optional[float] = None,
        pixel_format: Optional[str] = None,
    ) -> None:
        """Apply camera settings."""
        loop = asyncio.get_running_loop()

        if exposure_us is not None:
            self._exposure_us = exposure_us
            if self._vmb_cam is not None:
                def _set_exp():
                    try:
                        self._vmb_cam.ExposureTime.set(exposure_us)
                    except Exception as e:
                        log.debug("Exposure set failed: %s", e)
                await loop.run_in_executor(None, _set_exp)
            elif self._cap is not None and _CV2_AVAILABLE:
                self._cap.set(cv2.CAP_PROP_EXPOSURE, exposure_us / 1_000_000)

        if gain_db is not None:
            self._gain_db = gain_db
            if self._vmb_cam is not None:
                def _set_gain():
                    try:
                        self._vmb_cam.Gain.set(gain_db)
                    except Exception as e:
                        log.debug("Gain set failed: %s", e)
                await loop.run_in_executor(None, _set_gain)
            elif self._cap is not None and _CV2_AVAILABLE:
                self._cap.set(cv2.CAP_PROP_GAIN, gain_db)

        if pixel_format is not None:
            self._pixel_format = pixel_format

        log.debug(
            "Camera settings applied: exposure=%.1f us, gain=%.1f dB, format=%s",
            self._exposure_us, self._gain_db, self._pixel_format,
        )
