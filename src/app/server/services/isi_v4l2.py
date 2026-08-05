"""
isi_v4l2.py — Native V4L2 MPLANE capture for the Alvium CSI-2 on i.MX8MP.

The NXP ISI capture node (`mxc-isi-cap`, /dev/video3 on the bench) is
multiplanar-only, which neither OpenCV's V4L2 backend nor the pip
opencv wheel's (absent) GStreamer support can open. This module drives
it with raw ioctls and exposes `IsiV4l2Capture`, a duck-type of
`cv2.VideoCapture` (read/get/set/isOpened/release), so `CameraService`
can use it through its existing OpenCV code path unchanged.

Camera controls (exposure/gain) live on the Allied Vision `avt3` I2C
subdevice and only answer the *extended* control ioctls — plain
VIDIOC_G/S_CTRL returns EINVAL. Units: exposure in nanoseconds
(INTEGER64), gain in millibel (0.01 dB).

Board-verified quirks this module encodes (2026-08-05, C-052m):
  - open() must NOT use O_NONBLOCK (driver returns EBUSY)
  - an open fd on the ISI m2m node claims the channel — keep failed
    probes closed
  - stock+AVT-patched 5.15 ISI outputs YUYV (GREY negotiates to RGBP);
    the sensor is mono, so Y-extraction is lossless
  - the ISI cannot upscale: capture size must not exceed the sensor
    format (816x624 on the C-052m)

IEC 62304 SW Class: B
"""

from __future__ import annotations

import ctypes
import fcntl
import glob
import logging
import mmap
import os
import select

import numpy as np

log = logging.getLogger(__name__)

_u8, _u16, _u32 = ctypes.c_uint8, ctypes.c_uint16, ctypes.c_uint32
_s32, _u64, _s64 = ctypes.c_int32, ctypes.c_uint64, ctypes.c_int64

# ---------------------------------------------------------------------------
# V4L2 ABI (64-bit) — sizes assert-checked at import
# ---------------------------------------------------------------------------

VIDIOC_QUERYCAP = 0x80685600
VIDIOC_S_FMT = 0xC0D05605
VIDIOC_REQBUFS = 0xC0145608
VIDIOC_QUERYBUF = 0xC0585609
VIDIOC_QBUF = 0xC058560F
VIDIOC_DQBUF = 0xC0585611
VIDIOC_STREAMON = 0x40045612
VIDIOC_STREAMOFF = 0x40045613
VIDIOC_G_EXT_CTRLS = 0xC0205647
VIDIOC_S_EXT_CTRLS = 0xC0205648
VIDIOC_QUERY_EXT_CTRL = 0xC0E85667
VIDIOC_QUERYMENU = 0xC02C5625
VIDIOC_SUBDEV_G_SELECTION = 0xC040563D
VIDIOC_SUBDEV_S_SELECTION = 0xC040563E
VIDIOC_SUBDEV_G_FRAME_INTERVAL = 0xC0305615
VIDIOC_SUBDEV_S_FRAME_INTERVAL = 0xC0305616

SEL_TGT_CROP = 0x0000
SEL_TGT_CROP_DEFAULT = 0x0001
SEL_TGT_CROP_BOUNDS = 0x0002
SUBDEV_FMT_ACTIVE = 1

CTRL_FLAG_NEXT = 0x80000000 | 0x40000000   # NEXT_CTRL | NEXT_COMPOUND
CTRL_TYPE_NAMES = {1: "int", 2: "bool", 3: "menu", 4: "button", 5: "int64",
                   6: "ctrl_class", 7: "string", 9: "int_menu",
                   0x0100: "u8", 0x0101: "u16", 0x0102: "u32",
                   0x0106: "area"}
CTRL_FLAG_READ_ONLY = 0x0004
CTRL_FLAG_INACTIVE = 0x0010

