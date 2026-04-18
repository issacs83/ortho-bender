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
SIRM_REQ_PAYLOAD     = 0x08   # 8 bytes (low + high)
SIRM_REQ_LEADER      = 0x10
SIRM_REQ_TRAILER     = 0x14
# U3V SI payload transfer registers
SIRM_XFER_SIZE       = 0x20   # SI_Payload_Transfer_Size
SIRM_XFER_COUNT      = 0x24   # SI_Payload_Transfer_Count
SIRM_FINAL1          = 0x28   # SI_Payload_Final_Transfer1_Size
SIRM_FINAL2          = 0x2C   # SI_Payload_Final_Transfer2_Size

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

# NOVITEC custom packet framing constants (v4, verified on real data from
# /tmp/novitec_raw_evk.bin — produces coherent Mono8 1920x1200 frames).
#
# Each USB bulk packet of 32768 bytes carries 128 bytes of header + 32640
# bytes of 8-bit pixel payload. 32640 == 1920 * 17 (1920 u8 pixels × 17
# rows per packet). The sensor is monochrome (Mono8 only) — PFNC codes
# reported by the camera are ignored for the wire format.
#
# Packet header (128 B):
#   [0]    : sub_index (u8)  — only sub=0 carries pixel data for the frame
#   [1:8]  : magic bytes "00 f0 7f 01 4b 00 1e"
#   [8:12] : counter (u32 LE)
#
# Packet payload (32640 B): 1920 columns × 17 rows of u8 Mono8 data.
# Packets with sub_index != 0 are metadata/control frames and must be
# discarded. 71 sub=0 packets ≈ 1207 rows → crop to 1200.
NOVITEC_PKT_SIZE     = 32768
NOVITEC_HDR_SIZE     = 128
NOVITEC_PAYLOAD_SIZE = NOVITEC_PKT_SIZE - NOVITEC_HDR_SIZE  # 32640
NOVITEC_COLS         = 1920    # u8 pixels per row
NOVITEC_ROWS_PER_PKT = 17      # rows per sub=0 packet
_NOVITEC_MAGIC       = bytes.fromhex("00f07f014b001e")  # header bytes [1:8]

# Stream constants
USB_CHUNK    = 131072   # 128 KB — U3V transfer boundary

# Background reconnect poll interval (seconds)
_RECONNECT_POLL_S = 3.0


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
# NOVITEC packet framing decoder
# ---------------------------------------------------------------------------


