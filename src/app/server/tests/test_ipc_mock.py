"""
test_ipc_mock.py — Unit tests for IpcClient mock handler.

Tests each message type's mock response without network or hardware.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import struct
import pytest
import pytest_asyncio

from server.services.ipc_client import (
    IpcClient,
    IpcMessage,
    MSG_MOTION_EXECUTE_BCODE,
    MSG_MOTION_JOG,
    MSG_MOTION_HOME,
    MSG_MOTION_STOP,
    MSG_MOTION_ESTOP,
    MSG_MOTION_RESET,
    MSG_DIAG_GET_VERSION,
    MSG_STATUS_MOTION,
    MSG_STATUS_TMC,
    MSG_STATUS_HEARTBEAT,
    MSG_STATUS_BCODE_COMPLETE,
    MSG_STATUS_VERSION,
    build_jog_payload,
    build_home_payload,
    build_bcode_payload,
    _crc32_update,
    _compute_crc32,
)


@pytest_asyncio.fixture
async def ipc() -> IpcClient:
    """Connected mock IpcClient for unit testing."""
    client = IpcClient(mock=True)
    await client.connect()
    yield client
    await client.disconnect()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def test_ipc_mock_connects():
    """Mock IPC should connect without hardware."""
    client = IpcClient(mock=True)
    await client.connect()
    assert client.connected is True
    await client.disconnect()
    assert client.connected is False


# ---------------------------------------------------------------------------
# MSG_STATUS_MOTION
# ---------------------------------------------------------------------------

async def test_ipc_mock_status_motion(ipc):
    """MSG_STATUS_MOTION should return a parseable motion status payload."""
    msg = await ipc.send_recv(MSG_STATUS_MOTION)
    assert msg.msg_type == MSG_STATUS_MOTION
    # payload: state(1B) + pos[4](4f) + vel[4](4f) + curr_step(H) + total(H) + mask(B)
    assert len(msg.payload) >= struct.calcsize("<B4f4fHHB")
    raw = struct.unpack_from("<B4f4fHHB", msg.payload)
    state = raw[0]
    axis_mask = raw[11]
    assert 0 <= state <= 6
    assert axis_mask == 0x03


# ---------------------------------------------------------------------------
# MSG_MOTION_HOME
# ---------------------------------------------------------------------------

async def test_ipc_mock_home_resets_position(ipc):
    """MSG_MOTION_HOME should reset mock position to 0.0."""
    # First jog to move position
    jog_payload = build_jog_payload(0, 1, 10.0, 20.0)
    await ipc.send_recv(MSG_MOTION_JOG, jog_payload)

    # Home resets position
    home_payload = build_home_payload(0)
    msg = await ipc.send_recv(MSG_MOTION_HOME, home_payload)
    raw = struct.unpack_from("<B4f4fHHB", msg.payload)
    positions = list(raw[1:5])
    assert all(p == 0.0 for p in positions)


# ---------------------------------------------------------------------------
# MSG_MOTION_STOP
# ---------------------------------------------------------------------------

async def test_ipc_mock_stop_returns_idle(ipc):
    """MSG_MOTION_STOP should set state to IDLE (0)."""
    msg = await ipc.send_recv(MSG_MOTION_STOP)
    raw = struct.unpack_from("<B", msg.payload)
    assert raw[0] == 0  # IDLE


# ---------------------------------------------------------------------------
# MSG_MOTION_ESTOP
# ---------------------------------------------------------------------------

async def test_ipc_mock_estop_returns_estop_state(ipc):
    """MSG_MOTION_ESTOP should set state to ESTOP (6)."""
    msg = await ipc.send_recv(MSG_MOTION_ESTOP)
    raw = struct.unpack_from("<B", msg.payload)
    assert raw[0] == 6  # ESTOP


# ---------------------------------------------------------------------------
# MSG_MOTION_RESET
# ---------------------------------------------------------------------------

async def test_ipc_mock_reset_returns_idle(ipc):
    """MSG_MOTION_RESET should return IDLE state after resetting."""
    # First trigger ESTOP
    await ipc.send_recv(MSG_MOTION_ESTOP)
    # Then reset
    msg = await ipc.send_recv(MSG_MOTION_RESET)
    raw = struct.unpack_from("<B", msg.payload)
    assert raw[0] == 0  # IDLE


# ---------------------------------------------------------------------------
# MSG_MOTION_JOG
# ---------------------------------------------------------------------------

async def test_ipc_mock_jog_updates_position(ipc):
    """MSG_MOTION_JOG with positive direction should increment axis position."""
    # Reset position first
    await ipc.send_recv(MSG_MOTION_HOME)

    jog_payload = build_jog_payload(axis=0, direction=1, speed=10.0, distance=15.0)
    await ipc.send_recv(MSG_MOTION_JOG, jog_payload)

    status = await ipc.send_recv(MSG_STATUS_MOTION)
    raw = struct.unpack_from("<B4f4fHHB", status.payload)
    pos_feed = raw[1]
    assert pos_feed > 0.0


async def test_ipc_mock_jog_negative_decrements_position(ipc):
    """MSG_MOTION_JOG with negative direction should decrement axis position."""
    # Start at known position
    await ipc.send_recv(MSG_MOTION_HOME)
    # Move positive first
    await ipc.send_recv(MSG_MOTION_JOG, build_jog_payload(0, 1, 10.0, 30.0))
    # Then jog negative
    await ipc.send_recv(MSG_MOTION_JOG, build_jog_payload(0, -1, 10.0, 10.0))

    status = await ipc.send_recv(MSG_STATUS_MOTION)
    raw = struct.unpack_from("<B4f4fHHB", status.payload)
    pos_feed = raw[1]
    # Should be 30 - 10 = 20
    assert abs(pos_feed - 20.0) < 0.01


# ---------------------------------------------------------------------------
# MSG_MOTION_EXECUTE_BCODE
# ---------------------------------------------------------------------------

async def test_ipc_mock_bcode_returns_complete(ipc):
    """MSG_MOTION_EXECUTE_BCODE should return MSG_STATUS_BCODE_COMPLETE."""
    steps = [(10.0, 0.0, 45.0), (5.0, 90.0, 30.0)]
    payload = build_bcode_payload(steps, material_id=0, wire_diameter_mm=0.457)
    msg = await ipc.send_recv(MSG_MOTION_EXECUTE_BCODE, payload)
    assert msg.msg_type == MSG_STATUS_BCODE_COMPLETE


# ---------------------------------------------------------------------------
# MSG_DIAG_GET_VERSION
# ---------------------------------------------------------------------------

async def test_ipc_mock_version_returns_version_msg(ipc):
    """MSG_DIAG_GET_VERSION should return MSG_STATUS_VERSION with valid data."""
    msg = await ipc.send_recv(MSG_DIAG_GET_VERSION)
    assert msg.msg_type == MSG_STATUS_VERSION
    assert len(msg.payload) >= 8
    major, minor, patch, _, ts = struct.unpack_from("<BBBBI", msg.payload)
    assert major == 1
    assert minor == 0
    assert patch == 0


# ---------------------------------------------------------------------------
# MSG_STATUS_HEARTBEAT
# ---------------------------------------------------------------------------

async def test_ipc_mock_heartbeat_returns_payload(ipc):
    """MSG_STATUS_HEARTBEAT should return a valid heartbeat payload."""
    msg = await ipc.send_recv(MSG_STATUS_HEARTBEAT)
    assert msg.msg_type == MSG_STATUS_HEARTBEAT
    assert len(msg.payload) >= 9
    # uptime_ms(4B) state(1B) alarms(2B) wdt_ok(1B) axis_mask(1B)
    uptime_ms, state, alarms, wdt_ok, axis_mask = struct.unpack_from(
        "<IBHBB", msg.payload
    )
    assert wdt_ok == 1
    assert 0 <= state <= 6
    assert axis_mask == 0x03


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------

def test_build_jog_payload_size():
    """build_jog_payload should produce a 10-byte payload."""
    payload = build_jog_payload(axis=0, direction=1, speed=10.0, distance=5.0)
    assert len(payload) == struct.calcsize("<Bbff")


def test_build_home_payload_size():
    """build_home_payload should produce a 1-byte payload."""
    payload = build_home_payload(axis_mask=0x03)
    assert len(payload) == 1
    assert payload[0] == 0x03


def test_build_bcode_payload_structure():
    """build_bcode_payload should have correct header + step data."""
    steps = [(10.0, 0.0, 45.0), (5.0, 90.0, 30.0)]
    payload = build_bcode_payload(steps, material_id=1, wire_diameter_mm=0.457)
    header_size = struct.calcsize("<HHf")
    step_size = struct.calcsize("<fff")
    expected = header_size + len(steps) * step_size
    assert len(payload) == expected
    step_count, mat_id, wire_d = struct.unpack_from("<HHf", payload)
    assert step_count == 2
    assert mat_id == 1
    assert abs(wire_d - 0.457) < 0.001


# ---------------------------------------------------------------------------
# CRC utilities
# ---------------------------------------------------------------------------

def test_crc32_update_deterministic():
    """CRC-32 should produce consistent results for the same input."""
    data = b"ortho-bender-ipc-test"
    crc1 = _crc32_update(0, data)
    crc2 = _crc32_update(0, data)
    assert crc1 == crc2


def test_crc32_update_different_data():
    """Different data should produce different CRC values."""
    crc1 = _crc32_update(0, b"hello")
    crc2 = _crc32_update(0, b"world")
    assert crc1 != crc2


def test_frame_build_and_parse_round_trip():
    """A built frame should parse back to the original message fields."""
    client = IpcClient(mock=True)
    msg_type = MSG_MOTION_STOP
    payload = b"\xDE\xAD\xBE\xEF"
    frame = client._build_frame(msg_type, payload)
    parsed = client._parse_frame(frame)
    assert parsed.msg_type == msg_type
    assert parsed.payload == payload