BUF_TYPE_CAPTURE_MPLANE = 9
MEM_MMAP = 1
CAP_VIDEO_CAPTURE_MPLANE = 0x00001000
FMT_YUYV = 0x56595559  # 'YUYV'

CID_EXPOSURE = 0x00980911       # ns on the avt3 subdev (INTEGER64)
CID_GAIN = 0x00980913           # millibel on the avt3 subdev
CID_EXPOSURE_AUTO = 0x009A0901  # 0 = auto, 1 = manual
CID_DEVICE_TEMPERATURE = 0x009A0933  # 0.1 degC, read-only

# cv2.CAP_PROP_* numeric values (avoid importing cv2 here)
PROP_WIDTH = 3
PROP_HEIGHT = 4
PROP_FPS = 5
PROP_EXPOSURE = 15   # CameraService passes SECONDS
PROP_GAIN = 14       # dB


class _Capability(ctypes.Structure):
    _fields_ = [("driver", ctypes.c_char * 16), ("card", ctypes.c_char * 32),
                ("bus_info", ctypes.c_char * 32), ("version", _u32),
                ("capabilities", _u32), ("device_caps", _u32),
                ("reserved", _u32 * 3)]


class _PlanePixFmt(ctypes.Structure):
    _fields_ = [("sizeimage", _u32), ("bytesperline", _u32),
                ("reserved", _u16 * 6)]


class _PixFmtMplane(ctypes.Structure):
    _fields_ = [("width", _u32), ("height", _u32), ("pixelformat", _u32),
                ("field", _u32), ("colorspace", _u32),
                ("plane_fmt", _PlanePixFmt * 8),
                ("num_planes", _u8), ("flags", _u8), ("ycbcr_enc", _u8),
                ("quantization", _u8), ("xfer_func", _u8),
                ("reserved", _u8 * 7)]


class _FormatMp(ctypes.Structure):
    _fields_ = [("type", _u32), ("_pad", _u32), ("pix_mp", _PixFmtMplane),
                ("_tail", _u8 * (208 - 8 - 192))]


class _RequestBuffers(ctypes.Structure):
    _fields_ = [("count", _u32), ("type", _u32), ("memory", _u32),
                ("capabilities", _u32), ("reserved", _u32 * 1)]


class _Plane(ctypes.Structure):
    _fields_ = [("bytesused", _u32), ("length", _u32), ("m", _u64),
                ("data_offset", _u32), ("reserved", _u32 * 11)]


class _Timecode(ctypes.Structure):
    _fields_ = [("type", _u32), ("flags", _u32), ("frames", _u8),
                ("seconds", _u8), ("minutes", _u8), ("hours", _u8),
                ("userbits", _u8 * 4)]


class _BufferMp(ctypes.Structure):
    _fields_ = [("index", _u32), ("type", _u32), ("bytesused", _u32),
                ("flags", _u32), ("field", _u32), ("_pad", _u32),
                ("tv_sec", _u64), ("tv_usec", _u64),
                ("timecode", _Timecode), ("sequence", _u32), ("memory", _u32),
                ("m", _u64), ("length", _u32),
                ("reserved2", _u32), ("request_fd", _u32), ("reserved", _u32)]


class _QueryExtCtrl(ctypes.Structure):
    _fields_ = [("id", _u32), ("type", _u32), ("name", ctypes.c_char * 32),
                ("minimum", _s64), ("maximum", _s64), ("step", _u64),
                ("default_value", _s64), ("flags", _u32), ("elem_size", _u32),
                ("elems", _u32), ("nr_of_dims", _u32), ("dims", _u32 * 4),
                ("reserved", _u32 * 32)]


class _ExtControl(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("id", _u32), ("size", _u32), ("reserved2", _u32),
                ("value64", _s64)]


class _ExtControlPtr(ctypes.Structure):
    """v4l2_ext_control variant with the union used as a payload pointer
    (string/compound controls)."""
    _pack_ = 1
    _fields_ = [("id", _u32), ("size", _u32), ("reserved2", _u32),
                ("ptr", ctypes.c_void_p)]


