"""
test_v4l2_backend.py — Unit tests for the V4L2/MIPI camera backend.

FakeV4l2Io simulates an i.MX8MP ISI capture node carrying an Alvium
1800 C-158m (QUERYCAP bus_info "platform:32e00000.isi.0", GREY-only
format list, exposure-absolute + analogue-gain controls, MMAP streaming
with synthetic mono frames). No /dev/video* device is required.

Also verifies the _v4l2 ctypes layer: 64-bit struct sizes and ioctl
request codes against the kernel's canonical values.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import ctypes
import errno
import time
from collections import deque

import numpy as np
import pytest

from server.services.camera_backends import (
    CameraDisconnectedError, CameraError, Feature, FeatureNotSupportedError,
    FeatureOutOfRangeError,
)
from server.services.camera_backends import _v4l2 as v4l2
from server.services.camera_backends.v4l2_backend import V4l2CameraBackend


# ---------------------------------------------------------------------------
# FakeV4l2Io — in-memory simulation of the V4L2 ioctl surface
# ---------------------------------------------------------------------------

class FakeV4l2Io:
    """Simulated ISI capture node (Alvium 1800 C-158m, GREY only)."""

    SENSOR_W = 1456
    SENSOR_H = 1088

    def __init__(self, *, fail_open: bool = False,
                 with_exposure_absolute: bool = True,
                 with_raw_exposure: bool = False,
                 with_analogue_gain: bool = True,
                 frame_interval_s: float = 0.001) -> None:
        self.fail_open = fail_open
        self.frame_interval_s = frame_interval_s
        self.open_count = 0
        self.close_count = 0

        self.width = self.SENSOR_W
        self.height = self.SENSOR_H
        self.pixelformat = v4l2.V4L2_PIX_FMT_GREY
        self.formats = [v4l2.V4L2_PIX_FMT_GREY]

        # cid -> (min, max, step, default)
        self.ctrl_meta: dict[int, tuple[int, int, int, int]] = {}
        self.ctrl_values: dict[int, int] = {}
        if with_exposure_absolute:
            # V4L2_CID_EXPOSURE_ABSOLUTE — unit 100 µs, range 1..10000
            self.ctrl_meta[v4l2.V4L2_CID_EXPOSURE_ABSOLUTE] = (1, 10_000, 1, 50)
            self.ctrl_values[v4l2.V4L2_CID_EXPOSURE_ABSOLUTE] = 50
        if with_raw_exposure:
            self.ctrl_meta[v4l2.V4L2_CID_EXPOSURE] = (1, 65_535, 1, 100)
            self.ctrl_values[v4l2.V4L2_CID_EXPOSURE] = 100
        if with_analogue_gain:
            self.ctrl_meta[v4l2.V4L2_CID_ANALOGUE_GAIN] = (0, 480, 1, 0)
            self.ctrl_values[v4l2.V4L2_CID_ANALOGUE_GAIN] = 0

        self.timeperframe = (1, 30)      # 30 fps
        self.streaming = False
        self.buffers: list[bytearray] = []
        self.queued: deque[int] = deque()
        self.frame_counter = 0
        self.s_ctrl_log: list[tuple[int, int]] = []
        self.streamon_calls = 0
        self.streamoff_calls = 0
        self.reqbufs_free_calls = 0

    # -- seam methods -------------------------------------------------

    @property
    def sizeimage(self) -> int:
        return self.width * self.height

    def open(self, path: str) -> int:
        if self.fail_open:
            raise OSError(errno.ENOENT,
                          f"No such file or directory: {path}")
        self.open_count += 1
        return 42

    def close(self, fd: int) -> None:
        self.close_count += 1

    def mmap(self, fd: int, length: int, offset: int):
        return self.buffers[offset // max(self.sizeimage, 1)]

    def munmap(self, buf) -> None:
        pass

    def poll(self, fd: int, timeout_s: float) -> bool:
        time.sleep(min(self.frame_interval_s, timeout_s))
        return self.streaming and bool(self.queued)

    def ioctl(self, fd: int, request: int, arg) -> int:
        if request == v4l2.VIDIOC_QUERYCAP:
            arg.driver = b"mxc-isi-cap"
            arg.card = b"Alvium 1800 C-158m"
            arg.bus_info = b"platform:32e00000.isi.0"
            arg.version = (5 << 16) | (15 << 8)
            arg.capabilities = (v4l2.V4L2_CAP_VIDEO_CAPTURE
                                | v4l2.V4L2_CAP_STREAMING
                                | v4l2.V4L2_CAP_DEVICE_CAPS)
            arg.device_caps = (v4l2.V4L2_CAP_VIDEO_CAPTURE
                               | v4l2.V4L2_CAP_STREAMING)
            return 0
        if request == v4l2.VIDIOC_ENUM_FMT:
            if arg.index >= len(self.formats):
                raise OSError(errno.EINVAL, "EINVAL")
            arg.pixelformat = self.formats[arg.index]
            arg.description = b"8-bit Greyscale"
            return 0
        if request == v4l2.VIDIOC_G_FMT:
            pix = arg.fmt.pix
            pix.width = self.width
            pix.height = self.height
            pix.pixelformat = self.pixelformat
            pix.field = v4l2.V4L2_FIELD_NONE
            pix.bytesperline = self.width
            pix.sizeimage = self.sizeimage
            return 0
        if request == v4l2.VIDIOC_S_FMT:
            pix = arg.fmt.pix
            if pix.pixelformat not in self.formats:
                raise OSError(errno.EINVAL, "EINVAL")
            self.width = int(pix.width)
            self.height = int(pix.height)
            self.pixelformat = int(pix.pixelformat)
            pix.bytesperline = self.width
            pix.sizeimage = self.sizeimage
            return 0
        if request == v4l2.VIDIOC_QUERYCTRL:
            meta = self.ctrl_meta.get(arg.id)
            if meta is None:
                raise OSError(errno.EINVAL, "EINVAL")
            arg.type = v4l2.V4L2_CTRL_TYPE_INTEGER
            arg.name = b"fake-ctrl"
            arg.minimum, arg.maximum, arg.step, arg.default_value = meta
            arg.flags = 0
            return 0
        if request == v4l2.VIDIOC_G_CTRL:
            if arg.id not in self.ctrl_values:
                raise OSError(errno.EINVAL, "EINVAL")
            arg.value = self.ctrl_values[arg.id]
            return 0
        if request == v4l2.VIDIOC_S_CTRL:
            meta = self.ctrl_meta.get(arg.id)
            if meta is None:
                raise OSError(errno.EINVAL, "EINVAL")
            lo, hi, _step, _dflt = meta
            if not lo <= arg.value <= hi:
                raise OSError(errno.ERANGE, "ERANGE")
            self.ctrl_values[arg.id] = int(arg.value)
            self.s_ctrl_log.append((int(arg.id), int(arg.value)))
            return 0
        if request == v4l2.VIDIOC_G_PARM:
            cap = arg.parm.capture
            cap.capability = v4l2.V4L2_CAP_TIMEPERFRAME
            cap.timeperframe.numerator = self.timeperframe[0]
            cap.timeperframe.denominator = self.timeperframe[1]
            return 0
        if request == v4l2.VIDIOC_S_PARM:
            tpf = arg.parm.capture.timeperframe
            if tpf.denominator:
                self.timeperframe = (int(tpf.numerator),
                                     int(tpf.denominator))
            arg.parm.capture.capability = v4l2.V4L2_CAP_TIMEPERFRAME
            return 0
        if request == v4l2.VIDIOC_REQBUFS:
            if arg.count == 0:
                self.buffers = []
                self.queued.clear()
                self.reqbufs_free_calls += 1
                return 0
            n = min(int(arg.count), 4)
            arg.count = n
            self.buffers = [bytearray(self.sizeimage) for _ in range(n)]
            self.queued.clear()
            return 0
        if request == v4l2.VIDIOC_QUERYBUF:
            arg.length = self.sizeimage
            arg.m.offset = int(arg.index) * self.sizeimage
            return 0
        if request == v4l2.VIDIOC_QBUF:
            self.queued.append(int(arg.index))
            return 0
        if request == v4l2.VIDIOC_DQBUF:
            if not self.streaming or not self.queued:
                raise OSError(errno.EAGAIN, "EAGAIN")
            idx = self.queued.popleft()
            self.frame_counter += 1
            self.buffers[idx][:] = (
                bytes([self.frame_counter % 256]) * self.sizeimage)
            arg.index = idx
            arg.bytesused = self.sizeimage
            arg.sequence = self.frame_counter
            now = time.time()
            arg.timestamp.tv_sec = int(now)
            arg.timestamp.tv_usec = int((now % 1.0) * 1_000_000)
            return 0
        if request == v4l2.VIDIOC_STREAMON:
            self.streaming = True
            self.streamon_calls += 1
            return 0
        if request == v4l2.VIDIOC_STREAMOFF:
            self.streaming = False
            self.streamoff_calls += 1
            self.queued.clear()
            return 0
        raise OSError(errno.ENOTTY, f"Unhandled ioctl 0x{request:08x}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_io() -> FakeV4l2Io:
    return FakeV4l2Io()


@pytest.fixture
async def cam(fake_io):
    backend = V4l2CameraBackend(device_path="/dev/video0", io=fake_io)
    await backend.connect()
    yield backend
    await backend.disconnect()


# ---------------------------------------------------------------------------
# _v4l2 ABI layer
# ---------------------------------------------------------------------------

_IS_64BIT = (ctypes.sizeof(ctypes.c_void_p) == 8
             and ctypes.sizeof(ctypes.c_long) == 8)


@pytest.mark.skipif(not _IS_64BIT, reason="layout targets 64-bit Linux")
def test_struct_sizes_match_64bit_kernel():
    assert ctypes.sizeof(v4l2.v4l2_capability) == 104
    assert ctypes.sizeof(v4l2.v4l2_pix_format) == 48
    assert ctypes.sizeof(v4l2.v4l2_format) == 208
    assert ctypes.sizeof(v4l2.v4l2_fmtdesc) == 64
    assert ctypes.sizeof(v4l2.v4l2_requestbuffers) == 20
    assert ctypes.sizeof(v4l2.v4l2_buffer) == 88
    assert ctypes.sizeof(v4l2.v4l2_streamparm) == 204
    assert ctypes.sizeof(v4l2.v4l2_queryctrl) == 68
    assert ctypes.sizeof(v4l2.v4l2_control) == 8
    # The v4l2_buffer hot spots: timeval alignment + pointer union.
    assert v4l2.v4l2_buffer.timestamp.offset == 24
    assert v4l2.v4l2_buffer.m.offset == 64


@pytest.mark.skipif(not _IS_64BIT, reason="codes embed 64-bit struct sizes")
def test_ioctl_codes_match_64bit_kernel():
    assert v4l2.VIDIOC_QUERYCAP == 0x80685600
    assert v4l2.VIDIOC_ENUM_FMT == 0xC0405602
    assert v4l2.VIDIOC_G_FMT == 0xC0D05604
    assert v4l2.VIDIOC_S_FMT == 0xC0D05605
    assert v4l2.VIDIOC_REQBUFS == 0xC0145608
    assert v4l2.VIDIOC_QUERYBUF == 0xC0585609
    assert v4l2.VIDIOC_QBUF == 0xC058560F
    assert v4l2.VIDIOC_DQBUF == 0xC0585611
    assert v4l2.VIDIOC_STREAMON == 0x40045612
    assert v4l2.VIDIOC_STREAMOFF == 0x40045613
    assert v4l2.VIDIOC_G_PARM == 0xC0CC5615
    assert v4l2.VIDIOC_S_PARM == 0xC0CC5616
    assert v4l2.VIDIOC_G_CTRL == 0xC008561B
    assert v4l2.VIDIOC_S_CTRL == 0xC008561C
    assert v4l2.VIDIOC_QUERYCTRL == 0xC0445624


def test_fourcc_helpers_and_pixel_format_map():
    assert v4l2.V4L2_PIX_FMT_GREY == 0x59455247
    assert v4l2.fourcc_to_str(v4l2.V4L2_PIX_FMT_GREY) == "GREY"
    assert v4l2.PIXEL_FORMAT_MAP[v4l2.V4L2_PIX_FMT_GREY] == "mono8"
    assert v4l2.PIXEL_FORMAT_MAP[v4l2.V4L2_PIX_FMT_Y10] == "mono10"
    assert v4l2.PIXEL_FORMAT_MAP_INV["mono8"] == v4l2.V4L2_PIX_FMT_GREY
    assert v4l2.V4L2_CID_EXPOSURE_ABSOLUTE == 0x009A0902
    assert v4l2.V4L2_CID_ANALOGUE_GAIN == 0x009E0903


# ---------------------------------------------------------------------------
# Connect / device info / is_connected
# ---------------------------------------------------------------------------

async def test_connect_returns_device_info(cam):
    info = cam.device_info()
    assert info.model == "Alvium 1800 C-158m"
    assert info.serial == "platform:32e00000.isi.0"
    assert info.firmware == "mxc-isi-cap"
    assert info.vendor == "AlliedVision/V4L2"


async def test_is_connected_lifecycle(fake_io):
    backend = V4l2CameraBackend(io=fake_io)
    assert backend.is_connected is False
    await backend.connect()
    assert backend.is_connected is True
    await backend.disconnect()
    assert backend.is_connected is False


async def test_connect_failure_surfaces_camera_error():
    backend = V4l2CameraBackend(io=FakeV4l2Io(fail_open=True))
    with pytest.raises(CameraDisconnectedError):
        await backend.connect()
    assert backend.is_connected is False


async def test_device_info_requires_connection(fake_io):
    backend = V4l2CameraBackend(io=fake_io)
    with pytest.raises(CameraDisconnectedError):
        backend.device_info()


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

async def test_capture_returns_mono8_frame(cam, fake_io):
    frame = await cam.capture()
    assert frame.pixel_format == "mono8"
    assert frame.array.shape == (fake_io.SENSOR_H, fake_io.SENSOR_W)
    assert frame.array.dtype == np.uint8
    assert frame.meta.width == fake_io.SENSOR_W
    assert frame.meta.height == fake_io.SENSOR_H
    assert frame.meta.timestamp_us > 0


async def test_capture_meta_carries_cached_controls(cam):
    frame = await cam.capture()
    # Exposure seeded at connect: driver 50 × 100 µs = 5000 µs.
    assert frame.meta.exposure_us == 5000.0
    assert frame.meta.gain_db == 0.0
    assert frame.meta.temperature_c is None


# ---------------------------------------------------------------------------
# Exposure — µs ↔ 100 µs driver-unit conversion
# ---------------------------------------------------------------------------

async def test_exposure_set_converts_us_to_driver_units(cam, fake_io):
    info = await cam.set_exposure(time_us=5000)
    assert fake_io.ctrl_values[v4l2.V4L2_CID_EXPOSURE_ABSOLUTE] == 50
    assert info.time_us == 5000.0
    assert info.range.min == 100.0        # driver min 1 × 100 µs
    assert info.range.max == 1_000_000.0  # driver max 10000 × 100 µs


async def test_exposure_get_converts_driver_units_to_us(cam, fake_io):
    fake_io.ctrl_values[v4l2.V4L2_CID_EXPOSURE_ABSOLUTE] = 123
    info = await cam.get_exposure()
    assert info.time_us == 12_300.0


async def test_exposure_out_of_range_raises(cam):
    with pytest.raises(FeatureOutOfRangeError):
        await cam.set_exposure(time_us=2_000_000)  # > 10000 × 100 µs
    with pytest.raises(FeatureOutOfRangeError):
        await cam.set_exposure(time_us=50)         # < 1 × 100 µs


async def test_exposure_raw_fallback_when_absolute_absent():
    fake_io = FakeV4l2Io(with_exposure_absolute=False,
                         with_raw_exposure=True)
    backend = V4l2CameraBackend(io=fake_io)
    await backend.connect()
    try:
        info = await backend.set_exposure(time_us=250)
        # Raw fallback: driver units pass through 1:1 (no ×100 scale).
        assert fake_io.ctrl_values[v4l2.V4L2_CID_EXPOSURE] == 250
        assert info.time_us == 250.0
        assert info.range.max == 65_535.0
    finally:
        await backend.disconnect()


# ---------------------------------------------------------------------------
# Gain
# ---------------------------------------------------------------------------

async def test_gain_set_get_roundtrip(cam, fake_io):
    info = await cam.set_gain(value_db=120)
    assert fake_io.ctrl_values[v4l2.V4L2_CID_ANALOGUE_GAIN] == 120
    assert info.value_db == 120.0
    fake_io.ctrl_values[v4l2.V4L2_CID_ANALOGUE_GAIN] = 240
    info = await cam.get_gain()
    assert info.value_db == 240.0
    assert info.range.min == 0.0 and info.range.max == 480.0


async def test_gain_out_of_range_raises(cam):
    with pytest.raises(FeatureOutOfRangeError):
        await cam.set_gain(value_db=481)


# ---------------------------------------------------------------------------
# Pixel format
# ---------------------------------------------------------------------------

async def test_pixel_format_get_maps_grey_to_mono8(cam):
    info = await cam.get_pixel_format()
    assert info.format == "mono8"
    assert info.available == ["mono8"]


async def test_pixel_format_set_roundtrip_and_rejects_unknown(cam, fake_io):
    info = await cam.set_pixel_format(format="mono8")
    assert info.format == "mono8"
    assert fake_io.pixelformat == v4l2.V4L2_PIX_FMT_GREY
    with pytest.raises(FeatureOutOfRangeError):
        await cam.set_pixel_format(format="rgb8")
    with pytest.raises(FeatureOutOfRangeError):
        await cam.set_pixel_format(format="mono10")  # not enumerated


# ---------------------------------------------------------------------------
# Frame rate
# ---------------------------------------------------------------------------

async def test_frame_rate_set_get_via_parm(cam, fake_io):
    info = await cam.set_frame_rate(enable=True, value=15.0)
    assert info.enable is True
    assert abs(info.value - 15.0) < 0.01
    assert fake_io.timeperframe == (1000, 15_000)
    fake_io.timeperframe = (1, 60)  # driver changed behind our back
    info = await cam.get_frame_rate()
    assert abs(info.value - 60.0) < 0.01


# ---------------------------------------------------------------------------
# Unsupported features + capabilities
# ---------------------------------------------------------------------------

async def test_unsupported_features_raise(cam):
    with pytest.raises(FeatureNotSupportedError):
        await cam.set_roi(width=640, height=480)
    with pytest.raises(FeatureNotSupportedError):
        await cam.get_roi()
    with pytest.raises(FeatureNotSupportedError):
        await cam.set_trigger(mode="software")
    with pytest.raises(FeatureNotSupportedError):
        await cam.get_trigger()
    with pytest.raises(FeatureNotSupportedError):
        await cam.get_temperature()
    with pytest.raises(FeatureNotSupportedError):
        await cam.load_user_set(slot="UserSet1")


async def test_capabilities_reflect_probes(cam):
    caps = cam.capabilities()
    assert caps[Feature.EXPOSURE].supported is True
    assert caps[Feature.EXPOSURE].range.min == 100.0
    assert caps[Feature.EXPOSURE].range.max == 1_000_000.0
    assert caps[Feature.GAIN].supported is True
    assert caps[Feature.GAIN].range.max == 480.0
    assert caps[Feature.PIXEL_FORMAT].supported is True
    assert "mono8" in caps[Feature.PIXEL_FORMAT].available_values
    assert caps[Feature.FRAME_RATE].supported is True
    assert caps[Feature.TRIGGER].supported is False
    assert caps[Feature.ROI].supported is False
    assert caps[Feature.TEMPERATURE].supported is False
    assert caps[Feature.USER_SET].supported is False


async def test_capabilities_mark_gain_unsupported_when_ctrl_absent():
    fake_io = FakeV4l2Io(with_analogue_gain=False)
    backend = V4l2CameraBackend(io=fake_io)
    await backend.connect()
    try:
        caps = backend.capabilities()
        assert caps[Feature.GAIN].supported is False
        with pytest.raises(FeatureNotSupportedError):
            await backend.get_gain()
    finally:
        await backend.disconnect()


# ---------------------------------------------------------------------------
# Streaming + status + disconnect
# ---------------------------------------------------------------------------

async def test_stream_yields_frames_then_stops_cleanly(cam, fake_io):
    frames = []
    async for frame in cam.stream(fps=500.0):
        frames.append(frame)
        if len(frames) >= 3:
            break
    assert len(frames) >= 3
    assert all(f.array.shape == (fake_io.SENSOR_H, fake_io.SENSOR_W)
               for f in frames)
    assert all(f.pixel_format == "mono8" for f in frames)
    # Producer thread stays warm until disconnect tears it down.
    await cam.disconnect()
    assert fake_io.streaming is False
    assert fake_io.streamoff_calls >= 1
    assert fake_io.reqbufs_free_calls >= 1


async def test_stream_uses_mmap_reqbufs_machinery(cam, fake_io):
    frame = await cam.capture()
    assert frame.array.shape == (fake_io.SENSOR_H, fake_io.SENSOR_W)
    assert fake_io.streamon_calls == 1
    assert len(fake_io.buffers) == 4          # REQBUFS(MMAP, 4)
    # Synthetic frames are constant-valued per frame counter.
    assert len(np.unique(frame.array)) == 1


async def test_get_status_connected(cam):
    status = await cam.get_status()
    assert status.connected is True
    assert status.device.model == "Alvium 1800 C-158m"
    assert status.current_pixel_format == "mono8"
    assert status.current_exposure_us == 5000.0
    assert status.current_gain_db == 0.0
    assert status.current_trigger_mode == "freerun"
    assert status.current_roi == {"width": 1456, "height": 1088,
                                  "offset_x": 0, "offset_y": 0}


async def test_get_status_disconnected(fake_io):
    backend = V4l2CameraBackend(io=fake_io)
    status = await backend.get_status()
    assert status.connected is False
    assert status.device is None


async def test_disconnect_is_idempotent(fake_io):
    backend = V4l2CameraBackend(io=fake_io)
    await backend.disconnect()               # never connected — no-op
    assert fake_io.close_count == 0
    await backend.connect()
    await backend.capture()                  # spin up the stream thread
    await backend.disconnect()
    await backend.disconnect()               # second call must be safe
    assert fake_io.close_count == 1
    assert backend.is_connected is False
    with pytest.raises(CameraDisconnectedError):
        await backend.capture()
