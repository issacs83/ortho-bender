"""
ipc_client.py — RPMsg IPC client for A53 ↔ M7 communication.

Implements the binary protocol defined in src/shared/ipc_protocol.h.
Supports mock mode for development without physical hardware.

Device node: /dev/rpmsg0  (Linux RPMsg character device)

Packet layout:
  [magic 4B][msg_type 2B][payload_len 2B][sequence 4B]
  [timestamp_us 8B][crc32 4B][payload N bytes]

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import logging
import os
import struct
import time
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol constants (must match ipc_protocol.h)
# ---------------------------------------------------------------------------

IPC_MAGIC           = 0x4F425744   # "OBWD"
IPC_PROTOCOL_VER    = 2
IPC_MAX_PAYLOAD     = 1600
IPC_HEADER_FMT      = "<IHHIQ I"   # little-endian; total = 4+2+2+4+8+4 = 24 bytes
IPC_HEADER_SIZE     = struct.calcsize(IPC_HEADER_FMT)  # 24

# Message type IDs
MSG_MOTION_EXECUTE_BCODE    = 0x0100
MSG_MOTION_JOG              = 0x0101
MSG_MOTION_HOME             = 0x0102
MSG_MOTION_STOP             = 0x0103
MSG_MOTION_ESTOP            = 0x0104
MSG_MOTION_SET_PARAM        = 0x0105
MSG_MOTION_RESET            = 0x0106
MSG_MOTION_WIRE_DETECT      = 0x0107
MSG_MOTION_SET_DRV_ENABLE   = 0x0108
MSG_DIAG_TMC_READ           = 0x0200
MSG_DIAG_TMC_WRITE          = 0x0201
MSG_DIAG_TMC_DUMP           = 0x0202
MSG_DIAG_GET_VERSION        = 0x0203
MSG_THERMAL_SET_TEMP        = 0x0280
MSG_STATUS_MOTION           = 0x0300
MSG_STATUS_TMC              = 0x0301
MSG_STATUS_ALARM            = 0x0302
MSG_STATUS_BCODE_COMPLETE   = 0x0303
MSG_STATUS_HEARTBEAT        = 0x0304
MSG_STATUS_HOMING_DONE      = 0x0305
MSG_STATUS_WIRE_DETECT      = 0x0306
MSG_STATUS_VERSION          = 0x0307


# ---------------------------------------------------------------------------
# CRC-32 (ISO 3309, same polynomial as zlib — mirrors ipc_crc32_update)
# ---------------------------------------------------------------------------

def _crc32_update(crc: int, data: bytes) -> int:
    crc = crc ^ 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xEDB88320 & (-(crc & 1) & 0xFFFFFFFF))
    return crc ^ 0xFFFFFFFF


def _compute_crc32(header_without_crc: bytes, payload: bytes) -> int:
    """Compute CRC-32 over header fields before crc32 + payload."""
    crc = _crc32_update(0, header_without_crc)
    if payload:
        crc = _crc32_update(crc, payload)
    return crc & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# IPC message dataclass
# ---------------------------------------------------------------------------

@dataclass
class IpcMessage:
    msg_type: int
    payload: bytes = b""
    sequence: int = 0
    timestamp_us: int = 0


# ---------------------------------------------------------------------------
# IPC client
# ---------------------------------------------------------------------------

class IpcClient:
    """
    Async RPMsg IPC client.

    Usage::

        async with IpcClient(mock=True) as ipc:
            msg = await ipc.send_recv(MSG_MOTION_HOME, b"\\x00")
    """

    def __init__(
        self,
        device: str = "/dev/rpmsg0",
        mock: bool = False,
        timeout_s: float = 2.0,
    ) -> None:
        self._device = device
        self._mock = mock
        self._timeout = timeout_s
        self._seq: int = 0
        self._fd: Optional[int] = None
        self._lock = asyncio.Lock()
        self._connected = False

        # Mock state (shared across calls in mock mode)
        self._mock_motion_state: int = 0   # MOTION_STATE_IDLE
        self._mock_position: list[float] = [0.0, 0.0, 0.0, 0.0]
        self._mock_velocity: list[float] = [0.0, 0.0, 0.0, 0.0]
        self._mock_current_step: int = 0
        self._mock_total_steps: int = 0
        self._mock_bcode_task: Optional[asyncio.Task] = None
        self._mock_driver_enabled: bool = True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def _create_rpmsg_endpoint(ctrl: str = "/dev/rpmsg_ctrl0",
                                name: str = "ortho-bender-ipc",
                                dst: int = 30) -> str:
        """
        Create a user-space RPMsg endpoint via rpmsg_char ioctl.
        Returns the path of the created /dev/rpmsgN device.
        """
        import fcntl
        import struct
        import glob

        # RPMSG_CREATE_EPT_IOCTL = _IOW('r', 0x80, struct rpmsg_endpoint_info)
        # struct rpmsg_endpoint_info { char name[32]; __u32 src; __u32 dst; }
        RPMSG_CREATE_EPT_IOCTL = 0x4028_7280

        name_bytes = name.encode()[:31].ljust(32, b"\x00")
        info = struct.pack("32sII", name_bytes, 0xFFFFFFFF, dst)

        # Snapshot existing rpmsg devices before creating new one
        before = set(glob.glob("/dev/rpmsg[0-9]*"))
        before.discard("/dev/rpmsg_ctrl0")

        fd = os.open(ctrl, os.O_RDWR)
        try:
            fcntl.ioctl(fd, RPMSG_CREATE_EPT_IOCTL, info)
        finally:
            os.close(fd)

        import time
        time.sleep(0.2)
        after = set(glob.glob("/dev/rpmsg[0-9]*"))
        after.discard("/dev/rpmsg_ctrl0")
        new_devs = sorted(after - before)
        if new_devs:
            return new_devs[0]
        # Fallback: return highest-numbered rpmsg device
        all_devs = sorted(after)
        return all_devs[-1] if all_devs else "/dev/rpmsg0"

    async def connect(self) -> None:
        if self._mock:
            log.warning("IpcClient: running in MOCK mode — no hardware required")
            self._connected = True
            return

        loop = asyncio.get_running_loop()

        # If the configured device doesn't exist, search for any rpmsgN device
        # or try to create one via rpmsg_ctrl0
        if not os.path.exists(self._device):
            import glob
            # Check for any existing rpmsg character devices
            candidates = sorted(
                d for d in glob.glob("/dev/rpmsg[0-9]*")
                if "ctrl" not in d
            )
            if candidates:
                self._device = candidates[0]
                log.info("IpcClient: using existing RPMsg device %s", self._device)
            else:
                ctrl = "/dev/rpmsg_ctrl0"
                if not os.path.exists(ctrl):
                    raise FileNotFoundError(
                        f"RPMsg device {self._device} not found and "
                        f"{ctrl} not present. Is the M7 firmware loaded?"
                    )
                log.info("IpcClient: %s not found — creating RPMsg endpoint via %s",
                         self._device, ctrl)
                try:
                    created = await loop.run_in_executor(
                        None, self._create_rpmsg_endpoint
                    )
                    log.info("IpcClient: endpoint created at %s", created)
                    self._device = created
                except OSError as exc:
                    raise FileNotFoundError(
                        f"RPMsg endpoint creation failed: {exc}. "
                        "Is the M7 firmware loaded?"
                    ) from exc

        self._fd = await loop.run_in_executor(
            None, lambda: os.open(self._device, os.O_RDWR | os.O_NONBLOCK)
        )
        self._connected = True
        log.info("IpcClient: connected to %s", self._device)

    async def disconnect(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        self._connected = False

    async def __aenter__(self) -> "IpcClient":
        await self.connect()
        return self

    async def __aexit__(self, *_) -> None:
        await self.disconnect()

    @property
    def connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Public send/receive
    # ------------------------------------------------------------------

    async def send_recv(
        self, msg_type: int, payload: bytes = b"", timeout_s: Optional[float] = None
    ) -> IpcMessage:
        """Send an IPC message and await the corresponding response."""
        if not self._connected:
            raise RuntimeError("IpcClient not connected")

        async with self._lock:
            if self._mock:
                return await self._mock_handle(msg_type, payload)
            return await self._hw_send_recv(msg_type, payload, timeout_s or self._timeout)

    async def send_only(self, msg_type: int, payload: bytes = b"") -> None:
        """Fire-and-forget send (no response expected)."""
        if not self._connected:
            raise RuntimeError("IpcClient not connected")
        async with self._lock:
            if self._mock:
                await self._mock_handle(msg_type, payload)
                return
            frame = self._build_frame(msg_type, payload)
            await self._hw_write(frame)

    # ------------------------------------------------------------------
    # Frame construction / parsing
    # ------------------------------------------------------------------

    def _build_frame(self, msg_type: int, payload: bytes) -> bytes:
        seq = self._seq
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        ts = int(time.monotonic() * 1_000_000)
        payload_len = len(payload)

        # Header without crc32 (20 bytes): magic, msg_type, payload_len, seq, ts
        header_pre = struct.pack("<IHHIQ", IPC_MAGIC, msg_type, payload_len, seq, ts)
        crc = _compute_crc32(header_pre, payload)

        # Full header (24 bytes)
        header = header_pre + struct.pack("<I", crc)
        return header + payload

    def _parse_frame(self, data: bytes) -> IpcMessage:
        if len(data) < IPC_HEADER_SIZE:
            raise ValueError(f"Frame too short: {len(data)} bytes")

        magic, msg_type, payload_len, seq, ts, crc = struct.unpack_from(
            IPC_HEADER_FMT, data, 0
        )
        if magic != IPC_MAGIC:
            raise ValueError(f"Bad magic: 0x{magic:08X}")

        payload = data[IPC_HEADER_SIZE: IPC_HEADER_SIZE + payload_len]

        # Verify CRC
        header_pre = data[: IPC_HEADER_SIZE - 4]   # everything before crc32 field
        expected = _compute_crc32(header_pre, payload)
        if crc != expected:
            raise ValueError(f"CRC mismatch: got 0x{crc:08X}, expected 0x{expected:08X}")

        return IpcMessage(msg_type=msg_type, payload=payload, sequence=seq, timestamp_us=ts)

    # ------------------------------------------------------------------
    # Hardware I/O
    # ------------------------------------------------------------------

    async def _hw_write(self, frame: bytes) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: os.write(self._fd, frame))

    async def _hw_read(self, timeout_s: float) -> bytes:
        loop = asyncio.get_running_loop()

        async def _read() -> bytes:
            buf = bytearray(IPC_HEADER_SIZE + IPC_MAX_PAYLOAD)
            while True:
                try:
                    n = await loop.run_in_executor(None, lambda: os.read(self._fd, len(buf)))
                    return bytes(n)
                except BlockingIOError:
                    await asyncio.sleep(0.001)

        return await asyncio.wait_for(_read(), timeout=timeout_s)

    async def _hw_send_recv(
        self, msg_type: int, payload: bytes, timeout_s: float
    ) -> IpcMessage:
        frame = self._build_frame(msg_type, payload)
        await self._hw_write(frame)
        raw = await self._hw_read(timeout_s)
        return self._parse_frame(raw)

    # ------------------------------------------------------------------
    # Mock handler
    # ------------------------------------------------------------------

    async def _mock_handle(self, msg_type: int, payload: bytes) -> IpcMessage:
        """Return plausible mock responses for all known message types."""
        await asyncio.sleep(0.005)  # simulate minimal round-trip

        if msg_type in (MSG_MOTION_HOME, MSG_MOTION_RESET):
            self._mock_position = [0.0, 0.0, 0.0, 0.0]
            self._mock_motion_state = 0  # IDLE
            return self._mock_status_motion()

        if msg_type == MSG_MOTION_STOP:
            self._mock_motion_state = 0
            return self._mock_status_motion()

        if msg_type == MSG_MOTION_ESTOP:
            self._mock_motion_state = 6  # ESTOP
            return self._mock_status_motion()

        if msg_type == MSG_MOTION_SET_DRV_ENABLE:
            # payload: enable(1B), axis_mask(1B), _pad(2B)
            if len(payload) >= 4:
                enable = struct.unpack_from("<B", payload, 0)[0]
                # Refuse disable while motion is active (firmware-level guard mirror).
                if enable == 0 and self._mock_motion_state not in (0, 6):
                    return IpcMessage(
                        msg_type=MSG_STATUS_MOTION,
                        payload=self._mock_status_motion().payload,
                    )
                self._mock_driver_enabled = (enable != 0)
            return self._mock_status_motion()

        if msg_type == MSG_MOTION_JOG:
            # Parse jog payload: axis(1B), direction(1B), speed(4B), distance(4B)
            if len(payload) >= 10:
                axis, direction = struct.unpack_from("<Bb", payload, 0)
                distance = struct.unpack_from("<f", payload, 6)[0]
                if 0 <= axis < 4:
                    self._mock_position[axis] += direction * abs(distance)
            self._mock_motion_state = 0
            return self._mock_status_motion()

        if msg_type == MSG_MOTION_EXECUTE_BCODE:
            # Parse header (mirrors build_bcode_payload):
            #   step_count(H=2B) + material_id(H=2B) + diameter(f=4B) + N × (L,beta,theta) fff
            step_count = 0
            steps: list[tuple[float, float, float]] = []
            if len(payload) >= 8:
                step_count = struct.unpack_from("<H", payload, 0)[0]
                for i in range(step_count):
                    off = 8 + i * 12
                    if off + 12 <= len(payload):
                        L, beta, theta = struct.unpack_from("<fff", payload, off)
                        steps.append((L, beta, theta))

            # Cancel any previous bcode simulation task
            if self._mock_bcode_task and not self._mock_bcode_task.done():
                self._mock_bcode_task.cancel()

            self._mock_total_steps = step_count
            self._mock_current_step = 0
            self._mock_motion_state = 2  # RUNNING
            self._mock_bcode_task = asyncio.create_task(self._simulate_bcode(steps))
            # Dispatch-acknowledge only; completion arrives later via internal state
            return IpcMessage(
                msg_type=MSG_STATUS_BCODE_COMPLETE,
                payload=struct.pack("<H", step_count),
            )

        if msg_type == MSG_DIAG_GET_VERSION:
            # Return MSG_STATUS_VERSION: major=1, minor=0, patch=0, reserved=0, ts=0
            resp_payload = struct.pack("<BBBBI", 1, 0, 0, 0, 0)
            return IpcMessage(msg_type=MSG_STATUS_VERSION, payload=resp_payload)

        if msg_type == MSG_STATUS_HEARTBEAT:
            # Return heartbeat payload: uptime_ms(4B), state(1B), alarms(2B), wdt_ok(1B), axis_mask(1B)
            resp_payload = struct.pack(
                "<IBHBB",
                int(time.monotonic() * 1000) & 0xFFFFFFFF,
                self._mock_motion_state,
                0,   # active_alarms
                1,   # watchdog_ok
                0x0F  # all 4 axes: FEED, BEND, ROTATE, LIFT
            )
            return IpcMessage(msg_type=MSG_STATUS_HEARTBEAT, payload=resp_payload)

        # Default: return current motion status
        return self._mock_status_motion()

    def _mock_status_motion(self) -> IpcMessage:
        """Build a MSG_STATUS_MOTION response from current mock state."""
        payload = struct.pack(
            "<B4f4fHHBB",
            self._mock_motion_state,
            *self._mock_position,
            *self._mock_velocity,
            self._mock_current_step,
            self._mock_total_steps,
            0x0F,  # all 4 axes: FEED, BEND, ROTATE, LIFT
            1 if self._mock_driver_enabled else 0,
        )
        return IpcMessage(msg_type=MSG_STATUS_MOTION, payload=payload)

    async def _simulate_bcode(
        self, steps: list[tuple[float, float, float]]
    ) -> None:
        """
        Background task that simulates step-by-step B-code execution.
        Each step takes ~0.3 s and updates position/velocity/step counters so
        /ws/motor subscribers can observe realistic progress.
        """
        try:
            step_duration = 0.3
            sub_ticks = 6
            for idx, (L, beta, theta) in enumerate(steps):
                self._mock_current_step = idx + 1
                self._mock_motion_state = 2  # RUNNING
                # FEED phase
                self._mock_velocity[0] = L / step_duration if L else 0.0
                self._mock_velocity[2] = beta / step_duration if beta else 0.0
                self._mock_velocity[1] = theta / step_duration if theta else 0.0
                for _ in range(sub_ticks):
                    self._mock_position[0] += L / sub_ticks
                    self._mock_position[2] += beta / sub_ticks
                    self._mock_position[1] += theta / sub_ticks
                    await asyncio.sleep(step_duration / sub_ticks)
            self._mock_velocity = [0.0, 0.0, 0.0, 0.0]
            self._mock_motion_state = 0  # IDLE
        except asyncio.CancelledError:
            self._mock_velocity = [0.0, 0.0, 0.0, 0.0]
            self._mock_motion_state = 0
            raise


# ---------------------------------------------------------------------------
# Payload builders — one function per message type
# ---------------------------------------------------------------------------

def build_jog_payload(axis: int, direction: int, speed: float, distance: float) -> bytes:
    """Build MSG_MOTION_JOG payload."""
    return struct.pack("<Bbff", axis, direction, speed, distance)


def build_home_payload(axis_mask: int) -> bytes:
    """Build MSG_MOTION_HOME payload."""
    return struct.pack("<B", axis_mask)


def build_drv_enable_payload(enable: bool, axis_mask: int = 0) -> bytes:
    """Build MSG_MOTION_SET_DRV_ENABLE payload (1B enable + 1B mask + 2B pad)."""
    return struct.pack("<BBH", 1 if enable else 0, axis_mask & 0xFF, 0)


def build_bcode_payload(
    steps: list[tuple[float, float, float]],
    material_id: int,
    wire_diameter_mm: float,
) -> bytes:
    """
    Build MSG_MOTION_EXECUTE_BCODE payload.
    Each step is (L_mm, beta_deg, theta_deg).
    """
    step_count = len(steps)
    data = struct.pack("<HHf", step_count, material_id, wire_diameter_mm)
    for L_mm, beta_deg, theta_deg in steps:
        data += struct.pack("<fff", L_mm, beta_deg, theta_deg)
    return data