class _QueryMenu(ctypes.Structure):
    _fields_ = [("id", _u32), ("index", _u32), ("name", ctypes.c_char * 32),
                ("reserved", _u32)]


class _Rect(ctypes.Structure):
    _fields_ = [("left", _s32), ("top", _s32), ("width", _u32), ("height", _u32)]


class _SubdevSelection(ctypes.Structure):
    _fields_ = [("which", _u32), ("pad", _u32), ("target", _u32),
                ("flags", _u32), ("r", _Rect), ("reserved", _u32 * 8)]


class _Fract(ctypes.Structure):
    _fields_ = [("numerator", _u32), ("denominator", _u32)]


class _SubdevFrameInterval(ctypes.Structure):
    _fields_ = [("pad", _u32), ("interval", _Fract), ("reserved", _u32 * 9)]


class _ExtControls(ctypes.Structure):
    _fields_ = [("which", _u32), ("count", _u32), ("error_idx", _u32),
                ("request_fd", _s32), ("reserved", _u32 * 1),
                ("controls", ctypes.c_void_p)]


assert ctypes.sizeof(_FormatMp) == 208
assert ctypes.sizeof(_Plane) == 64
assert ctypes.sizeof(_BufferMp) == 88
assert ctypes.sizeof(_QueryExtCtrl) == 232
assert ctypes.sizeof(_ExtControl) == 20
assert ctypes.sizeof(_ExtControls) == 32


# ---------------------------------------------------------------------------
# Subdev controls (avt3)
# ---------------------------------------------------------------------------

