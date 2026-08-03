# src/app/server/services/camera_backends/v4l2_backend.py
"""
v4l2_backend.py — Camera backend for V4L2/MIPI CSI-2 devices.

Targets the Allied Vision Alvium 1800 C-158m (1456×1088 mono8 global
shutter) attached to the i.MX8MP ISI pipeline, where it appears as a
standard V4L2 capture node (bus_info "platform:…isi…"). All kernel
interaction goes through the pure-ctypes ABI layer (`_v4l2`) and an
injectable device-IO seam (`V4l2DeviceIO`), so the backend is fully
unit-testable on machines without any /dev/video* node.

Streaming architecture (mirrors vmbpy_backend's thread-affinity model):
a dedicated OS thread owns the MMAP streaming machinery — REQBUFS(4) /
QUERYBUF / mmap / QBUF / STREAMON, then a DQBUF loop. Decoded frames
are handed to asyncio subscriber queues via loop.call_soon_threadsafe.
STREAMOFF + munmap + REQBUFS(0) run in the thread's finally block.

Feature support (V4L2 standard controls only):
  exposure     — V4L2_CID_EXPOSURE_ABSOLUTE (driver unit = 100 µs,
                 converted to/from the ABC's µs); falls back to
                 V4L2_CID_EXPOSURE raw driver units when absent.
  gain         — V4L2_CID_ANALOGUE_GAIN (fallback V4L2_CID_GAIN).
  pixel_format — VIDIOC_ENUM_FMT / S_FMT via the _v4l2 fourcc map.
  frame_rate   — VIDIOC_S_PARM / G_PARM timeperframe.
ROI, trigger, temperature and user_set need the AVT vendor-extension
CIDs (avt3 driver) and raise FeatureNotSupportedError for now.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import ctypes
import errno
import logging
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Optional

import numpy as np

from . import (
    CameraBackend, CameraDisconnectedError, CameraError, CameraStatus,
    CameraTimeoutError, CapturedFrame, DeviceInfo, ExposureInfo, Feature,
    FeatureCapability, FeatureNotSupportedError, FeatureOutOfRangeError,
    FrameMeta, FrameRateInfo, GainInfo, NumericRange, PixelFormatInfo,
)
from . import _v4l2 as v4l2

log = logging.getLogger(__name__)

# Preferred sensor-native mode for the Alvium 1800 C-158m.
PREFERRED_WIDTH = 1456
PREFERRED_HEIGHT = 1088

# Number of MMAP buffers requested from the driver.
_NUM_BUFFERS = 4

# Nominal frame-rate range. The true per-mode range requires
# VIDIOC_ENUM_FRAMEINTERVALS which is deferred until AVT driver bring-up.
_FPS_RANGE = NumericRange(min=1.0, max=120.0, step=0.01)

# V4L2_CID_EXPOSURE_ABSOLUTE is defined in units of 100 µs.
_EXPOSURE_ABSOLUTE_UNIT_US = 100.0


# ---------------------------------------------------------------------------
# Device IO seam
# ---------------------------------------------------------------------------

class V4l2DeviceIO:
    """Real device IO: os.open / fcntl.ioctl / mmap / select.

    Injectable seam — tests substitute a fake implementing the same
    six methods. ioctl argument objects are ctypes structures mutated
    in place (fcntl.ioctl writes results back through the buffer
    protocol).
    """

    def open(self, path: str) -> int:
        import os
        return os.open(path, os.O_RDWR | os.O_NONBLOCK)

    def close(self, fd: int) -> None:
        import os
        os.close(fd)

    def ioctl(self, fd: int, request: int, arg) -> int:
        import fcntl
        return fcntl.ioctl(fd, request, arg)

    def mmap(self, fd: int, length: int, offset: int):
        import mmap as _mmap
        return _mmap.mmap(
            fd, length,
            flags=_mmap.MAP_SHARED,
            prot=_mmap.PROT_READ | _mmap.PROT_WRITE,
            offset=offset,
        )

    def munmap(self, buf) -> None:
        buf.close()

    def poll(self, fd: int, timeout_s: float) -> bool:
        import select
        readable, _, _ = select.select([fd], [], [], timeout_s)
        return bool(readable)


# ---------------------------------------------------------------------------
# Cached control descriptor
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _CtrlInfo:
    """QUERYCTRL result cached during connect()."""
    cid: int
    minimum: int
    maximum: int
    step: int
    default: int


class V4l2CameraBackend(CameraBackend):
    """V4L2/MIPI camera backend (Alvium 1800 C on i.MX8MP ISI)."""

    def __init__(self, device_path: str = "/dev/video0", *,
                 io=None) -> None:
        self._path = device_path
        self._io = io if io is not None else V4l2DeviceIO()

        self._fd: Optional[int] = None
        self._connected = False
        self._device: Optional[DeviceInfo] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Format state (refreshed on connect / set_pixel_format)
        self._fourccs: list[int] = []
        self._fmt_width = PREFERRED_WIDTH
        self._fmt_height = PREFERRED_HEIGHT
        self._fmt_pixelformat = v4l2.V4L2_PIX_FMT_GREY
        self._fmt_bytesperline = PREFERRED_WIDTH
        self._fmt_sizeimage = PREFERRED_WIDTH * PREFERRED_HEIGHT

        # Control cache (QUERYCTRL probes done during connect)
        self._exposure_ctrl: Optional[_CtrlInfo] = None
        self._exposure_scale = _EXPOSURE_ABSOLUTE_UNIT_US
        self._gain_ctrl: Optional[_CtrlInfo] = None
        self._has_timeperframe = False

        # Telemetry cache
        self._exposure_us: Optional[float] = None
        self._gain_db: Optional[float] = None
        self._fps_value: Optional[float] = None
        self._fps_enable = False
        self._fps_actual = 0.0

        # Streaming thread state
        self._stream_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stream_started = threading.Event()
        self._stream_error: Optional[BaseException] = None
        self._streaming = False
        self._broadcast_subs: list[asyncio.Queue] = []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """CameraService gates the MJPEG stream route on this."""
        return self._connected

    def _require_connected(self) -> None:
        if not self._connected or self._fd is None:
            raise CameraDisconnectedError("Camera not connected")

    def _pixel_format_name(self) -> str:
        return v4l2.PIXEL_FORMAT_MAP.get(
            self._fmt_pixelformat,
            v4l2.fourcc_to_str(self._fmt_pixelformat),
        )

    def _available_format_names(self) -> list[str]:
        return [
            v4l2.PIXEL_FORMAT_MAP.get(fcc, v4l2.fourcc_to_str(fcc))
            for fcc in self._fourccs
        ]

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> DeviceInfo:
        if self._connected:
            return self._device
        self._loop = asyncio.get_running_loop()

        try:
            fd = self._io.open(self._path)
        except OSError as exc:
            raise CameraDisconnectedError(
                f"Cannot open V4L2 device {self._path}: {exc}") from exc

        try:
            cap = v4l2.v4l2_capability()
            self._io.ioctl(fd, v4l2.VIDIOC_QUERYCAP, cap)
            caps_flags = cap.device_caps or cap.capabilities
            if not (caps_flags & v4l2.V4L2_CAP_VIDEO_CAPTURE):
                raise CameraError(
                    f"{self._path} is not a video capture device")
            if not (caps_flags & v4l2.V4L2_CAP_STREAMING):
                raise CameraError(
                    f"{self._path} does not support streaming IO")

            self._enumerate_formats(fd)
            self._negotiate_format(fd)
            self._probe_controls(fd)
            self._probe_streamparm(fd)
            self._seed_control_cache(fd)
        except CameraError:
            self._safe_close(fd)
            raise
        except OSError as exc:
            self._safe_close(fd)
            raise CameraError(
                f"V4L2 setup failed on {self._path}: {exc}") from exc

        self._fd = fd
        self._connected = True
        self._device = DeviceInfo(
            model=cap.card.decode("ascii", "replace"),
            serial=cap.bus_info.decode("ascii", "replace"),
            firmware=cap.driver.decode("ascii", "replace"),
            vendor="AlliedVision/V4L2",
        )
        log.info("V4L2 connected: %s (%s, %dx%d %s)",
                 self._device.model, self._device.serial,
                 self._fmt_width, self._fmt_height,
                 self._pixel_format_name())
        return self._device

    def _safe_close(self, fd: int) -> None:
        try:
            self._io.close(fd)
        except OSError:
            pass

    def _enumerate_formats(self, fd: int) -> None:
        """Collect all fourccs the capture node offers."""
        self._fourccs = []
        index = 0
        while True:
            desc = v4l2.v4l2_fmtdesc()
            desc.index = index
            desc.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
            try:
                self._io.ioctl(fd, v4l2.VIDIOC_ENUM_FMT, desc)
            except OSError:
                break  # EINVAL == past the last format
            self._fourccs.append(desc.pixelformat)
            index += 1

    def _negotiate_format(self, fd: int) -> None:
        """Prefer GREY at sensor-native 1456×1088; else keep current."""
        if v4l2.V4L2_PIX_FMT_GREY in self._fourccs:
            fmt = v4l2.v4l2_format()
            fmt.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
            fmt.fmt.pix.width = PREFERRED_WIDTH
            fmt.fmt.pix.height = PREFERRED_HEIGHT
            fmt.fmt.pix.pixelformat = v4l2.V4L2_PIX_FMT_GREY
            fmt.fmt.pix.field = v4l2.V4L2_FIELD_NONE
            try:
                self._io.ioctl(fd, v4l2.VIDIOC_S_FMT, fmt)
            except OSError as exc:
                log.warning("S_FMT GREY %dx%d refused (%s) — "
                            "keeping device format",
                            PREFERRED_WIDTH, PREFERRED_HEIGHT, exc)
        self._read_back_format(fd)

    def _read_back_format(self, fd: int) -> None:
        """G_FMT — the driver may have adjusted our request."""
        fmt = v4l2.v4l2_format()
        fmt.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        self._io.ioctl(fd, v4l2.VIDIOC_G_FMT, fmt)
        pix = fmt.fmt.pix
        self._fmt_width = int(pix.width)
        self._fmt_height = int(pix.height)
        self._fmt_pixelformat = int(pix.pixelformat)
        self._fmt_bytesperline = int(pix.bytesperline)
        self._fmt_sizeimage = int(pix.sizeimage)

    def _query_ctrl(self, fd: int, cid: int) -> Optional[_CtrlInfo]:
        qc = v4l2.v4l2_queryctrl()
        qc.id = cid
        try:
            self._io.ioctl(fd, v4l2.VIDIOC_QUERYCTRL, qc)
        except OSError:
            return None
        if qc.flags & v4l2.V4L2_CTRL_FLAG_DISABLED:
            return None
        return _CtrlInfo(cid=cid, minimum=int(qc.minimum),
                         maximum=int(qc.maximum),
                         step=max(int(qc.step), 1),
                         default=int(qc.default_value))

    def _probe_controls(self, fd: int) -> None:
        """QUERYCTRL probes — results cached for capabilities()."""
        # Exposure: prefer EXPOSURE_ABSOLUTE (100 µs units). Fall back to
        # the raw V4L2_CID_EXPOSURE whose unit is driver-defined; we then
        # pass values through 1:1 and document them as "µs" best-effort.
        ctrl = self._query_ctrl(fd, v4l2.V4L2_CID_EXPOSURE_ABSOLUTE)
        if ctrl is not None:
            self._exposure_ctrl = ctrl
            self._exposure_scale = _EXPOSURE_ABSOLUTE_UNIT_US
        else:
            ctrl = self._query_ctrl(fd, v4l2.V4L2_CID_EXPOSURE)
            if ctrl is not None:
                log.warning(
                    "V4L2_CID_EXPOSURE_ABSOLUTE absent — using raw "
                    "V4L2_CID_EXPOSURE (driver-defined units, reported "
                    "as-is in the µs fields)")
                self._exposure_ctrl = ctrl
                self._exposure_scale = 1.0

        # Gain: prefer ANALOGUE_GAIN, fall back to legacy GAIN.
        # NOTE: raw driver units are passed through as "dB" — the actual
        # per-sensor unit→dB mapping (e.g. 0.1 dB/step on Alvium) needs
        # the AVT datasheet and lands with the vendor-extension work.
        self._gain_ctrl = (
            self._query_ctrl(fd, v4l2.V4L2_CID_ANALOGUE_GAIN)
            or self._query_ctrl(fd, v4l2.V4L2_CID_GAIN)
        )

    def _probe_streamparm(self, fd: int) -> None:
        sp = v4l2.v4l2_streamparm()
        sp.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        try:
            self._io.ioctl(fd, v4l2.VIDIOC_G_PARM, sp)
        except OSError:
            self._has_timeperframe = False
            return
        self._has_timeperframe = bool(
            sp.parm.capture.capability & v4l2.V4L2_CAP_TIMEPERFRAME)
        tpf = sp.parm.capture.timeperframe
        if self._has_timeperframe and tpf.numerator:
            self._fps_value = round(tpf.denominator / tpf.numerator, 3)

    def _seed_control_cache(self, fd: int) -> None:
        """Read current exposure/gain so FrameMeta is populated."""
        if self._exposure_ctrl is not None:
            try:
                raw = self._g_ctrl(fd, self._exposure_ctrl.cid)
                self._exposure_us = raw * self._exposure_scale
            except CameraError:
                self._exposure_us = None
        if self._gain_ctrl is not None:
            try:
                self._gain_db = float(self._g_ctrl(fd, self._gain_ctrl.cid))
            except CameraError:
                self._gain_db = None

    async def disconnect(self) -> None:
        """Idempotent teardown: stop stream thread, close the node."""
        self._connected = False
        await self._stop_stream()
        fd = self._fd
        self._fd = None
        if fd is not None:
            self._safe_close(fd)
            log.info("V4L2 disconnected (%s)", self._path)
        self._close_subscribers()

    def _close_subscribers(self) -> None:
        """Push a stream-end sentinel to any lingering subscribers."""
        for q in list(self._broadcast_subs):
            try:
                q.put_nowait(None)
            except Exception:
                pass
        self._broadcast_subs.clear()

    # ------------------------------------------------------------------
    # Low-level control access
    # ------------------------------------------------------------------

    def _g_ctrl(self, fd: int, cid: int) -> int:
        ctrl = v4l2.v4l2_control()
        ctrl.id = cid
        try:
            self._io.ioctl(fd, v4l2.VIDIOC_G_CTRL, ctrl)
        except OSError as exc:
            raise CameraError(
                f"G_CTRL 0x{cid:08x} failed: {exc}") from exc
        return int(ctrl.value)

    def _s_ctrl(self, fd: int, cid: int, value: int) -> None:
        ctrl = v4l2.v4l2_control()
        ctrl.id = cid
        ctrl.value = value
        try:
            self._io.ioctl(fd, v4l2.VIDIOC_S_CTRL, ctrl)
        except OSError as exc:
            raise CameraError(
                f"S_CTRL 0x{cid:08x}={value} failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Streaming thread
    # ------------------------------------------------------------------

    async def _ensure_streaming(self, target_fps: float) -> None:
        """Start the capture thread if it is not already running."""
        if self._stream_thread is not None and self._stream_thread.is_alive():
            return
        self._stream_error = None
        self._stop_event = threading.Event()
        self._stream_started = threading.Event()
        self._stream_thread = threading.Thread(
            target=self._stream_main, args=(target_fps,),
            daemon=True, name="v4l2-stream",
        )
        self._stream_thread.start()
        ok = await asyncio.to_thread(self._stream_started.wait, 5.0)
        if not ok:
            self._stop_event.set()
            raise CameraTimeoutError("V4L2 stream thread did not start")
        if self._stream_error is not None:
            err = self._stream_error
            self._stream_error = None
            await self._stop_stream()
            if isinstance(err, CameraError):
                raise err
            raise CameraError(f"V4L2 streaming setup failed: {err}") from err

    async def _stop_stream(self) -> None:
        thread = self._stream_thread
        if thread is None:
            return
        self._stop_event.set()
        if thread.is_alive():
            await asyncio.to_thread(thread.join, 5.0)
        self._stream_thread = None

    def _stream_main(self, target_fps: float) -> None:
        """Capture-thread body: owns the full MMAP streaming lifecycle."""
        io = self._io
        fd = self._fd
        mmaps: list = []
        stream_on = False
        try:
            # Best-effort S_PARM before STREAMON. If the driver ignores
            # it, the fps argument is still honored by the pacing/drop
            # logic in stream().
            if target_fps > 0 and self._has_timeperframe:
                try:
                    self._set_timeperframe(fd, target_fps)
                except CameraError as exc:
                    log.debug("S_PARM %.2f fps refused: %s", target_fps, exc)

            req = v4l2.v4l2_requestbuffers()
            req.count = _NUM_BUFFERS
            req.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
            req.memory = v4l2.V4L2_MEMORY_MMAP
            io.ioctl(fd, v4l2.VIDIOC_REQBUFS, req)
            count = int(req.count)
            if count < 1:
                raise CameraError("V4L2 driver granted no MMAP buffers")

            for i in range(count):
                buf = v4l2.v4l2_buffer()
                buf.index = i
                buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
                buf.memory = v4l2.V4L2_MEMORY_MMAP
                io.ioctl(fd, v4l2.VIDIOC_QUERYBUF, buf)
                mm = io.mmap(fd, int(buf.length), int(buf.m.offset))
                mmaps.append((mm, int(buf.length)))

            for i in range(count):
                buf = v4l2.v4l2_buffer()
                buf.index = i
                buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
                buf.memory = v4l2.V4L2_MEMORY_MMAP
                io.ioctl(fd, v4l2.VIDIOC_QBUF, buf)

            buf_type = ctypes.c_int(v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE)
            io.ioctl(fd, v4l2.VIDIOC_STREAMON, buf_type)
            stream_on = True
            self._streaming = True

            width = self._fmt_width
            height = self._fmt_height
            bytesperline = self._fmt_bytesperline
            pixelformat = self._fmt_pixelformat

            frame_count = 0
            t0 = time.monotonic()
            self._stream_started.set()

            while not self._stop_event.is_set():
                if not io.poll(fd, 0.5):
                    continue
                buf = v4l2.v4l2_buffer()
                buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
                buf.memory = v4l2.V4L2_MEMORY_MMAP
                try:
                    io.ioctl(fd, v4l2.VIDIOC_DQBUF, buf)
                except OSError as exc:
                    if exc.errno in (errno.EAGAIN, errno.EINTR):
                        continue
                    raise
                mm, length = mmaps[buf.index]
                nbytes = int(buf.bytesused) or length
                arr = self._decode_frame(
                    mm, width, height, bytesperline, pixelformat, nbytes)
                ts_us = (int(buf.timestamp.tv_sec) * 1_000_000
                         + int(buf.timestamp.tv_usec))
                frame_count += 1
                elapsed = time.monotonic() - t0
                self._fps_actual = round(frame_count / max(elapsed, 1e-3), 2)
                self._dispatch_to_subs((arr, ts_us, width, height))
                io.ioctl(fd, v4l2.VIDIOC_QBUF, buf)
        except BaseException as exc:  # surfaced via _stream_error
            self._stream_error = exc
            log.warning("V4L2 stream thread error: %s", exc)
        finally:
            self._streaming = False
            if stream_on:
                try:
                    io.ioctl(fd, v4l2.VIDIOC_STREAMOFF,
                             ctypes.c_int(v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE))
                except OSError:
                    pass
            for mm, _length in mmaps:
                try:
                    io.munmap(mm)
                except Exception:
                    pass
            if mmaps:
                try:
                    req = v4l2.v4l2_requestbuffers()
                    req.count = 0
                    req.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
                    req.memory = v4l2.V4L2_MEMORY_MMAP
                    io.ioctl(fd, v4l2.VIDIOC_REQBUFS, req)
                except OSError:
                    pass
            self._stream_started.set()
            loop = self._loop
            if loop is not None:
                def _notify_end() -> None:
                    for q in list(self._broadcast_subs):
                        try:
                            q.put_nowait(None)
                        except Exception:
                            pass
                try:
                    loop.call_soon_threadsafe(_notify_end)
                except RuntimeError:
                    pass

    @staticmethod
    def _decode_frame(mm, width: int, height: int, bytesperline: int,
                      pixelformat: int, nbytes: int) -> np.ndarray:
        """Copy one MMAP buffer out into a numpy array.

        GREY  → (h, w) uint8 (line padding from the ISI stripped).
        Y10   → (h, w) uint16 little-endian.
        other → 1-D uint8 of the raw payload (YUYV/MJPEG decode is left
                to the consumer).
        """
        if pixelformat == v4l2.V4L2_PIX_FMT_GREY:
            stride = bytesperline if bytesperline >= width else width
            data = np.frombuffer(mm, dtype=np.uint8, count=stride * height)
            return data.reshape(height, stride)[:, :width].copy()
        if pixelformat == v4l2.V4L2_PIX_FMT_Y10:
            row_bytes = bytesperline if bytesperline >= 2 * width else 2 * width
            data = np.frombuffer(
                mm, dtype=np.dtype("<u2"),
                count=(row_bytes // 2) * height)
            return data.reshape(height, row_bytes // 2)[:, :width].copy()
        return np.frombuffer(mm, dtype=np.uint8, count=nbytes).copy()

    def _dispatch_to_subs(self, payload) -> None:
        """Enqueue a frame payload onto every subscriber's asyncio.Queue."""
        loop = self._loop
        if loop is None:
            return

        def _dispatch() -> None:
            dead = []
            for q in list(self._broadcast_subs):
                if q.full():
                    try:
                        q.get_nowait()  # drop oldest — keep stream live
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

    def _build_frame(self, item) -> CapturedFrame:
        arr, ts_us, width, height = item
        meta = FrameMeta(
            timestamp_us=ts_us,
            exposure_us=self._exposure_us,
            gain_db=self._gain_db,
            temperature_c=None,   # needs AVT extension CID
            fps_actual=self._fps_actual,
            width=width,
            height=height,
        )
        return CapturedFrame(
            array=arr,
            pixel_format=self._pixel_format_name(),
            meta=meta,
        )

    # ------------------------------------------------------------------
    # Frame API
    # ------------------------------------------------------------------

    async def capture(self) -> CapturedFrame:
        """Grab one frame via the streaming machinery.

        Starts the capture thread on first use and leaves it running so
        subsequent captures are warm (same model as the VmbPy backend).
        """
        self._require_connected()
        await self._ensure_streaming(0.0)   # 0 → keep driver's frame rate
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        self._broadcast_subs.append(queue)
        try:
            item = await asyncio.wait_for(queue.get(), timeout=5.0)
        except asyncio.TimeoutError as exc:
            raise CameraTimeoutError(
                "Timed out waiting for a V4L2 frame") from exc
        finally:
            try:
                self._broadcast_subs.remove(queue)
            except ValueError:
                pass
        if item is None:
            raise CameraDisconnectedError("V4L2 stream stopped")
        return self._build_frame(item)

    async def stream(self, fps: float = 30.0) -> AsyncIterator[CapturedFrame]:
        """Async frame iterator.

        Attempts S_PARM at stream start; if the driver ignores it (many
        ISI pipelines do), the requested fps is still honored here by
        dropping frames that arrive faster than 1/fps.
        """
        self._require_connected()
        await self._ensure_streaming(fps)
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        self._broadcast_subs.append(queue)
        min_interval = 1.0 / fps if fps > 0 else 0.0
        next_emit = 0.0
        try:
            while self._connected:
                item = await queue.get()
                if item is None:
                    break
                now = time.monotonic()
                if min_interval > 0 and now < next_emit:
                    continue    # drop — pace to the requested fps
                next_emit = now + min_interval
                yield self._build_frame(item)
        finally:
            try:
                self._broadcast_subs.remove(queue)
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def capabilities(self) -> dict[Feature, FeatureCapability]:
        """Derived from the QUERYCTRL/G_PARM probes cached at connect()."""
        self._require_connected()
        caps: dict[Feature, FeatureCapability] = {}
        if self._exposure_ctrl is not None:
            caps[Feature.EXPOSURE] = FeatureCapability(
                supported=True,
                range=self._exposure_range_us(),
                auto_available=False,
            )
        else:
            caps[Feature.EXPOSURE] = FeatureCapability(supported=False)
        if self._gain_ctrl is not None:
            caps[Feature.GAIN] = FeatureCapability(
                supported=True,
                range=NumericRange(
                    min=float(self._gain_ctrl.minimum),
                    max=float(self._gain_ctrl.maximum),
                    step=float(self._gain_ctrl.step),
                ),
                auto_available=False,
            )
        else:
            caps[Feature.GAIN] = FeatureCapability(supported=False)
        caps[Feature.PIXEL_FORMAT] = FeatureCapability(
            supported=bool(self._fourccs),
            available_values=self._available_format_names(),
        )
        caps[Feature.FRAME_RATE] = FeatureCapability(
            supported=self._has_timeperframe,
            range=_FPS_RANGE if self._has_timeperframe else None,
        )
        # AVT vendor-extension CIDs (trigger, ROI crop, temperature,
        # user sets) land with the avt3 driver bring-up.
        caps[Feature.ROI] = FeatureCapability(supported=False)
        caps[Feature.TRIGGER] = FeatureCapability(supported=False)
        caps[Feature.TEMPERATURE] = FeatureCapability(supported=False)
        caps[Feature.USER_SET] = FeatureCapability(supported=False)
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
        fps = self._fps_actual if self._streaming else self._fps_value
        return CameraStatus(
            connected=True,
            streaming=self._streaming,
            device=self._device,
            current_exposure_us=self._exposure_us,
            current_gain_db=self._gain_db,
            current_temperature_c=None,
            current_fps=fps,
            current_pixel_format=self._pixel_format_name(),
            current_roi={"width": self._fmt_width,
                         "height": self._fmt_height,
                         "offset_x": 0, "offset_y": 0},
            current_trigger_mode="freerun",
        )

    def device_info(self) -> DeviceInfo:
        self._require_connected()
        return self._device

    # ------------------------------------------------------------------
    # Exposure — V4L2_CID_EXPOSURE_ABSOLUTE (100 µs) or raw fallback
    # ------------------------------------------------------------------

    def _exposure_range_us(self) -> NumericRange:
        ctrl = self._exposure_ctrl
        return NumericRange(
            min=ctrl.minimum * self._exposure_scale,
            max=ctrl.maximum * self._exposure_scale,
            step=ctrl.step * self._exposure_scale,
        )

    async def set_exposure(self, *, auto: bool = False,
                           time_us: Optional[float] = None) -> ExposureInfo:
        self._require_connected()
        if self._exposure_ctrl is None:
            raise FeatureNotSupportedError(Feature.EXPOSURE)
        if auto:
            # V4L2_CID_EXPOSURE_AUTO wiring deferred to AVT bring-up.
            raise FeatureNotSupportedError(Feature.EXPOSURE)
        if time_us is not None:
            rng = self._exposure_range_us()
            if time_us < rng.min or time_us > rng.max:
                raise FeatureOutOfRangeError(Feature.EXPOSURE, time_us, rng)
            raw = int(round(time_us / self._exposure_scale))
            self._s_ctrl(self._fd, self._exposure_ctrl.cid, raw)
            self._exposure_us = raw * self._exposure_scale
        return await self.get_exposure()

    async def get_exposure(self) -> ExposureInfo:
        self._require_connected()
        if self._exposure_ctrl is None:
            raise FeatureNotSupportedError(Feature.EXPOSURE)
        raw = self._g_ctrl(self._fd, self._exposure_ctrl.cid)
        self._exposure_us = raw * self._exposure_scale
        return ExposureInfo(
            auto=False,
            time_us=self._exposure_us,
            range=self._exposure_range_us(),
            auto_available=False,
        )

    # ------------------------------------------------------------------
    # Gain — V4L2_CID_ANALOGUE_GAIN raw units reported as dB
    # ------------------------------------------------------------------

    async def set_gain(self, *, auto: bool = False,
                       value_db: Optional[float] = None) -> GainInfo:
        self._require_connected()
        if self._gain_ctrl is None:
            raise FeatureNotSupportedError(Feature.GAIN)
        if auto:
            raise FeatureNotSupportedError(Feature.GAIN)
        if value_db is not None:
            # Driver units pass through 1:1 as "dB". The Alvium sensor's
            # true unit→dB conversion (AVT datasheet, typically 0.1 dB
            # per step) is applied once the vendor CIDs are wired up.
            rng = NumericRange(
                min=float(self._gain_ctrl.minimum),
                max=float(self._gain_ctrl.maximum),
                step=float(self._gain_ctrl.step),
            )
            if value_db < rng.min or value_db > rng.max:
                raise FeatureOutOfRangeError(Feature.GAIN, value_db, rng)
            self._s_ctrl(self._fd, self._gain_ctrl.cid,
                         int(round(value_db)))
            self._gain_db = float(int(round(value_db)))
        return await self.get_gain()

    async def get_gain(self) -> GainInfo:
        self._require_connected()
        if self._gain_ctrl is None:
            raise FeatureNotSupportedError(Feature.GAIN)
        raw = self._g_ctrl(self._fd, self._gain_ctrl.cid)
        self._gain_db = float(raw)
        return GainInfo(
            auto=False,
            value_db=self._gain_db,
            range=NumericRange(
                min=float(self._gain_ctrl.minimum),
                max=float(self._gain_ctrl.maximum),
                step=float(self._gain_ctrl.step),
            ),
            auto_available=False,
        )

    # ------------------------------------------------------------------
    # Pixel format
    # ------------------------------------------------------------------

    async def set_pixel_format(self, *, format: str) -> PixelFormatInfo:
        self._require_connected()
        fcc = v4l2.PIXEL_FORMAT_MAP_INV.get(format)
        if fcc is None or fcc not in self._fourccs:
            raise FeatureOutOfRangeError(
                Feature.PIXEL_FORMAT, 0,
                NumericRange(min=0, max=max(len(self._fourccs) - 1, 0),
                             step=1),
            )
        # S_FMT returns EBUSY while buffers are in flight — stop the
        # capture thread first. Consumers restart streaming on demand.
        await self._stop_stream()
        fmt = v4l2.v4l2_format()
        fmt.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        fmt.fmt.pix.width = self._fmt_width
        fmt.fmt.pix.height = self._fmt_height
        fmt.fmt.pix.pixelformat = fcc
        fmt.fmt.pix.field = v4l2.V4L2_FIELD_NONE
        try:
            self._io.ioctl(self._fd, v4l2.VIDIOC_S_FMT, fmt)
            self._read_back_format(self._fd)
        except OSError as exc:
            raise CameraError(f"S_FMT {format} failed: {exc}") from exc
        info = await self.get_pixel_format()
        info.invalidated = [Feature.FRAME_RATE]
        return info

    async def get_pixel_format(self) -> PixelFormatInfo:
        self._require_connected()
        return PixelFormatInfo(
            format=self._pixel_format_name(),
            available=self._available_format_names(),
        )

    # ------------------------------------------------------------------
    # Frame rate — VIDIOC_S_PARM / G_PARM
    # ------------------------------------------------------------------

    def _set_timeperframe(self, fd: int, fps: float) -> float:
        """S_PARM helper. Returns the fps the driver actually granted."""
        sp = v4l2.v4l2_streamparm()
        sp.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        sp.parm.capture.timeperframe.numerator = 1000
        sp.parm.capture.timeperframe.denominator = int(round(fps * 1000))
        try:
            self._io.ioctl(fd, v4l2.VIDIOC_S_PARM, sp)
        except OSError as exc:
            raise CameraError(f"S_PARM {fps} fps failed: {exc}") from exc
        tpf = sp.parm.capture.timeperframe
        if tpf.numerator:
            return round(tpf.denominator / tpf.numerator, 3)
        return fps

    async def set_frame_rate(self, *, enable: bool,
                             value: Optional[float] = None) -> FrameRateInfo:
        self._require_connected()
        if not self._has_timeperframe:
            raise FeatureNotSupportedError(Feature.FRAME_RATE)
        self._fps_enable = enable
        if enable and value is not None:
            if value < _FPS_RANGE.min or value > _FPS_RANGE.max:
                raise FeatureOutOfRangeError(
                    Feature.FRAME_RATE, value, _FPS_RANGE)
            self._fps_value = self._set_timeperframe(self._fd, value)
        return await self.get_frame_rate()

    async def get_frame_rate(self) -> FrameRateInfo:
        self._require_connected()
        if not self._has_timeperframe:
            raise FeatureNotSupportedError(Feature.FRAME_RATE)
        sp = v4l2.v4l2_streamparm()
        sp.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        try:
            self._io.ioctl(self._fd, v4l2.VIDIOC_G_PARM, sp)
        except OSError as exc:
            raise CameraError(f"G_PARM failed: {exc}") from exc
        tpf = sp.parm.capture.timeperframe
        if tpf.numerator:
            self._fps_value = round(tpf.denominator / tpf.numerator, 3)
        return FrameRateInfo(
            enable=self._fps_enable,
            value=self._fps_value or 0.0,
            range=_FPS_RANGE,
        )

    # ROI / trigger / temperature / user_set intentionally inherit the
    # ABC defaults (FeatureNotSupportedError) until the AVT extension
    # CIDs are available.
