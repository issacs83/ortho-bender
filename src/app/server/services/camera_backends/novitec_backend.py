"""
novitec_backend.py — CameraBackend for NOVITEC u-Nova2 USB3 Vision cameras.

Communicates directly via libusb + GenCP/U3V protocol (no Aravis dependency).
The NOVITEC u-Nova2 series uses non-standard USB descriptors (bDeviceClass=0x00,
single vendor-specific interface) but speaks standard GenCP register protocol
and U3V bulk streaming on EP 0x82.

Hardware tested: NOVITEC u-Nova2-23C (VID=0x2b00, PID=0xf202, 1920×1200 color)

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import struct
import time
from collections.abc import AsyncIterator
from typing import Optional

import cv2
import numpy as np

from . import (
    CameraBackend,
    CameraDisconnectedError,
    CameraError,
    CameraStatus,
    CameraTimeoutError,
    CapturedFrame,
    DeviceInfo,
    ExposureInfo,
    Feature,
    FeatureCapability,
    FeatureNotSupportedError,
    FeatureOutOfRangeError,
    FrameMeta,
    FrameRateInfo,
    GainInfo,
    NumericRange,
    PixelFormatInfo,
    RoiInfo,
    TriggerInfo,
    UserSetInfo,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# NOVITEC USB IDs
# ---------------------------------------------------------------------------
NOVITEC_VID = 0x2B00
NOVITEC_PID_U_NOVA2_23C = 0xF202

# ---------------------------------------------------------------------------
# GenCP command codes
# ---------------------------------------------------------------------------
GENCP_MAGIC = 0x43563355       # 'U3VC' little-endian
READMEM_CMD = 0x0800
READMEM_ACK = 0x0801
WRITEMEM_CMD = 0x0802
WRITEMEM_ACK = 0x0803

# ---------------------------------------------------------------------------
# USB endpoint addresses (NOVITEC single-interface layout)
# ---------------------------------------------------------------------------
EP_CTRL_OUT = 0x01
EP_CTRL_IN  = 0x81
EP_STREAM_IN = 0x82

# ---------------------------------------------------------------------------
# ABRM offsets (Technology Agnostic Bootstrap Register Map)
# ---------------------------------------------------------------------------
ABRM_MANUFACTURER  = 0x0004
ABRM_MODEL         = 0x0044
ABRM_SERIAL        = 0x0144
ABRM_FW_VERSION    = 0x00C4
ABRM_SBRM_ADDR     = 0x01D8

# ---------------------------------------------------------------------------
# SBRM offsets (relative to SBRM base)
# ---------------------------------------------------------------------------
SBRM_SIRM_ADDR = 0x20

# ---------------------------------------------------------------------------
# SIRM offsets (relative to SIRM base)
# ---------------------------------------------------------------------------
SIRM_CONTROL         = 0x04
SIRM_REQ_PAYLOAD     = 0x08   # 8 bytes
SIRM_REQ_LEADER      = 0x10
SIRM_REQ_TRAILER     = 0x14
SIRM_TRANSFER1       = 0x2C
SIRM_TRANSFER2       = 0x30

# ---------------------------------------------------------------------------
# Camera register addresses (from GenICam XML: NOVITEC_U-NOVA2.xml)
# All registers are 4 bytes, little-endian unless noted.
# ---------------------------------------------------------------------------
REG_WIDTH         = 0x50000120
REG_HEIGHT        = 0x50000124
REG_OFFSET_X      = 0x50000128
REG_OFFSET_Y      = 0x5000012C
REG_PIXEL_FORMAT  = 0x50000130
REG_EXPOSURE_TIME = 0x50000134
REG_EXPOSURE_MIN  = 0x50000138
REG_EXPOSURE_MAX  = 0x5000013C
REG_TRIGGER_MODE  = 0x50000140
REG_TRIGGER_ACTIVATION = 0x50000144
REG_FRAME_RATE    = 0x50000148   # milliHz (value × 1000)
REG_FRAME_RATE_MIN = 0x5000014C
REG_FRAME_RATE_MAX = 0x50000150
REG_ACQ_START     = 0x50000154   # write 1 to start
REG_ACQ_STOP      = 0x50000158   # write 0 to stop
REG_GAIN          = 0x5000015C   # centi-dB (value × 100)
REG_TRIGGER_SW    = 0x50000110   # write 1 for software trigger
REG_WIDTH_MAX     = 0x500001C0
REG_HEIGHT_MAX    = 0x500001C4
REG_SENSOR_WIDTH  = 0x500001C8
REG_SENSOR_HEIGHT = 0x500001CC
REG_WIDTH_MIN     = 0x500001D8
REG_HEIGHT_MIN    = 0x500001DC
REG_REVERSE_X     = 0x500001D0
REG_REVERSE_Y     = 0x500001D4
REG_AE_SHUTTER_EN = 0x50000184
REG_AE_SHUTTER_MIN = 0x50000188
REG_AE_SHUTTER_MAX = 0x5000018C
REG_AE_GAIN_EN    = 0x50000190
REG_AE_GAIN_MIN   = 0x50000194
REG_AE_GAIN_MAX   = 0x50000198
REG_EXPOSURE_LEVEL = 0x5000019C
REG_TRIGGER_SOURCE = 0x50000144
REG_TRIGGER_DEBOUNCE = 0x50000114
REG_TRIGGER_RECOVERY = 0x50000118
REG_USER_SET_SELECTOR = 0x500001F0
REG_USER_SET_LOAD  = 0x500001F4
REG_USER_SET_SAVE  = 0x500001F8
REG_USER_SET_DEFAULT = 0x500001FC

# Pixel format GenICam PFNC codes
PFNC_MONO8     = 0x01080001
PFNC_BAYER_GR8 = 0x01080009
PFNC_BAYER_RG8 = 0x01080008
PFNC_BAYER_GB8 = 0x01080010
PFNC_BAYER_BG8 = 0x0108000B

PFNC_TO_STR = {
    PFNC_MONO8:     "mono8",
    PFNC_BAYER_GR8: "bayergr8",
    PFNC_BAYER_RG8: "bayerrg8",
    PFNC_BAYER_GB8: "bayergb8",
    PFNC_BAYER_BG8: "bayerbg8",
}
STR_TO_PFNC = {v: k for k, v in PFNC_TO_STR.items()}

BAYER_CV_CODE = {
    PFNC_BAYER_GR8: cv2.COLOR_BAYER_GR2BGR,
    PFNC_BAYER_RG8: cv2.COLOR_BAYER_RG2BGR,
    PFNC_BAYER_GB8: cv2.COLOR_BAYER_GB2BGR,
    PFNC_BAYER_BG8: cv2.COLOR_BAYER_BG2BGR,
}

# Stream constants
LEADER_SIZE  = 52
TRAILER_SIZE = 32
USB_CHUNK    = 131072   # 128 KB — natural USB transfer boundary
READ_CHUNK   = 16384    # 16 KB per bulk read call


# ---------------------------------------------------------------------------
# libusb ctypes wrapper (minimal, no header dependency)
# ---------------------------------------------------------------------------

class _LibUSB:
    """Thin ctypes wrapper around libusb-1.0."""

    def __init__(self):
        self._lib = ctypes.CDLL("libusb-1.0.so.0")
        L = self._lib

        # Declare function signatures
        L.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        L.libusb_init.restype = ctypes.c_int
        L.libusb_exit.argtypes = [ctypes.c_void_p]
        L.libusb_open_device_with_vid_pid.argtypes = [
            ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16
        ]
        L.libusb_open_device_with_vid_pid.restype = ctypes.c_void_p
        L.libusb_close.argtypes = [ctypes.c_void_p]
        L.libusb_set_auto_detach_kernel_driver.argtypes = [
            ctypes.c_void_p, ctypes.c_int
        ]
        L.libusb_claim_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.libusb_claim_interface.restype = ctypes.c_int
        L.libusb_release_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
        L.libusb_bulk_transfer.argtypes = [
            ctypes.c_void_p, ctypes.c_uint8,
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_int,
            ctypes.POINTER(ctypes.c_int), ctypes.c_uint,
        ]
        L.libusb_bulk_transfer.restype = ctypes.c_int
        L.libusb_clear_halt.argtypes = [ctypes.c_void_p, ctypes.c_uint8]
        L.libusb_clear_halt.restype = ctypes.c_int

        self._ctx = ctypes.c_void_p()
        rc = L.libusb_init(ctypes.byref(self._ctx))
        if rc != 0:
            raise CameraError(f"libusb_init failed: {rc}")

    def open(self, vid: int, pid: int) -> ctypes.c_void_p:
        handle = self._lib.libusb_open_device_with_vid_pid(
            self._ctx, vid, pid
        )
        if not handle:
            raise CameraError(
                f"USB device {vid:04x}:{pid:04x} not found"
            )
        self._lib.libusb_set_auto_detach_kernel_driver(handle, 1)
        rc = self._lib.libusb_claim_interface(handle, 0)
        if rc != 0:
            self._lib.libusb_close(handle)
            raise CameraError(f"libusb_claim_interface failed: {rc}")
        return handle

    def close(self, handle: ctypes.c_void_p) -> None:
        self._lib.libusb_release_interface(handle, 0)
        self._lib.libusb_close(handle)

    def clear_halt(self, handle: ctypes.c_void_p, ep: int) -> None:
        self._lib.libusb_clear_halt(handle, ep)

    def bulk_write(self, handle, ep: int, data: bytes,
                   timeout_ms: int = 3000) -> int:
        buf = (ctypes.c_uint8 * len(data))(*data)
        transferred = ctypes.c_int()
        rc = self._lib.libusb_bulk_transfer(
            handle, ep, buf, len(data),
            ctypes.byref(transferred), timeout_ms,
        )
        if rc != 0:
            raise CameraError(f"bulk_write EP 0x{ep:02x} failed: {rc}")
        return transferred.value

    def bulk_read(self, handle, ep: int, size: int,
                  timeout_ms: int = 3000) -> Optional[bytes]:
        buf = (ctypes.c_uint8 * size)()
        transferred = ctypes.c_int()
        rc = self._lib.libusb_bulk_transfer(
            handle, ep, buf, size,
            ctypes.byref(transferred), timeout_ms,
        )
        if rc == 0 and transferred.value > 0:
            return bytes(buf[:transferred.value])
        if rc == 0:
            return b""  # ZLP
        if rc == -7:   # LIBUSB_ERROR_TIMEOUT
            return None
        if rc == -1:   # LIBUSB_ERROR_IO
            return None
        return None

    def shutdown(self) -> None:
        self._lib.libusb_exit(self._ctx)


# Singleton libusb context (created on first NovitecBackend instantiation)
_usb: Optional[_LibUSB] = None


def _get_usb() -> _LibUSB:
    global _usb
    if _usb is None:
        _usb = _LibUSB()
    return _usb


# ---------------------------------------------------------------------------
# NovitecBackend
# ---------------------------------------------------------------------------

class NovitecBackend(CameraBackend):
    """CameraBackend for NOVITEC u-Nova2 cameras via direct GenCP/U3V."""

    def __init__(self, vid: int = NOVITEC_VID,
                 pid: int = NOVITEC_PID_U_NOVA2_23C) -> None:
        self._vid = vid
        self._pid = pid
        self._handle: Optional[ctypes.c_void_p] = None
        self._usb: Optional[_LibUSB] = None
        self._connected = False
        self._streaming = False
        self._device: Optional[DeviceInfo] = None
        self._caps: Optional[dict[Feature, FeatureCapability]] = None
        self._frame_count = 0
        self._start_time = 0.0
        self._rid = 0
        self._sirm_addr = 0
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Cached sensor limits (populated on connect)
        self._width_max = 0
        self._height_max = 0
        self._width_min = 0
        self._height_min = 0

    # --- Helpers ---

    def _require_connected(self) -> None:
        if not self._connected:
            raise CameraDisconnectedError("Camera not connected")

    def _next_rid(self) -> int:
        self._rid = (self._rid + 1) & 0xFFFF
        return self._rid

    def _gencp_readmem(self, addr: int, count: int,
                       timeout_ms: int = 3000) -> Optional[bytes]:
        """Read `count` bytes from GenCP register address."""
        rid = self._next_rid()
        hdr = struct.pack('<IHHHH', GENCP_MAGIC, 0x4001,
                          READMEM_CMD, 12, rid)
        pay = struct.pack('<QHH', addr, 0, min(count, 1000))
        self._usb.bulk_write(self._handle, EP_CTRL_OUT, hdr + pay,
                             timeout_ms)
        resp = self._usb.bulk_read(self._handle, EP_CTRL_IN, count + 64,
                                   timeout_ms)
        if resp and len(resp) > 12:
            return resp[12:]
        return None

    def _gencp_writemem(self, addr: int, data: bytes,
                        timeout_ms: int = 3000) -> bool:
        """Write `data` to GenCP register address."""
        rid = self._next_rid()
        payload = struct.pack('<Q', addr) + data
        hdr = struct.pack('<IHHHH', GENCP_MAGIC, 0x4001,
                          WRITEMEM_CMD, len(payload), rid)
        self._usb.bulk_write(self._handle, EP_CTRL_OUT, hdr + payload,
                             timeout_ms)
        resp = self._usb.bulk_read(self._handle, EP_CTRL_IN, 64,
                                   timeout_ms)
        if resp and len(resp) >= 12:
            ack_cmd = struct.unpack_from('<H', resp, 6)[0]
            return ack_cmd == WRITEMEM_ACK
        return False

    def _read_string(self, addr: int, maxlen: int = 64) -> str:
        data = self._gencp_readmem(addr, maxlen)
        if data:
            return data.split(b'\x00')[0].decode('ascii', errors='replace')
        return ""

    def _read_u32(self, addr: int) -> int:
        data = self._gencp_readmem(addr, 4)
        if data and len(data) >= 4:
            return struct.unpack('<I', data[:4])[0]
        raise CameraTimeoutError(f"Register read failed: 0x{addr:08x}")

    def _read_u64(self, addr: int) -> int:
        data = self._gencp_readmem(addr, 8)
        if data and len(data) >= 8:
            return struct.unpack('<Q', data[:8])[0]
        raise CameraTimeoutError(f"Register read 64-bit failed: 0x{addr:08x}")

    def _write_u32(self, addr: int, val: int) -> None:
        if not self._gencp_writemem(addr, struct.pack('<I', val)):
            raise CameraError(f"Register write failed: 0x{addr:08x}")

    def _write_u64(self, addr: int, val: int) -> None:
        if not self._gencp_writemem(addr, struct.pack('<Q', val)):
            raise CameraError(f"Register write 64-bit failed: 0x{addr:08x}")

    def _run_sync(self, fn, *args):
        loop = self._loop or asyncio.get_event_loop()
        return loop.run_in_executor(None, fn, *args)

    # --- Streaming helpers ---

    def _configure_sirm(self, width: int, height: int) -> None:
        """Configure SIRM for streaming at given resolution."""
        payload_size = width * height  # 1 bpp for 8-bit formats
        self._gencp_writemem(
            self._sirm_addr + SIRM_REQ_PAYLOAD,
            struct.pack('<Q', payload_size),
        )
        self._write_u32(self._sirm_addr + SIRM_REQ_LEADER, LEADER_SIZE)
        self._write_u32(self._sirm_addr + SIRM_REQ_TRAILER, TRAILER_SIZE)
        self._write_u32(self._sirm_addr + SIRM_TRANSFER1, USB_CHUNK)
        self._write_u32(self._sirm_addr + SIRM_TRANSFER2, USB_CHUNK)

    def _start_acquisition(self) -> None:
        self._write_u32(self._sirm_addr + SIRM_CONTROL, 1)
        self._write_u32(REG_ACQ_START, 1)

    def _stop_acquisition(self) -> None:
        try:
            self._write_u32(REG_ACQ_STOP, 0)
        except CameraError:
            pass
        try:
            self._write_u32(self._sirm_addr + SIRM_CONTROL, 0)
        except CameraError:
            pass
        # Drain any remaining stream data
        for _ in range(20):
            data = self._usb.bulk_read(self._handle, EP_STREAM_IN,
                                       65536, timeout_ms=200)
            if data is None or len(data) == 0:
                break

    def _read_frame_sync(self) -> tuple[bytes, int, int, int]:
        """Read one frame from EP 0x82. Returns (raw_pixels, width, height, pfnc)."""
        width = self._read_u32(REG_WIDTH)
        height = self._read_u32(REG_HEIGHT)
        pfnc = self._read_u32(REG_PIXEL_FORMAT)
        payload_size = width * height
        total_frame = LEADER_SIZE + payload_size + TRAILER_SIZE

        frame_buf = bytearray()
        timeout_count = 0

        for _ in range(2000):
            data = self._usb.bulk_read(self._handle, EP_STREAM_IN,
                                       READ_CHUNK, timeout_ms=1000)
            if data is None:
                timeout_count += 1
                if timeout_count > 5:
                    break
                # IO error — clear halt and retry
                self._usb.clear_halt(self._handle, EP_STREAM_IN)
                continue
            if len(data) == 0:
                # ZLP — USB transfer boundary, keep reading
                continue
            frame_buf.extend(data)
            timeout_count = 0
            if len(frame_buf) >= total_frame:
                break

        if len(frame_buf) < payload_size:
            raise CameraTimeoutError(
                f"Incomplete frame: {len(frame_buf)}/{total_frame} bytes"
            )

        # Extract raw pixel data (skip leader if present)
        # The NOVITEC stream data starts with raw pixels at offset 0
        # (no standard U3V leader magic). Use the payload directly.
        return bytes(frame_buf[:payload_size]), width, height, pfnc

    def _debayer(self, raw: np.ndarray, pfnc: int) -> np.ndarray:
        """Convert Bayer raw to BGR. Returns mono unchanged."""
        if pfnc == PFNC_MONO8:
            return raw
        code = BAYER_CV_CODE.get(pfnc)
        if code is not None:
            return cv2.cvtColor(raw, code)
        return raw

    # --- CameraBackend required methods ---

    async def connect(self) -> DeviceInfo:
        if self._connected:
            return self._device

        self._loop = asyncio.get_event_loop()

        def _connect_sync():
            self._usb = _get_usb()
            self._handle = self._usb.open(self._vid, self._pid)

            # Clear halt on all endpoints
            for ep in [EP_CTRL_OUT, EP_CTRL_IN, EP_STREAM_IN]:
                self._usb.clear_halt(self._handle, ep)

            # Read device info from ABRM
            vendor = self._read_string(ABRM_MANUFACTURER)
            model = self._read_string(ABRM_MODEL)
            serial = self._read_string(ABRM_SERIAL)
            firmware = self._read_string(ABRM_FW_VERSION)

            # Resolve SBRM -> SIRM address
            sbrm_addr = self._read_u64(ABRM_SBRM_ADDR)
            self._sirm_addr = self._read_u64(sbrm_addr + SBRM_SIRM_ADDR)

            # Cache sensor limits
            self._width_max = self._read_u32(REG_WIDTH_MAX)
            self._height_max = self._read_u32(REG_HEIGHT_MAX)
            self._width_min = self._read_u32(REG_WIDTH_MIN)
            self._height_min = self._read_u32(REG_HEIGHT_MIN)

            self._device = DeviceInfo(
                model=model, serial=serial,
                firmware=firmware, vendor=vendor,
            )
            self._connected = True
            self._start_time = time.monotonic()
            self._frame_count = 0

            log.info("NOVITEC connected: %s %s (SN: %s, FW: %s)",
                     vendor, model, serial, firmware)
            log.info("Sensor: %dx%d, SIRM at 0x%x",
                     self._width_max, self._height_max, self._sirm_addr)

        await self._run_sync(_connect_sync)

        # Build capabilities cache
        self._caps = self._build_capabilities()
        return self._device

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._streaming = False

        def _disconnect_sync():
            try:
                self._stop_acquisition()
            except Exception:
                pass
            if self._handle:
                self._usb.close(self._handle)
                self._handle = None
            self._connected = False

        await self._run_sync(_disconnect_sync)
        log.info("NOVITEC disconnected")

    async def capture(self) -> CapturedFrame:
        self._require_connected()

        def _capture_sync():
            # If not already streaming, start single-shot
            was_streaming = self._streaming
            if not was_streaming:
                w = self._read_u32(REG_WIDTH)
                h = self._read_u32(REG_HEIGHT)
                self._configure_sirm(w, h)
                self._start_acquisition()
                time.sleep(0.15)  # allow first frame to arrive

            raw_bytes, w, h, pfnc = self._read_frame_sync()

            if not was_streaming:
                self._stop_acquisition()

            self._frame_count += 1
            elapsed = time.monotonic() - self._start_time
            fps = self._frame_count / elapsed if elapsed > 0 else 0.0

            raw = np.frombuffer(raw_bytes, dtype=np.uint8).reshape(h, w)
            img = self._debayer(raw, pfnc)

            exposure_us = float(self._read_u32(REG_EXPOSURE_TIME))
            gain_raw = self._read_u32(REG_GAIN)
            gain_db = gain_raw / 100.0

            meta = FrameMeta(
                timestamp_us=int(time.monotonic() * 1_000_000),
                exposure_us=exposure_us,
                gain_db=gain_db,
                temperature_c=None,
                fps_actual=round(fps, 2),
                width=w,
                height=h,
            )
            pf_str = PFNC_TO_STR.get(pfnc, f"0x{pfnc:08x}")
            return CapturedFrame(array=img, pixel_format=pf_str, meta=meta)

        return await self._run_sync(_capture_sync)

    async def stream(self, fps: float = 30.0) -> AsyncIterator[CapturedFrame]:
        self._require_connected()
        self._streaming = True

        def _setup():
            w = self._read_u32(REG_WIDTH)
            h = self._read_u32(REG_HEIGHT)
            self._configure_sirm(w, h)
            self._start_acquisition()

        await self._run_sync(_setup)

        try:
            interval = 1.0 / fps if fps > 0 else 0.033
            while self._streaming and self._connected:
                try:
                    frame = await self.capture()
                    yield frame
                except CameraTimeoutError:
                    log.debug("Stream frame timeout, retrying")
                    continue
                await asyncio.sleep(interval)
        finally:
            self._streaming = False
            await self._run_sync(self._stop_acquisition)

    def capabilities(self) -> dict[Feature, FeatureCapability]:
        self._require_connected()
        if self._caps:
            return self._caps
        self._caps = self._build_capabilities()
        return self._caps

    def _build_capabilities(self) -> dict[Feature, FeatureCapability]:
        """Query live camera for feature capabilities."""
        caps = {}

        # Exposure
        try:
            exp_min = self._read_u32(REG_EXPOSURE_MIN)
            exp_max = self._read_u32(REG_EXPOSURE_MAX)
            caps[Feature.EXPOSURE] = FeatureCapability(
                supported=True,
                range=NumericRange(float(exp_min), float(exp_max), 1.0),
                auto_available=True,
            )
        except CameraError:
            caps[Feature.EXPOSURE] = FeatureCapability(supported=False)

        # Gain (register in centi-dB)
        caps[Feature.GAIN] = FeatureCapability(
            supported=True,
            range=NumericRange(0.0, 48.0, 0.01),
            auto_available=True,
        )

        # ROI
        caps[Feature.ROI] = FeatureCapability(
            supported=True,
            range=NumericRange(
                float(self._width_min), float(self._width_max), 4.0
            ),
        )

        # Pixel format
        caps[Feature.PIXEL_FORMAT] = FeatureCapability(
            supported=True,
            available_values=list(STR_TO_PFNC.keys()),
        )

        # Frame rate (register in milliHz)
        try:
            fr_min = self._read_u32(REG_FRAME_RATE_MIN)
            fr_max = self._read_u32(REG_FRAME_RATE_MAX)
            caps[Feature.FRAME_RATE] = FeatureCapability(
                supported=True,
                range=NumericRange(fr_min / 1000.0, fr_max / 1000.0, 0.001),
            )
        except CameraError:
            caps[Feature.FRAME_RATE] = FeatureCapability(supported=False)

        # Trigger
        caps[Feature.TRIGGER] = FeatureCapability(
            supported=True,
            available_values=["freerun", "software", "hardware"],
        )

        # Temperature — not available on u-Nova2
        caps[Feature.TEMPERATURE] = FeatureCapability(supported=False)

        # UserSet
        caps[Feature.USER_SET] = FeatureCapability(
            supported=True,
            slots=["default", "user1", "user2", "user3"],
        )

        return caps

    async def get_status(self) -> CameraStatus:
        self._require_connected()

        def _status_sync():
            exposure_us = float(self._read_u32(REG_EXPOSURE_TIME))
            gain_db = self._read_u32(REG_GAIN) / 100.0
            fr_mhz = self._read_u32(REG_FRAME_RATE)
            w = self._read_u32(REG_WIDTH)
            h = self._read_u32(REG_HEIGHT)
            ox = self._read_u32(REG_OFFSET_X)
            oy = self._read_u32(REG_OFFSET_Y)
            pfnc = self._read_u32(REG_PIXEL_FORMAT)
            trig = self._read_u32(REG_TRIGGER_MODE)

            return CameraStatus(
                connected=True,
                streaming=self._streaming,
                device=self._device,
                current_exposure_us=exposure_us,
                current_gain_db=gain_db,
                current_temperature_c=None,
                current_fps=fr_mhz / 1000.0,
                current_pixel_format=PFNC_TO_STR.get(pfnc, f"0x{pfnc:08x}"),
                current_roi={"width": w, "height": h,
                             "offset_x": ox, "offset_y": oy},
                current_trigger_mode="freerun" if trig == 0 else "hardware",
            )

        return await self._run_sync(_status_sync)

    def device_info(self) -> DeviceInfo:
        self._require_connected()
        return self._device

    @property
    def is_connected(self) -> bool:
        return self._connected

    # --- Optional feature methods ---

    async def set_exposure(self, *, auto: bool = False,
                           time_us: Optional[float] = None) -> ExposureInfo:
        self._require_connected()

        def _set():
            self._write_u32(REG_AE_SHUTTER_EN, 1 if auto else 0)
            if time_us is not None and not auto:
                exp_min = self._read_u32(REG_EXPOSURE_MIN)
                exp_max = self._read_u32(REG_EXPOSURE_MAX)
                val = int(max(exp_min, min(exp_max, time_us)))
                self._write_u32(REG_EXPOSURE_TIME, val)

        await self._run_sync(_set)
        return await self.get_exposure()

    async def get_exposure(self) -> ExposureInfo:
        self._require_connected()

        def _get():
            time_us = float(self._read_u32(REG_EXPOSURE_TIME))
            exp_min = self._read_u32(REG_EXPOSURE_MIN)
            exp_max = self._read_u32(REG_EXPOSURE_MAX)
            ae_en = self._read_u32(REG_AE_SHUTTER_EN)
            return ExposureInfo(
                auto=ae_en != 0,
                time_us=time_us,
                range=NumericRange(float(exp_min), float(exp_max), 1.0),
                auto_available=True,
            )

        return await self._run_sync(_get)

    async def set_gain(self, *, auto: bool = False,
                       value_db: Optional[float] = None) -> GainInfo:
        self._require_connected()

        def _set():
            self._write_u32(REG_AE_GAIN_EN, 1 if auto else 0)
            if value_db is not None and not auto:
                val = int(max(0, min(4800, value_db * 100)))
                self._write_u32(REG_GAIN, val)

        await self._run_sync(_set)
        return await self.get_gain()

    async def get_gain(self) -> GainInfo:
        self._require_connected()

        def _get():
            raw = self._read_u32(REG_GAIN)
            ae_en = self._read_u32(REG_AE_GAIN_EN)
            return GainInfo(
                auto=ae_en != 0,
                value_db=raw / 100.0,
                range=NumericRange(0.0, 48.0, 0.01),
                auto_available=True,
            )

        return await self._run_sync(_get)

    async def set_roi(self, *, width: int, height: int,
                      offset_x: int = 0, offset_y: int = 0) -> RoiInfo:
        self._require_connected()

        def _set():
            # Clamp to limits
            w = max(self._width_min, min(self._width_max, width))
            h = max(self._height_min, min(self._height_max, height))
            ox = max(0, min(self._width_max - w, offset_x))
            oy = max(0, min(self._height_max - h, offset_y))

            # Must stop acquisition to change ROI
            was_streaming = self._streaming
            if was_streaming:
                self._stop_acquisition()
                time.sleep(0.05)

            self._write_u32(REG_WIDTH, w)
            self._write_u32(REG_HEIGHT, h)
            self._write_u32(REG_OFFSET_X, ox)
            self._write_u32(REG_OFFSET_Y, oy)

            if was_streaming:
                self._configure_sirm(w, h)
                self._start_acquisition()

        await self._run_sync(_set)
        info = await self.get_roi()
        info.invalidated = [Feature.FRAME_RATE]
        return info

    async def get_roi(self) -> RoiInfo:
        self._require_connected()

        def _get():
            w = self._read_u32(REG_WIDTH)
            h = self._read_u32(REG_HEIGHT)
            ox = self._read_u32(REG_OFFSET_X)
            oy = self._read_u32(REG_OFFSET_Y)
            return RoiInfo(
                width=w, height=h, offset_x=ox, offset_y=oy,
                width_range=NumericRange(
                    float(self._width_min), float(self._width_max), 4.0
                ),
                height_range=NumericRange(
                    float(self._height_min), float(self._height_max), 2.0
                ),
                offset_x_range=NumericRange(
                    0.0, float(self._width_max - w), 4.0
                ),
                offset_y_range=NumericRange(
                    0.0, float(self._height_max - h), 2.0
                ),
            )

        return await self._run_sync(_get)

    async def center_roi(self) -> RoiInfo:
        self._require_connected()
        roi = await self.get_roi()
        cx = (self._width_max - roi.width) // 2
        cy = (self._height_max - roi.height) // 2
        return await self.set_roi(
            width=roi.width, height=roi.height,
            offset_x=cx, offset_y=cy,
        )

    async def set_pixel_format(self, *, format: str) -> PixelFormatInfo:
        self._require_connected()
        pfnc = STR_TO_PFNC.get(format.lower())
        if pfnc is None:
            raise FeatureOutOfRangeError(
                Feature.PIXEL_FORMAT, 0,
                NumericRange(0, 0),
            )

        def _set():
            was_streaming = self._streaming
            if was_streaming:
                self._stop_acquisition()
                time.sleep(0.05)
            self._write_u32(REG_PIXEL_FORMAT, pfnc)
            if was_streaming:
                w = self._read_u32(REG_WIDTH)
                h = self._read_u32(REG_HEIGHT)
                self._configure_sirm(w, h)
                self._start_acquisition()

        await self._run_sync(_set)
        info = await self.get_pixel_format()
        info.invalidated = [Feature.FRAME_RATE]
        return info

    async def get_pixel_format(self) -> PixelFormatInfo:
        self._require_connected()

        def _get():
            pfnc = self._read_u32(REG_PIXEL_FORMAT)
            return PixelFormatInfo(
                format=PFNC_TO_STR.get(pfnc, f"0x{pfnc:08x}"),
                available=list(STR_TO_PFNC.keys()),
            )

        return await self._run_sync(_get)

    async def set_frame_rate(self, *, enable: bool,
                             value: Optional[float] = None) -> FrameRateInfo:
        self._require_connected()

        def _set():
            if value is not None and enable:
                mhz = int(value * 1000)
                fr_min = self._read_u32(REG_FRAME_RATE_MIN)
                fr_max = self._read_u32(REG_FRAME_RATE_MAX)
                mhz = max(fr_min, min(fr_max, mhz))
                self._write_u32(REG_FRAME_RATE, mhz)

        await self._run_sync(_set)
        return await self.get_frame_rate()

    async def get_frame_rate(self) -> FrameRateInfo:
        self._require_connected()

        def _get():
            mhz = self._read_u32(REG_FRAME_RATE)
            fr_min = self._read_u32(REG_FRAME_RATE_MIN)
            fr_max = self._read_u32(REG_FRAME_RATE_MAX)
            return FrameRateInfo(
                enable=True,
                value=mhz / 1000.0,
                range=NumericRange(fr_min / 1000.0, fr_max / 1000.0, 0.001),
            )

        return await self._run_sync(_get)

    async def set_trigger(self, *, mode: str,
                          source: Optional[str] = None) -> TriggerInfo:
        self._require_connected()

        def _set():
            if mode == "freerun":
                self._write_u32(REG_TRIGGER_MODE, 0)
            elif mode == "software":
                self._write_u32(REG_TRIGGER_MODE, 1)
            elif mode == "hardware":
                self._write_u32(REG_TRIGGER_MODE, 1)

        await self._run_sync(_set)
        info = await self.get_trigger()
        info.invalidated = [Feature.FRAME_RATE]
        return info

    async def get_trigger(self) -> TriggerInfo:
        self._require_connected()

        def _get():
            mode_val = self._read_u32(REG_TRIGGER_MODE)
            mode_str = "freerun" if mode_val == 0 else "hardware"
            return TriggerInfo(
                mode=mode_str,
                source=None,
                available_modes=["freerun", "software", "hardware"],
                available_sources=["software", "line1"],
            )

        return await self._run_sync(_get)

    async def fire_trigger(self) -> None:
        self._require_connected()
        await self._run_sync(self._write_u32, REG_TRIGGER_SW, 1)

    async def load_user_set(self, *, slot: str) -> None:
        self._require_connected()
        slot_map = {"default": 0, "user1": 1, "user2": 2, "user3": 3}
        idx = slot_map.get(slot)
        if idx is None:
            raise FeatureNotSupportedError(Feature.USER_SET)

        def _load():
            self._write_u32(REG_USER_SET_SELECTOR, idx)
            self._write_u32(REG_USER_SET_LOAD, 1)

        await self._run_sync(_load)

    async def save_user_set(self, *, slot: str) -> None:
        self._require_connected()
        slot_map = {"user1": 1, "user2": 2, "user3": 3}
        idx = slot_map.get(slot)
        if idx is None:
            raise FeatureNotSupportedError(Feature.USER_SET)

        def _save():
            self._write_u32(REG_USER_SET_SELECTOR, idx)
            self._write_u32(REG_USER_SET_SAVE, 1)

        await self._run_sync(_save)

    async def set_default_user_set(self, *, slot: str) -> None:
        self._require_connected()
        slot_map = {"default": 0, "user1": 1, "user2": 2, "user3": 3}
        idx = slot_map.get(slot)
        if idx is None:
            raise FeatureNotSupportedError(Feature.USER_SET)
        await self._run_sync(self._write_u32, REG_USER_SET_DEFAULT, idx)

    async def get_user_set_info(self) -> UserSetInfo:
        self._require_connected()

        def _get():
            sel = self._read_u32(REG_USER_SET_SELECTOR)
            default = self._read_u32(REG_USER_SET_DEFAULT)
            idx_to_name = {0: "default", 1: "user1", 2: "user2", 3: "user3"}
            return UserSetInfo(
                current_slot=idx_to_name.get(sel, f"unknown({sel})"),
                available_slots=["default", "user1", "user2", "user3"],
                default_slot=idx_to_name.get(default, f"unknown({default})"),
            )

        return await self._run_sync(_get)