class AvtSubdevControls:
    """Exposure/gain via extended controls on the avt3 I2C subdevice."""

    def __init__(self, subdev_path: str) -> None:
        self._path = subdev_path
        self._fd = os.open(subdev_path, os.O_RDWR)
        self.exposure_range_ns = self._query_range(CID_EXPOSURE)
        self.gain_range_mb = self._query_range(CID_GAIN)

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def _query_range(self, cid: int):
        q = _QueryExtCtrl()
        q.id = cid
        fcntl.ioctl(self._fd, VIDIOC_QUERY_EXT_CTRL, q)
        return (q.minimum, q.maximum)

    def _get(self, cid: int) -> int:
        ec = _ExtControl()
        ec.id = cid
        cs = _ExtControls()
        cs.which = 0
        cs.count = 1
        cs.controls = ctypes.addressof(ec)
        fcntl.ioctl(self._fd, VIDIOC_G_EXT_CTRLS, cs)
        return ec.value64

    def _set(self, cid: int, value: int) -> None:
        ec = _ExtControl()
        ec.id = cid
        ec.value64 = int(value)
        cs = _ExtControls()
        cs.which = 0
        cs.count = 1
        cs.controls = ctypes.addressof(ec)
        fcntl.ioctl(self._fd, VIDIOC_S_EXT_CTRLS, cs)

    # -- generic control surface (drives the UI "Parameters" tab) -------
    def _query_one(self, cid: int) -> _QueryExtCtrl:
        q = _QueryExtCtrl()
        q.id = cid
        fcntl.ioctl(self._fd, VIDIOC_QUERY_EXT_CTRL, q)
        return q

    def _get_string(self, cid: int, max_len: int) -> str | None:
        buf = ctypes.create_string_buffer(max_len + 1)
        ec = _ExtControlPtr()
        ec.id = cid
        ec.size = max_len + 1
        ec.ptr = ctypes.addressof(buf)
        cs = _ExtControls()
        cs.which = 0
        cs.count = 1
        cs.controls = ctypes.addressof(ec)
        try:
            fcntl.ioctl(self._fd, VIDIOC_G_EXT_CTRLS, cs)
            return buf.value.decode(errors="replace")
        except OSError:
            return None

    def enumerate_controls(self) -> list[dict]:
        """Walk every control the sensor driver exposes (NEXT_CTRL walk).

        Returns UI-ready dicts: id, name, type, min/max/step/default,
        flags (read_only/inactive), current value, and menu item names.
        The list is whatever the connected camera model supports, so a
        different Alvium (e.g. the C-158m) shows its own set.
        """
        out: list[dict] = []
        cid = 0
        while True:
            q = _QueryExtCtrl()
            q.id = cid | CTRL_FLAG_NEXT
            try:
                fcntl.ioctl(self._fd, VIDIOC_QUERY_EXT_CTRL, q)
            except OSError:
                break
            cid = q.id
            ctype = CTRL_TYPE_NAMES.get(q.type, f"type{q.type}")
            entry: dict = {
                "id": q.id,
                "name": q.name.decode(),
                "type": ctype,
                "min": q.minimum,
                "max": q.maximum,
                "step": q.step,
                "default": q.default_value,
                "read_only": bool(q.flags & CTRL_FLAG_READ_ONLY),
                "inactive": bool(q.flags & CTRL_FLAG_INACTIVE),
            }
            if ctype == "ctrl_class":
                entry["value"] = None
            elif ctype == "string":
                entry["value"] = self._get_string(q.id, int(q.maximum))
            elif ctype in ("u8", "u16", "u32", "area") or ctype.startswith("type"):
                # Compound/array controls (e.g. "Binning Setting" is an
                # AREA = width x height pair) — read as a u32 list.
                n = max(1, (q.elem_size * max(1, q.elems)) // 4)
                try:
                    entry["value"] = self._get_compound_u32(q.id, n)
                except OSError:
                    entry["value"] = None
            elif ctype == "button":
                entry["value"] = None
            else:
                try:
                    entry["value"] = self._get(q.id)
                except OSError:
                    entry["value"] = None
            if ctype in ("menu", "int_menu"):
                items: dict[int, str] = {}
                for i in range(int(q.minimum), int(q.maximum) + 1):
                    m = _QueryMenu()
                    m.id = q.id
                    m.index = i
                    try:
                        fcntl.ioctl(self._fd, VIDIOC_QUERYMENU, m)
                        items[i] = m.name.decode()
                    except OSError:
                        pass
                entry["menu"] = items
            out.append(entry)
        return out

    def set_control(self, cid: int, value):
        """Set one control by numeric id; returns the read-back value.

        Scalar controls take an int; compound controls (u8/u16/u32/area)
        take a list of ints. Buttons fire on any write, read back None.
        """
        q = self._query_one(cid)
        if q.flags & CTRL_FLAG_READ_ONLY:
            raise PermissionError(f"control {q.name.decode()!r} is read-only")
        if isinstance(value, (list, tuple)):
            n = max(1, (q.elem_size * max(1, q.elems)) // 4)
            buf = (ctypes.c_uint32 * n)(*([int(v) for v in value] + [0] * n)[:n])
            ec = _ExtControlPtr()
            ec.id = cid
            ec.size = 4 * n
            ec.ptr = ctypes.addressof(buf)
            cs = _ExtControls()
            cs.which = 0
            cs.count = 1
            cs.controls = ctypes.addressof(ec)
            fcntl.ioctl(self._fd, VIDIOC_S_EXT_CTRLS, cs)
            return self._get_compound_u32(cid, n)
        self._set(cid, int(value))
        if CTRL_TYPE_NAMES.get(q.type) == "button":
            return None
        return self._get(cid)

    # -- compound (array) controls, e.g. "Binning Setting" --------------
    def _get_compound_u32(self, cid: int, elems: int) -> list[int]:
        buf = (ctypes.c_uint32 * elems)()
        ec = _ExtControlPtr()
        ec.id = cid
        ec.size = 4 * elems
        ec.ptr = ctypes.addressof(buf)
        cs = _ExtControls()
        cs.which = 0
        cs.count = 1
        cs.controls = ctypes.addressof(ec)
        fcntl.ioctl(self._fd, VIDIOC_G_EXT_CTRLS, cs)
        return list(buf)

    def set_compound_u32(self, cid: int, values: list[int]) -> list[int]:
        q = self._query_one(cid)
        if q.flags & CTRL_FLAG_READ_ONLY:
            raise PermissionError(f"control {q.name.decode()!r} is read-only")
        elems = max(1, q.elems)
        buf = (ctypes.c_uint32 * elems)(*([int(v) for v in values] + [0] * elems)[:elems])
        ec = _ExtControlPtr()
        ec.id = cid
        ec.size = 4 * elems
        ec.ptr = ctypes.addressof(buf)
        cs = _ExtControls()
        cs.which = 0
        cs.count = 1
        cs.controls = ctypes.addressof(ec)
        fcntl.ioctl(self._fd, VIDIOC_S_EXT_CTRLS, cs)
        return self._get_compound_u32(cid, elems)

    # -- sensor frame rate via the subdev frame-interval API ------------
    def get_frame_rate(self) -> float | None:
        fi = _SubdevFrameInterval()
        fi.pad = 0
        try:
            fcntl.ioctl(self._fd, VIDIOC_SUBDEV_G_FRAME_INTERVAL, fi)
        except OSError:
            return None
        if fi.interval.numerator == 0:
            return None
        return fi.interval.denominator / fi.interval.numerator

    def set_frame_rate(self, fps: float) -> float | None:
        fi = _SubdevFrameInterval()
        fi.pad = 0
        fi.interval.numerator = 1000
        fi.interval.denominator = max(1, int(round(fps * 1000)))
        fcntl.ioctl(self._fd, VIDIOC_SUBDEV_S_FRAME_INTERVAL, fi)
        return self.get_frame_rate()

    # -- ROI (sensor crop) via the subdev selection API -----------------
    def get_selection(self, target: int = SEL_TGT_CROP) -> dict:
        s = _SubdevSelection()
        s.which = SUBDEV_FMT_ACTIVE
        s.pad = 0
        s.target = target
        fcntl.ioctl(self._fd, VIDIOC_SUBDEV_G_SELECTION, s)
        return {"left": s.r.left, "top": s.r.top,
                "width": s.r.width, "height": s.r.height}

    def set_selection(self, left: int, top: int, width: int, height: int) -> dict:
        s = _SubdevSelection()
        s.which = SUBDEV_FMT_ACTIVE
        s.pad = 0
        s.target = SEL_TGT_CROP
        s.r.left = int(left)
        s.r.top = int(top)
        s.r.width = int(width)
        s.r.height = int(height)
        fcntl.ioctl(self._fd, VIDIOC_SUBDEV_S_SELECTION, s)
        # Driver may clamp/align — return what it actually applied.
        return {"left": s.r.left, "top": s.r.top,
                "width": s.r.width, "height": s.r.height}

    # -- public, in CameraService units ---------------------------------
    def get_exposure_us(self) -> float:
        return self._get(CID_EXPOSURE) / 1000.0

    def set_exposure_us(self, exposure_us: float) -> float:
        ns = int(exposure_us * 1000.0)
        lo, hi = self.exposure_range_ns
        ns = max(lo, min(hi, ns))
        self._set(CID_EXPOSURE_AUTO, 1)  # manual
        self._set(CID_EXPOSURE, ns)
        return self._get(CID_EXPOSURE) / 1000.0

    def get_gain_db(self) -> float:
        return self._get(CID_GAIN) / 100.0

    def set_gain_db(self, gain_db: float) -> float:
        mb = int(gain_db * 100.0)
        lo, hi = self.gain_range_mb
        mb = max(lo, min(hi, mb))
        self._set(CID_GAIN, mb)
        return self._get(CID_GAIN) / 100.0


def _find_avt_subdev() -> str | None:
    """The avt3 subdev is the one that answers an Exposure ext-query."""
    for path in sorted(glob.glob("/dev/v4l-subdev*")):
        try:
            fd = os.open(path, os.O_RDWR)
        except OSError:
            continue
        try:
            q = _QueryExtCtrl()
            q.id = CID_EXPOSURE
            fcntl.ioctl(fd, VIDIOC_QUERY_EXT_CTRL, q)
            if q.name == b"Exposure":
                return path
        except OSError:
            pass
        finally:
            os.close(fd)
    return None


def _find_isi_capture_node() -> str | None:
    for path in sorted(glob.glob("/dev/video*")):
        try:
            fd = os.open(path, os.O_RDWR)  # no O_NONBLOCK — EBUSY quirk
        except OSError:
            continue
        try:
            cap = _Capability()
            fcntl.ioctl(fd, VIDIOC_QUERYCAP, cap)
            caps = cap.device_caps or cap.capabilities
            if cap.driver == b"mxc-isi-cap" and caps & CAP_VIDEO_CAPTURE_MPLANE:
                return path
        except OSError:
            pass
        finally:
            os.close(fd)
    return None


# ---------------------------------------------------------------------------
# Capture (duck-types cv2.VideoCapture)
# ---------------------------------------------------------------------------

class IsiV4l2Capture:
    """MPLANE mmap capture from the ISI node, mono8 frames out.

    read() returns (True, HxW uint8 ndarray) like cv2.VideoCapture on a
    grayscale source. set()/get() route CAP_PROP_EXPOSURE / CAP_PROP_GAIN
    to the avt3 subdevice (CameraService's generic OpenCV settings path).
    """

    NOMINAL_FPS = 50.0
    N_BUFFERS = 4
    READ_TIMEOUT_S = 2.0

    def __init__(self, device: str | None = None, subdev: str | None = None,
                 width: int = 816, height: int = 624) -> None:
        self._device = device or _find_isi_capture_node()
        if self._device is None:
            raise RuntimeError("no mxc-isi-cap MPLANE node found")
        subdev = subdev or _find_avt_subdev()
        if subdev is None:
            raise RuntimeError("no avt3 subdev with Exposure control found")
        self.ctrl = AvtSubdevControls(subdev)

        self._fd = os.open(self._device, os.O_RDWR)
        self._maps: list[mmap.mmap] = []
        self._streaming = False
        self._open = True
        try:
            self._width, self._height = self._setup(width, height)
        except Exception:
            self.release()
            raise
        log.info("IsiV4l2Capture: %s %dx%d YUYV (subdev %s)",
                 self._device, self._width, self._height, subdev)

    # ------------------------------------------------------------------
    def _setup(self, width: int, height: int):
        fmt = _FormatMp()
        fmt.type = BUF_TYPE_CAPTURE_MPLANE
        fmt.pix_mp.width = width
        fmt.pix_mp.height = height
        fmt.pix_mp.pixelformat = FMT_YUYV
        fmt.pix_mp.field = 1  # NONE
        fmt.pix_mp.num_planes = 1
        fcntl.ioctl(self._fd, VIDIOC_S_FMT, fmt)
        if fmt.pix_mp.pixelformat != FMT_YUYV:
            raise RuntimeError("ISI refused YUYV")
        w, h = fmt.pix_mp.width, fmt.pix_mp.height

        req = _RequestBuffers()
        req.count = self.N_BUFFERS
        req.type = BUF_TYPE_CAPTURE_MPLANE
        req.memory = MEM_MMAP
        fcntl.ioctl(self._fd, VIDIOC_REQBUFS, req)
        if req.count < 2:
            raise RuntimeError(f"ISI granted only {req.count} buffers")

        for i in range(req.count):
            planes = (_Plane * 1)()
            buf = _BufferMp()
            buf.index = i
            buf.type = BUF_TYPE_CAPTURE_MPLANE
            buf.memory = MEM_MMAP
            buf.m = ctypes.addressof(planes)
            buf.length = 1
            fcntl.ioctl(self._fd, VIDIOC_QUERYBUF, buf)
            m = mmap.mmap(self._fd, planes[0].length, mmap.MAP_SHARED,
                          mmap.PROT_READ | mmap.PROT_WRITE,
                          offset=planes[0].m & 0xFFFFFFFF)
            self._maps.append(m)
            fcntl.ioctl(self._fd, VIDIOC_QBUF, buf)

        fcntl.ioctl(self._fd, VIDIOC_STREAMON,
                    ctypes.c_int(BUF_TYPE_CAPTURE_MPLANE))
        self._streaming = True
        return w, h

    def _teardown_stream(self) -> None:
        """Stop streaming and release mmap buffers (fd stays open)."""
        if self._streaming:
            try:
                fcntl.ioctl(self._fd, VIDIOC_STREAMOFF,
                            ctypes.c_int(BUF_TYPE_CAPTURE_MPLANE))
            except OSError:
                pass
            self._streaming = False
        for m in self._maps:
            try:
                m.close()
            except Exception:
                pass
        self._maps = []
        req = _RequestBuffers()
        req.count = 0
        req.type = BUF_TYPE_CAPTURE_MPLANE
        req.memory = MEM_MMAP
        try:
            fcntl.ioctl(self._fd, VIDIOC_REQBUFS, req)
        except OSError:
            pass

    # -- preset application (stream paused: several controls EBUSY
    #    while streaming, same as frame-interval) -----------------------
    def apply_snapshot(self, fps: float | None, roi: dict | None,
                       controls: list) -> dict:
        """Apply an (fps, roi, [(cid, value, name), ...]) snapshot with the
        capture pipeline stopped, then bring the stream back up. Returns
        {name: error} for per-item failures."""
        errors: dict[str, str] = {}
        self._teardown_stream()
        try:
            if fps:
                try:
                    self.ctrl.set_frame_rate(fps)
                except OSError as exc:
                    errors["fps"] = str(exc)
            width, height = self._width, self._height
            if roi:
                try:
                    applied = self.ctrl.set_selection(
                        roi["left"], roi["top"], roi["width"], roi["height"])
                    width, height = applied["width"], applied["height"]
                except OSError as exc:
                    errors["roi"] = str(exc)
            for cid, value, name in controls:
                try:
                    self.ctrl.set_control(cid, value)
                except (OSError, PermissionError) as exc:
                    errors[name] = str(exc)
        finally:
            self._width, self._height = self._setup(width, height)
        return errors

    # -- sensor frame rate (needs the stream stopped: driver EBUSYs) ----
    def set_sensor_fps(self, fps: float) -> float | None:
        self._teardown_stream()
        try:
            actual = self.ctrl.set_frame_rate(fps)
        finally:
            self._width, self._height = self._setup(self._width, self._height)
        log.info("IsiV4l2Capture: sensor frame rate -> %s fps", actual)
        return actual

    # -- ROI ------------------------------------------------------------
    def get_roi(self) -> dict:
        return {
            "crop": self.ctrl.get_selection(SEL_TGT_CROP),
            "bounds": self.ctrl.get_selection(SEL_TGT_CROP_BOUNDS),
            "default": self.ctrl.get_selection(SEL_TGT_CROP_DEFAULT),
            "capture": {"width": self._width, "height": self._height},
        }

    def set_roi(self, left: int, top: int, width: int, height: int) -> dict:
        """Apply a sensor crop and rebuild the capture pipeline at the new
        size. Returns the rect the driver actually applied (it may clamp
        or align the request)."""
        self._teardown_stream()
        try:
            applied = self.ctrl.set_selection(left, top, width, height)
            self._width, self._height = self._setup(applied["width"],
                                                    applied["height"])
        except Exception:
            # Best effort to come back up at the previous size.
            try:
                if not self._streaming:
                    self._width, self._height = self._setup(self._width,
                                                            self._height)
            except Exception:
                log.exception("IsiV4l2Capture: stream recovery failed")
            raise
        log.info("IsiV4l2Capture: ROI -> (%d,%d) %dx%d",
                 applied["left"], applied["top"],
                 applied["width"], applied["height"])
        return self.get_roi()

    def _dqbuf(self) -> _BufferMp | None:
        planes = (_Plane * 1)()
        buf = _BufferMp()
        buf.type = BUF_TYPE_CAPTURE_MPLANE
        buf.memory = MEM_MMAP
        buf.m = ctypes.addressof(planes)
        buf.length = 1
        fcntl.ioctl(self._fd, VIDIOC_DQBUF, buf)
        return buf

    def _qbuf(self, index: int) -> None:
        planes = (_Plane * 1)()
        buf = _BufferMp()
        buf.index = index
        buf.type = BUF_TYPE_CAPTURE_MPLANE
        buf.memory = MEM_MMAP
        buf.m = ctypes.addressof(planes)
        buf.length = 1
        fcntl.ioctl(self._fd, VIDIOC_QBUF, buf)

    # ------------------------------------------------------------------
    # cv2.VideoCapture interface
    # ------------------------------------------------------------------
    def isOpened(self) -> bool:  # noqa: N802 (cv2 naming)
        return self._open and self._streaming

    def read(self):
        """Return (True, mono ndarray) — freshest frame, stale ones dropped."""
        if not self.isOpened():
            return False, None
        r, _, _ = select.select([self._fd], [], [], self.READ_TIMEOUT_S)
        if not r:
            log.warning("IsiV4l2Capture: frame timeout")
            return False, None
        buf = self._dqbuf()
        # Drain to the most recent frame so the stream shows live motion
        # instead of a 4-buffer-deep queue.
        while True:
            r, _, _ = select.select([self._fd], [], [], 0)
            if not r:
                break
            self._qbuf(buf.index)
            buf = self._dqbuf()
        raw = np.frombuffer(self._maps[buf.index],
                            dtype=np.uint8,
                            count=self._width * self._height * 2)
        mono = raw[0::2].reshape(self._height, self._width).copy()
        self._qbuf(buf.index)
        return True, mono

    def get(self, prop: int) -> float:
        if prop == PROP_WIDTH:
            return float(self._width)
        if prop == PROP_HEIGHT:
            return float(self._height)
        if prop == PROP_FPS:
            try:
                return self.ctrl.get_frame_rate() or self.NOMINAL_FPS
            except OSError:
                return self.NOMINAL_FPS
        if prop == PROP_EXPOSURE:
            try:
                return self.ctrl.get_exposure_us() / 1_000_000.0  # seconds
            except OSError:
                return 0.0
        if prop == PROP_GAIN:
            try:
                return self.ctrl.get_gain_db()
            except OSError:
                return 0.0
        return 0.0

    def set(self, prop: int, value: float) -> bool:
        try:
            if prop == PROP_EXPOSURE:
                # CameraService passes seconds (exposure_us / 1e6)
                actual_us = self.ctrl.set_exposure_us(value * 1_000_000.0)
                log.info("IsiV4l2Capture: exposure -> %.0f us", actual_us)
                return True
            if prop == PROP_GAIN:
                actual_db = self.ctrl.set_gain_db(value)
                log.info("IsiV4l2Capture: gain -> %.2f dB", actual_db)
                return True
        except OSError as exc:
            log.warning("IsiV4l2Capture: set(prop=%d) failed: %s", prop, exc)
        return False

    def release(self) -> None:
        if self._streaming:
            try:
                fcntl.ioctl(self._fd, VIDIOC_STREAMOFF,
                            ctypes.c_int(BUF_TYPE_CAPTURE_MPLANE))
            except OSError:
                pass
            self._streaming = False
        for m in self._maps:
            try:
                m.close()
            except Exception:
                pass
        self._maps = []
        if self._open:
            os.close(self._fd)
            self._open = False
        try:
            self.ctrl.close()
        except Exception:
            pass
