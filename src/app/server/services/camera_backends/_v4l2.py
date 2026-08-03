# src/app/server/services/camera_backends/_v4l2.py
"""
_v4l2.py — Pure-ctypes V4L2 ABI layer: structs, ioctl codes, constants.

Mirrors <linux/videodev2.h> for the subset needed by the MMAP streaming
capture path (QUERYCAP / ENUM_FMT / S_FMT / REQBUFS / QUERYBUF / QBUF /
DQBUF / STREAMON / STREAMOFF / S_PARM / QUERYCTRL / G_CTRL / S_CTRL).

Struct layouts target 64-bit Linux (LP64: aarch64 i.MX8MP target and
x86-64 dev hosts). The tricky parts are ``v4l2_buffer`` (its ``m`` union
contains a pointer, forcing 8-byte alignment, and ``struct timeval`` is
two 8-byte longs) and ``v4l2_format`` (its union is 8-byte aligned in
the kernel because ``v4l2_window`` contains pointers — we force the same
alignment with a ``c_uint64`` union member). Expected 64-bit sizes are
verified by unit tests against the kernel's known ioctl code values.

No device access happens at import time — this module is pure data.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import ctypes

# ---------------------------------------------------------------------------
# _IOC macros (asm-generic/ioctl.h)
# ---------------------------------------------------------------------------

_IOC_NRSHIFT   = 0
_IOC_TYPESHIFT = 8
_IOC_SIZESHIFT = 16
_IOC_DIRSHIFT  = 30

_IOC_NONE  = 0
_IOC_WRITE = 1
_IOC_READ  = 2


def _ioc_size(arg) -> int:
    """Accept a ctypes type or an int byte count."""
    if isinstance(arg, int):
        return arg
    return ctypes.sizeof(arg)


def _IOC(direction: int, ioc_type: str, nr: int, size) -> int:
    return (
        (direction << _IOC_DIRSHIFT)
        | (ord(ioc_type) << _IOC_TYPESHIFT)
        | (nr << _IOC_NRSHIFT)
        | (_ioc_size(size) << _IOC_SIZESHIFT)
    )


def _IO(ioc_type: str, nr: int) -> int:
    return _IOC(_IOC_NONE, ioc_type, nr, 0)


def _IOR(ioc_type: str, nr: int, size) -> int:
    return _IOC(_IOC_READ, ioc_type, nr, size)


def _IOW(ioc_type: str, nr: int, size) -> int:
    return _IOC(_IOC_WRITE, ioc_type, nr, size)


def _IOWR(ioc_type: str, nr: int, size) -> int:
    return _IOC(_IOC_READ | _IOC_WRITE, ioc_type, nr, size)


# ---------------------------------------------------------------------------
# fourcc helpers + pixel format map
# ---------------------------------------------------------------------------

def v4l2_fourcc(a: str, b: str, c: str, d: str) -> int:
    return ord(a) | (ord(b) << 8) | (ord(c) << 16) | (ord(d) << 24)


def fourcc_to_str(fcc: int) -> str:
    """Decode a fourcc code to its 4-character string (trailing spaces kept)."""
    return "".join(chr((fcc >> shift) & 0xFF) for shift in (0, 8, 16, 24))


V4L2_PIX_FMT_GREY  = v4l2_fourcc("G", "R", "E", "Y")   # 8-bit greyscale
V4L2_PIX_FMT_Y10   = v4l2_fourcc("Y", "1", "0", " ")   # 10-bit greyscale
V4L2_PIX_FMT_YUYV  = v4l2_fourcc("Y", "U", "Y", "V")   # YUV 4:2:2
V4L2_PIX_FMT_MJPEG = v4l2_fourcc("M", "J", "P", "G")   # Motion-JPEG

# fourcc ↔ CameraBackend API pixel-format name
PIXEL_FORMAT_MAP: dict[int, str] = {
    V4L2_PIX_FMT_GREY:  "mono8",
    V4L2_PIX_FMT_Y10:   "mono10",
    V4L2_PIX_FMT_YUYV:  "yuyv",
    V4L2_PIX_FMT_MJPEG: "mjpeg",
}
PIXEL_FORMAT_MAP_INV: dict[str, int] = {v: k for k, v in PIXEL_FORMAT_MAP.items()}


# ---------------------------------------------------------------------------
# Enums / flags
# ---------------------------------------------------------------------------

V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_MEMORY_MMAP            = 1
V4L2_FIELD_NONE             = 1

# v4l2_capability.capabilities / device_caps flags
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_STREAMING     = 0x04000000
V4L2_CAP_DEVICE_CAPS   = 0x80000000

# v4l2_captureparm.capability flag
V4L2_CAP_TIMEPERFRAME = 0x1000

# v4l2_queryctrl.flags
V4L2_CTRL_FLAG_DISABLED = 0x0001

# v4l2_queryctrl.type
V4L2_CTRL_TYPE_INTEGER = 1

# ---------------------------------------------------------------------------
# Control IDs (linux/v4l2-controls.h)
# ---------------------------------------------------------------------------

V4L2_CTRL_CLASS_USER = 0x00980000
V4L2_CID_BASE        = V4L2_CTRL_CLASS_USER | 0x900
V4L2_CID_EXPOSURE    = V4L2_CID_BASE + 17      # raw, driver-defined units
V4L2_CID_GAIN        = V4L2_CID_BASE + 19      # raw, driver-defined units

V4L2_CTRL_CLASS_CAMERA      = 0x009A0000
V4L2_CID_CAMERA_CLASS_BASE  = V4L2_CTRL_CLASS_CAMERA | 0x900
V4L2_CID_EXPOSURE_AUTO      = V4L2_CID_CAMERA_CLASS_BASE + 1
V4L2_CID_EXPOSURE_ABSOLUTE  = V4L2_CID_CAMERA_CLASS_BASE + 2   # unit: 100 µs

V4L2_CTRL_CLASS_IMAGE_SOURCE     = 0x009E0000
V4L2_CID_IMAGE_SOURCE_CLASS_BASE = V4L2_CTRL_CLASS_IMAGE_SOURCE | 0x900
V4L2_CID_ANALOGUE_GAIN           = V4L2_CID_IMAGE_SOURCE_CLASS_BASE + 3


# ---------------------------------------------------------------------------
# Structs (64-bit Linux layout)
# ---------------------------------------------------------------------------

class timeval(ctypes.Structure):
    """struct timeval — two longs (8 bytes each on LP64)."""
    _fields_ = [
        ("tv_sec",  ctypes.c_long),
        ("tv_usec", ctypes.c_long),
    ]


class v4l2_capability(ctypes.Structure):
    """VIDIOC_QUERYCAP result. sizeof == 104."""
    _fields_ = [
        ("driver",       ctypes.c_char * 16),
        ("card",         ctypes.c_char * 32),
        ("bus_info",     ctypes.c_char * 32),
        ("version",      ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("device_caps",  ctypes.c_uint32),
        ("reserved",     ctypes.c_uint32 * 3),
    ]


class v4l2_pix_format(ctypes.Structure):
    """Single-planar pixel format. sizeof == 48."""
    _fields_ = [
        ("width",        ctypes.c_uint32),
        ("height",       ctypes.c_uint32),
        ("pixelformat",  ctypes.c_uint32),
        ("field",        ctypes.c_uint32),
        ("bytesperline", ctypes.c_uint32),
        ("sizeimage",    ctypes.c_uint32),
        ("colorspace",   ctypes.c_uint32),
        ("priv",         ctypes.c_uint32),
        ("flags",        ctypes.c_uint32),
        # Kernel union { ycbcr_enc; hsv_enc; } — layout-identical u32.
        ("ycbcr_enc",    ctypes.c_uint32),
        ("quantization", ctypes.c_uint32),
        ("xfer_func",    ctypes.c_uint32),
    ]


class _v4l2_format_fmt(ctypes.Union):
    """v4l2_format payload union.

    The kernel union contains v4l2_window (which holds pointers), so it
    is 8-byte aligned on 64-bit — the ``_align`` member reproduces that.
    """
    _fields_ = [
        ("pix",      v4l2_pix_format),
        ("raw_data", ctypes.c_uint8 * 200),
        ("_align",   ctypes.c_uint64 * 25),
    ]


class v4l2_format(ctypes.Structure):
    """VIDIOC_G_FMT / VIDIOC_S_FMT argument. sizeof == 208 on 64-bit."""
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("fmt",  _v4l2_format_fmt),        # at offset 8 (union is 8-aligned)
    ]


class v4l2_fmtdesc(ctypes.Structure):
    """VIDIOC_ENUM_FMT result. sizeof == 64."""
    _fields_ = [
        ("index",       ctypes.c_uint32),
        ("type",        ctypes.c_uint32),
        ("flags",       ctypes.c_uint32),
        ("description", ctypes.c_char * 32),
        ("pixelformat", ctypes.c_uint32),
        ("mbus_code",   ctypes.c_uint32),
        ("reserved",    ctypes.c_uint32 * 3),
    ]


class v4l2_requestbuffers(ctypes.Structure):
    """VIDIOC_REQBUFS argument. sizeof == 20."""
    _fields_ = [
        ("count",        ctypes.c_uint32),
        ("type",         ctypes.c_uint32),
        ("memory",       ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("flags",        ctypes.c_uint8),
        ("reserved",     ctypes.c_uint8 * 3),
    ]


class v4l2_timecode(ctypes.Structure):
    """sizeof == 16."""
    _fields_ = [
        ("type",     ctypes.c_uint32),
        ("flags",    ctypes.c_uint32),
        ("frames",   ctypes.c_uint8),
        ("seconds",  ctypes.c_uint8),
        ("minutes",  ctypes.c_uint8),
        ("hours",    ctypes.c_uint8),
        ("userbits", ctypes.c_uint8 * 4),
    ]


class _v4l2_buffer_m(ctypes.Union):
    """v4l2_buffer memory-location union — pointer member forces 8-align."""
    _fields_ = [
        ("offset",  ctypes.c_uint32),
        ("userptr", ctypes.c_ulong),
        ("planes",  ctypes.c_void_p),
        ("fd",      ctypes.c_int32),
    ]


class v4l2_buffer(ctypes.Structure):
    """VIDIOC_QUERYBUF / QBUF / DQBUF argument. sizeof == 88 on 64-bit.

    64-bit offsets: index=0 type=4 bytesused=8 flags=12 field=16
    (4 pad) timestamp=24 timecode=40 sequence=56 memory=60 m=64
    length=72 reserved2=76 request_fd=80, total 88.
    ctypes inserts the 4 padding bytes before ``timestamp`` automatically
    because ``timeval`` is 8-byte aligned.
    """
    _fields_ = [
        ("index",      ctypes.c_uint32),
        ("type",       ctypes.c_uint32),
        ("bytesused",  ctypes.c_uint32),
        ("flags",      ctypes.c_uint32),
        ("field",      ctypes.c_uint32),
        ("timestamp",  timeval),
        ("timecode",   v4l2_timecode),
        ("sequence",   ctypes.c_uint32),
        ("memory",     ctypes.c_uint32),
        ("m",          _v4l2_buffer_m),
        ("length",     ctypes.c_uint32),
        ("reserved2",  ctypes.c_uint32),
        # Kernel anonymous union { request_fd; reserved; } — s32 layout.
        ("request_fd", ctypes.c_int32),
    ]


class v4l2_fract(ctypes.Structure):
    _fields_ = [
        ("numerator",   ctypes.c_uint32),
        ("denominator", ctypes.c_uint32),
    ]


class v4l2_captureparm(ctypes.Structure):
    """sizeof == 40."""
    _fields_ = [
        ("capability",   ctypes.c_uint32),
        ("capturemode",  ctypes.c_uint32),
        ("timeperframe", v4l2_fract),      # seconds per frame (num/den)
        ("extendedmode", ctypes.c_uint32),
        ("readbuffers",  ctypes.c_uint32),
        ("reserved",     ctypes.c_uint32 * 4),
    ]


class _v4l2_streamparm_parm(ctypes.Union):
    _fields_ = [
        ("capture",  v4l2_captureparm),
        ("raw_data", ctypes.c_uint8 * 200),
    ]


class v4l2_streamparm(ctypes.Structure):
    """VIDIOC_G_PARM / VIDIOC_S_PARM argument. sizeof == 204."""
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("parm", _v4l2_streamparm_parm),
    ]


class v4l2_queryctrl(ctypes.Structure):
    """VIDIOC_QUERYCTRL argument. sizeof == 68."""
    _fields_ = [
        ("id",            ctypes.c_uint32),
        ("type",          ctypes.c_uint32),
        ("name",          ctypes.c_char * 32),
        ("minimum",       ctypes.c_int32),
        ("maximum",       ctypes.c_int32),
        ("step",          ctypes.c_int32),
        ("default_value", ctypes.c_int32),
        ("flags",         ctypes.c_uint32),
        ("reserved",      ctypes.c_uint32 * 2),
    ]


class v4l2_control(ctypes.Structure):
    """VIDIOC_G_CTRL / VIDIOC_S_CTRL argument. sizeof == 8."""
    _fields_ = [
        ("id",    ctypes.c_uint32),
        ("value", ctypes.c_int32),
    ]


# ---------------------------------------------------------------------------
# ioctl request codes (linux/videodev2.h)
# ---------------------------------------------------------------------------

VIDIOC_QUERYCAP  = _IOR("V", 0, v4l2_capability)
VIDIOC_ENUM_FMT  = _IOWR("V", 2, v4l2_fmtdesc)
VIDIOC_G_FMT     = _IOWR("V", 4, v4l2_format)
VIDIOC_S_FMT     = _IOWR("V", 5, v4l2_format)
VIDIOC_REQBUFS   = _IOWR("V", 8, v4l2_requestbuffers)
VIDIOC_QUERYBUF  = _IOWR("V", 9, v4l2_buffer)
VIDIOC_QBUF      = _IOWR("V", 15, v4l2_buffer)
VIDIOC_DQBUF     = _IOWR("V", 17, v4l2_buffer)
VIDIOC_STREAMON  = _IOW("V", 18, ctypes.c_int)
VIDIOC_STREAMOFF = _IOW("V", 19, ctypes.c_int)
VIDIOC_G_PARM    = _IOWR("V", 21, v4l2_streamparm)
VIDIOC_S_PARM    = _IOWR("V", 22, v4l2_streamparm)
VIDIOC_G_CTRL    = _IOWR("V", 27, v4l2_control)
VIDIOC_S_CTRL    = _IOWR("V", 28, v4l2_control)
VIDIOC_QUERYCTRL = _IOWR("V", 36, v4l2_queryctrl)