def _novitec_decode_stream(raw: bytes, width: int, height: int) -> bytes:
    """Decode a NOVITEC USB bulk stream into 8-bit Mono8 pixel data (v4).

    Input: concatenated 32768 B packets from EP 0x82.
    Output: width*height bytes of 8-bit Mono8 pixels (monochrome sensor —
    no Bayer demosaic needed).

    Wire format (reverse-engineered and verified on real capture
    /tmp/novitec_raw_evk.bin):
        Header (128 B):
          [0]    : sub_index (u8)  — only sub=0 carries frame pixel data
          [1:8]  : magic "00 f0 7f 01 4b 00 1e"
          [8:12] : counter (u32 LE) shared by packets in the same xfer
        Payload (32640 B): 1920 columns × 17 rows of u8 Mono8 pixels.

    Non-sub-0 packets are metadata / bookkeeping and are discarded.
    We accumulate sub=0 packet payloads row-by-row until we have at
    least `height` rows, then return the top `height` rows.

    Note: the u-Nova2-23C is a monochrome sensor — Bayer demosaic must
    NOT be applied even if REG_PIXEL_FORMAT reports a Bayer PFNC code.
    """
    n_packets = len(raw) // NOVITEC_PKT_SIZE
    if n_packets == 0:
        raise CameraError("Novitec decode: no complete packets in stream")

    # Pixel data width is fixed by the wire format (1920 u8 pixels per row).
    # `width` parameter is honored only if it is smaller (ROI crop).
    wire_cols = NOVITEC_COLS
    crop_w = min(width, wire_cols)
    crop_h = height

    mv = memoryview(raw)
    rows: list[np.ndarray] = []
    row_count = 0

    for i in range(n_packets):
        off = i * NOVITEC_PKT_SIZE
        if bytes(mv[off + 1:off + 8]) != _NOVITEC_MAGIC:
            continue
        sub = mv[off]
        if sub != 0:
            continue
        payload = raw[off + NOVITEC_HDR_SIZE:off + NOVITEC_PKT_SIZE]
        if len(payload) != NOVITEC_PAYLOAD_SIZE:
            continue
        arr = np.frombuffer(payload, dtype=np.uint8).reshape(
            NOVITEC_ROWS_PER_PKT, wire_cols,
        )
        rows.append(arr)
        row_count += NOVITEC_ROWS_PER_PKT
        if row_count >= crop_h:
            break

    if not rows:
        raise CameraError("Novitec decode: no sub=0 packets in stream")

    stacked = np.vstack(rows)
    if stacked.shape[0] < crop_h:
        raise CameraError(
            f"Novitec decode: only {stacked.shape[0]} rows, need {crop_h}"
        )

    frame = stacked[:crop_h, :crop_w]
    # If the caller asked for an unusual W different from wire_cols, resize
    # horizontally; otherwise return as-is.
    if crop_w != width or crop_h != height:
        frame = cv2.resize(frame, (width, height),
                           interpolation=cv2.INTER_AREA)
    return bytes(frame.tobytes())


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
        # Background reconnect task (spawned on first connect() call)
        self._reconnect_task: Optional[asyncio.Task] = None
        self._shutdown = False

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
        xfer_count = payload_size // USB_CHUNK
        remainder = payload_size - xfer_count * USB_CHUNK

        self._write_u32(self._sirm_addr + SIRM_REQ_PAYLOAD, payload_size)
        self._write_u32(self._sirm_addr + SIRM_REQ_PAYLOAD + 4, 0)
        # Camera sends raw pixels — no U3V leader/trailer
        self._write_u32(self._sirm_addr + SIRM_REQ_LEADER, 0)
        self._write_u32(self._sirm_addr + SIRM_REQ_TRAILER, 0)
        # U3V transfer packetization
        self._write_u32(self._sirm_addr + SIRM_XFER_SIZE, USB_CHUNK)
        self._write_u32(self._sirm_addr + SIRM_XFER_COUNT, xfer_count)
        self._write_u32(self._sirm_addr + SIRM_FINAL1, remainder)
        self._write_u32(self._sirm_addr + SIRM_FINAL2, 0)

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
        """Read one frame from EP 0x82 and decode the NOVITEC packet framing.

        The NOVITEC u-Nova2 wraps each USB packet with a 128-byte custom
        header before the pixel bytes. We read enough WIRE bytes to obtain
        width*height bytes of net pixel payload, then strip headers and
        discard LEADER/TRAILER groups.

        Returns:
            (raw_pixels, width, height, pfnc) where raw_pixels has length
            width*height (8-bit pixels, ready for debayer).
        """
        width  = self._read_u32(REG_WIDTH)
        height = self._read_u32(REG_HEIGHT)
        pfnc   = self._read_u32(REG_PIXEL_FORMAT)

        frame_size = width * height                       # net pixel bytes
        # Mono8 wire format: only sub_index=0 packets carry pixel rows
        # (17 rows × 1920 cols each). In a real stream the sub=0 ratio is
        # roughly 1:4 (DATA group has subs 0/1/2/4). For a 1200-row frame
        # we need ≥71 sub=0 packets, so ~300 total packets worst case.
        need_sub0_pkts = (height + NOVITEC_ROWS_PER_PKT - 1) // NOVITEC_ROWS_PER_PKT
        max_wire_bytes = 6 * need_sub0_pkts * NOVITEC_PKT_SIZE  # ~430 pkts @1200 rows
        # Minimum wire bytes before attempting early decode (enough to
        # possibly contain one full frame's worth of sub=0 packets).
        min_decode_bytes = 4 * need_sub0_pkts * NOVITEC_PKT_SIZE  # ~285 pkts @1200

        frame_buf = bytearray()
        timeout_count = 0

        for _ in range(5000):
            data = self._usb.bulk_read(self._handle, EP_STREAM_IN,
                                       USB_CHUNK, timeout_ms=2000)
            if data is None:
                timeout_count += 1
                if timeout_count > 10:
                    break
                self._usb.clear_halt(self._handle, EP_STREAM_IN)
                continue
            if len(data) == 0:
                continue
            frame_buf.extend(data)
            timeout_count = 0
            # Attempt decode once we have enough wire data.
            if len(frame_buf) >= max_wire_bytes:
                break
            # Early-out: try to decode as soon as theoretically sufficient.
            if len(frame_buf) >= min_decode_bytes:
                try:
                    pixels = _novitec_decode_stream(bytes(frame_buf),
                                                    width, height)
                    return pixels, width, height, pfnc
                except CameraError:
                    continue

        if len(frame_buf) < min_decode_bytes:
            raise CameraTimeoutError(
                f"Incomplete frame: {len(frame_buf)}/{min_decode_bytes} "
                f"wire bytes (target {max_wire_bytes})"
            )

        # Final decode (may raise CameraError if truly insufficient).
        pixels = _novitec_decode_stream(bytes(frame_buf), width, height)
        return pixels, width, height, pfnc

    def _debayer(self, raw: np.ndarray, pfnc: int) -> np.ndarray:
        """Convert Bayer raw to BGR. Returns mono unchanged."""
        if pfnc == PFNC_MONO8:
            return raw
        code = BAYER_CV_CODE.get(pfnc)
        if code is not None:
            return cv2.cvtColor(raw, code)
        return raw

    # --- CameraBackend required methods ---

    def _connect_sync_attempt(self) -> bool:
        """Try to open USB + bring the camera into a known-good state.

        Returns True on success, False if the USB device is not present
        or any step of the init sequence fails. NEVER raises — callers
        can treat False as "hardware not ready, will retry later".
        """
        global _usb
        # Re-use the existing libusb context if any — creating a fresh
        # context on every attempt leaks file descriptors when the
        # camera is absent.
        if self._usb is None:
            try:
                self._usb = _get_usb()
            except Exception as exc:  # libusb_init failed
                log.warning("NOVITEC libusb_init failed: %s", exc)
                return False

        try:
            self._handle = self._usb.open(self._vid, self._pid)
        except CameraError as exc:
            # Expected when the camera is not plugged in. Log at debug
            # level after the first warning so the log does not flood.
            log.debug("NOVITEC USB open failed: %s", exc)
            self._handle = None
            return False
        except Exception as exc:
            log.warning("NOVITEC USB open unexpected error: %s", exc)
            self._handle = None
            return False

        try:
            # Clear halt on all endpoints
            for ep in [EP_CTRL_OUT, EP_CTRL_IN, EP_STREAM_IN]:
                try:
                    self._usb.clear_halt(self._handle, ep)
                except Exception:
                    pass

            # Read device info from ABRM
            vendor = self._read_string(ABRM_MANUFACTURER)
            model = self._read_string(ABRM_MODEL)
            serial = self._read_string(ABRM_SERIAL)
            firmware = self._read_string(ABRM_FW_VERSION)

            # Resolve SBRM -> SIRM address
            sbrm_addr = self._read_u64(ABRM_SBRM_ADDR)
            self._sirm_addr = self._read_u64(sbrm_addr + SBRM_SIRM_ADDR)

            # Force-stop any previous streaming session left over
            try:
                self._gencp_writemem(
                    self._sirm_addr + SIRM_CONTROL,
                    struct.pack('<I', 0),
                )
            except CameraError:
                pass
            try:
                self._gencp_writemem(REG_ACQ_STOP, struct.pack('<I', 0))
            except CameraError:
                pass
            # Drain stale stream data
            for _ in range(30):
                d = self._usb.bulk_read(self._handle, EP_STREAM_IN,
                                        65536, timeout_ms=100)
                if d is None or len(d) == 0:
                    break

            # Cache sensor limits
            self._width_max = self._read_u32(REG_WIDTH_MAX)
            self._height_max = self._read_u32(REG_HEIGHT_MAX)
            self._width_min = self._read_u32(REG_WIDTH_MIN)
            self._height_min = self._read_u32(REG_HEIGHT_MIN)

            # Ensure width/height are set to full resolution — some cameras
            # do not default to max after USB reset
            cur_w = self._read_u32(REG_WIDTH)
            cur_h = self._read_u32(REG_HEIGHT)
            if cur_w < self._width_min or cur_h < self._height_min:
                log.warning(
                    "Camera W×H=%dx%d invalid, resetting to %dx%d",
                    cur_w, cur_h,
                    self._width_max, self._height_max,
                )
                self._write_u32(REG_WIDTH, self._width_max)
                self._write_u32(REG_HEIGHT, self._height_max)

            cur_trig = self._read_u32(REG_TRIGGER_MODE)
            if cur_trig != 0:
                log.warning("Camera trigger=%d (hardware), forcing freerun",
                            cur_trig)
                self._write_u32(REG_TRIGGER_MODE, 0)

            # The u-Nova2-23C is a monochrome sensor. Force Mono8 so the
            # sensor reports a sane PFNC code; the wire format is always
            # Mono8 regardless.
            try:
                cur_pf = self._read_u32(REG_PIXEL_FORMAT)
                if cur_pf != PFNC_MONO8:
                    log.info(
                        "Camera pixel format 0x%08x → forcing Mono8",
                        cur_pf,
                    )
                    self._write_u32(REG_PIXEL_FORMAT, PFNC_MONO8)
            except CameraError:
                pass

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
            return True
        except Exception as exc:
            # Init sequence failed after open. Close the handle and
            # leave _connected=False so the reconnect loop retries.
            log.warning("NOVITEC init failed after open: %s", exc)
            try:
                if self._handle:
                    self._usb.close(self._handle)
            except Exception:
                pass
            self._handle = None
            self._connected = False
            return False

    async def connect(self) -> DeviceInfo:
        """Connect to the camera (idempotent, never raises).

        If the camera is not currently plugged in, this returns an empty
        DeviceInfo and leaves the backend in a disconnected state. A
        background task continues to poll for the camera and transitions
        the backend to connected when the hardware appears.
        """
        if self._connected and self._device is not None:
            return self._device

        self._loop = asyncio.get_running_loop()
        self._shutdown = False

        await self._run_sync(self._connect_sync_attempt)

        if self._connected:
            # Build capabilities cache when hardware is live.
            try:
                self._caps = self._build_capabilities()
            except CameraError as exc:
                log.warning("NOVITEC capability probe failed: %s", exc)
                self._caps = {}
        else:
            # Hardware absent — return a placeholder so the FastAPI
            # startup can proceed. The reconnect loop will populate the
            # real DeviceInfo once the camera is attached.
            log.warning(
                "NOVITEC camera not present at VID=%04x PID=%04x "
                "— running disconnected, will auto-reconnect when "
                "hardware appears",
                self._vid, self._pid,
            )
            self._device = DeviceInfo(
                model="", serial="", firmware="", vendor="",
            )
            self._caps = {}

        # Spawn the background reconnect task once.
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = self._loop.create_task(
                self._reconnect_loop(),
                name="novitec-reconnect",
            )

        return self._device

    async def _reconnect_loop(self) -> None:
        """Periodic USB presence check; reconnect when the camera appears."""
        log.info("NOVITEC reconnect loop started (interval=%.1fs)",
                 _RECONNECT_POLL_S)
        while not self._shutdown:
            try:
                await asyncio.sleep(_RECONNECT_POLL_S)
            except asyncio.CancelledError:
                break
            if self._shutdown:
                break
            if self._connected:
                continue
            try:
                ok = await self._run_sync(self._connect_sync_attempt)
            except Exception as exc:
                log.debug("NOVITEC reconnect attempt raised: %s", exc)
                ok = False
            if ok:
                try:
                    self._caps = self._build_capabilities()
                except CameraError as exc:
                    log.warning(
                        "NOVITEC capability probe failed: %s", exc)
                    self._caps = {}
                log.info("NOVITEC camera auto-reconnected")
        log.info("NOVITEC reconnect loop exited")

    async def disconnect(self) -> None:
        self._shutdown = True
        self._streaming = False

        # Stop background reconnect task
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reconnect_task = None

        if not self._connected:
            return

        def _disconnect_sync():
            try:
                self._stop_acquisition()
            except Exception:
                pass
            if self._handle:
                try:
                    self._usb.close(self._handle)
                except Exception:
                    pass
                self._handle = None
            self._connected = False

        await self._run_sync(_disconnect_sync)
        log.info("NOVITEC disconnected")

    def _reconnect_sync(self) -> None:
        """Re-establish USB connection after a communication failure."""
        log.warning("NOVITEC USB reconnecting...")
        # Close old handle only (keep libusb context alive — other threads
        # may still reference it)
        if self._handle:
            try:
                self._usb.close(self._handle)
            except Exception:
                pass
            self._handle = None
        self._connected = False
        self._streaming = False

        # Re-open on same libusb context (VID/PID scan finds new device#)
        time.sleep(1.0)
        self._handle = self._usb.open(self._vid, self._pid)
        for ep in [EP_CTRL_OUT, EP_CTRL_IN, EP_STREAM_IN]:
            self._usb.clear_halt(self._handle, ep)
        time.sleep(0.3)

        # Re-resolve SIRM
        sbrm_addr = self._read_u64(ABRM_SBRM_ADDR)
        self._sirm_addr = self._read_u64(sbrm_addr + SBRM_SIRM_ADDR)

        # Stop any leftover stream
        try:
            self._gencp_writemem(
                self._sirm_addr + SIRM_CONTROL,
                struct.pack('<I', 0),
            )
        except CameraError:
            pass
        for _ in range(30):
            d = self._usb.bulk_read(self._handle, EP_STREAM_IN,
                                    65536, timeout_ms=100)
            if d is None or len(d) == 0:
                break

        self._connected = True
        self._frame_count = 0
        self._start_time = time.monotonic()
        log.info("NOVITEC USB reconnected (SIRM at 0x%x)", self._sirm_addr)

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

            try:
                raw_bytes, w, h, _pfnc = self._read_frame_sync()
            except (CameraError, CameraTimeoutError):
                # Clean up on failure so next capture starts fresh
                if not was_streaming:
                    try:
                        self._stop_acquisition()
                    except CameraError:
                        pass
                for ep in [EP_CTRL_OUT, EP_CTRL_IN, EP_STREAM_IN]:
                    try:
                        self._usb.clear_halt(self._handle, ep)
                    except Exception:
                        pass
                raise

            if not was_streaming:
                self._stop_acquisition()

            self._frame_count += 1
            elapsed = time.monotonic() - self._start_time
            fps = self._frame_count / elapsed if elapsed > 0 else 0.0

            # u-Nova2-23C is a monochrome sensor; the wire format is
            # always Mono8 regardless of PFNC code. Do NOT debayer.
            img = np.frombuffer(raw_bytes, dtype=np.uint8).reshape(h, w)

            try:
                exposure_us = float(self._read_u32(REG_EXPOSURE_TIME))
                gain_raw = self._read_u32(REG_GAIN)
                gain_db = gain_raw / 100.0
            except (CameraError, CameraTimeoutError):
                exposure_us = 0.0
                gain_db = 0.0

            meta = FrameMeta(
                timestamp_us=int(time.monotonic() * 1_000_000),
                exposure_us=exposure_us,
                gain_db=gain_db,
                temperature_c=None,
                fps_actual=round(fps, 2),
                width=w,
                height=h,
            )
            return CapturedFrame(array=img, pixel_format="mono8", meta=meta)

        try:
            return await self._run_sync(_capture_sync)
        except CameraError as exc:
            # USB communication failure — mark disconnected; the background
            # reconnect loop (single source of truth) will re-establish the
            # link. Avoid racing _reconnect_sync here.
            log.warning("NOVITEC capture failed (%s: %s); marking disconnected",
                        type(exc).__name__, exc)
            if self._handle:
                try:
                    self._usb.close(self._handle)
                except Exception:
                    pass
                self._handle = None
            self._connected = False
            raise CameraDisconnectedError(
                f"NOVITEC camera disconnected: {exc}"
            ) from exc

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
        # Return cached caps if available (populated on connect). When
        # the camera is not connected, return an empty dict so status
        # endpoints can serialize without raising.
        if self._caps is not None:
            return self._caps
        if not self._connected:
            return {}
        try:
            self._caps = self._build_capabilities()
        except CameraError as exc:
            log.warning("NOVITEC capability probe failed: %s", exc)
            self._caps = {}
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
        """Return the current camera status.

        Safe to call when the camera is not connected — returns a
        CameraStatus with connected=False and the last known device
        info (empty placeholder if it has never been connected).
        """
        if not self._connected:
            return CameraStatus(
                connected=False,
                streaming=False,
                device=self._device or DeviceInfo(
                    model="", serial="", firmware="", vendor="",
                ),
                current_exposure_us=0.0,
                current_gain_db=0.0,
                current_temperature_c=None,
                current_fps=0.0,
                current_pixel_format="",
                current_roi={"width": 0, "height": 0,
                             "offset_x": 0, "offset_y": 0},
                current_trigger_mode="freerun",
            )

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

        try:
            return await self._run_sync(_status_sync)
        except CameraError as exc:
            log.warning(
                "NOVITEC get_status failed (%s) — marking disconnected, "
                "reconnect loop will retry",
                exc,
            )
            # Drop the handle so the reconnect loop re-opens cleanly.
            self._connected = False
            if self._handle is not None:
                try:
                    self._usb.close(self._handle)
                except Exception:
                    pass
                self._handle = None
            return await self.get_status()

    def device_info(self) -> DeviceInfo:
        # Safe when disconnected — returns placeholder DeviceInfo.
        return self._device or DeviceInfo(
            model="", serial="", firmware="", vendor="",
        )

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
