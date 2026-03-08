"""
Serial frame builder/parser. Ported from stub.cpp sendcmd() + getack().

Frame format: STX(0x5B) | CMD | DATA... | CRC16_HI | CRC16_LO | ETX(0x5D)
Reply format: STX(0x5B) | CMD+0x10 | DATA... | CRC16_HI | CRC16_LO | ETX(0x5D)
"""

from .crc16 import calc_crc
from .constants import STX, ETX, ACKC, CMD_PROTOCOLERROR


def build_frame(cmd: int, data: bytes = b"") -> bytes:
    """Build a command frame. Mirrors sendcmd() from stub.cpp."""
    payload = bytes([STX, cmd]) + data
    crc = calc_crc(payload)
    return payload + bytes([(crc >> 8) & 0xFF, crc & 0xFF, ETX])


def parse_response(raw: bytes, expected_cmd: int) -> tuple[bool, bytes]:
    """
    Parse a response frame. Mirrors getack() from stub.cpp.

    Returns (success, data_payload).
    data_payload starts after [STX, CMD_ACK, ...] and excludes CRC+ETX.
    """
    if len(raw) < 5:
        return False, b""

    if raw[0] != STX or raw[-1] != ETX:
        return False, b""

    # Check for protocol error
    if raw[ACKC] == CMD_PROTOCOLERROR:
        return False, b""

    # Check ACK command byte = expected_cmd + 0x10
    if raw[ACKC] != (expected_cmd + 0x10):
        return False, b""

    # Data is between CMD_ACK and CRC (last 3 bytes = CRC_HI, CRC_LO, ETX)
    data = raw[2:-3]
    return True, data
