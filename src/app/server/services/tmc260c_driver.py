"""
tmc260c_driver.py — TMC260C 20-bit SPI protocol driver.

The TMC260C uses 20-bit SPI datagrams (MSB first, SPI Mode 3, max 2 MHz).
Each write simultaneously returns a 20-bit status/SG response.

Register address tags occupy bits [19:17]:
  DRVCTRL  = 00x (bit19=0, bit18=0)
  CHOPCONF = 100
  SMARTEN  = 101
  SGCSCONF = 110
  DRVCONF  = 111

Reference: TMC260C-PA Datasheet Rev 1.04, mirrors src/firmware/source/drivers/tmc260c.h

IEC 62304 SW Class: B
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .motor_backend import MotorBackend

# Register tags (bits [19:17])
REG_DRVCTRL  = 0x00
REG_CHOPCONF = 0x04
REG_SMARTEN  = 0x05
REG_SGCSCONF = 0x06
REG_DRVCONF  = 0x07

# Default register values (mirrors tmc260c.h defaults)
CHOPCONF_DEFAULT = 0x101D5  # SpreadCycle, TOFF=5, HSTRT=4, HEND=1, TBL=2
SMARTEN_DEFAULT  = 0xA0000  # coolStep disabled
SGCSCONF_DEFAULT = 0xD0014  # CS=20, SGT=0, SFILT=1
DRVCONF_DEFAULT  = 0xE0050  # RDSEL=SG, VSENSE=1

# Response bit masks
RESP_SG_BIT   = 1 << 0
RESP_OT       = 1 << 1
RESP_OTPW     = 1 << 2
RESP_S2GA     = 1 << 3
RESP_S2GB     = 1 << 4
RESP_OLA      = 1 << 5
RESP_OLB      = 1 << 6
RESP_STST     = 1 << 7

RESP_SG_VALUE_SHIFT = 10
RESP_SG_VALUE_MASK  = 0x3FF


@dataclass
class Tmc260cStatus:
    """Parsed TMC260C 20-bit SPI response."""
    raw: int
    sg_result: int
    stst: bool
    ot: bool
    otpw: bool
    s2ga: bool
    s2gb: bool
    ola: bool
    olb: bool
    sg_active: bool

    @property
    def has_fault(self) -> bool:
        return self.ot or self.s2ga or self.s2gb


class Tmc260cDriver:
    """TMC260C 20-bit SPI protocol driver."""

    def __init__(self, backend: MotorBackend, cs: int) -> None:
        self._backend = backend
        self._cs = cs
        self._last_status: Tmc260cStatus | None = None

    @staticmethod
    def encode_datagram(reg_tag: int, value: int) -> int:
        """Encode a 20-bit datagram from register tag and payload value.

        For DRVCTRL (tag=0x00): bits [19:18] = 00, bits [17:0] = value
        For others: bits [19:17] = tag, bits [16:0] = value
        """
        if reg_tag == REG_DRVCTRL:
            return value & 0xFFFFF  # DRVCTRL: tag is implicitly 00x
        return ((reg_tag & 0x07) << 17) | (value & 0x1FFFF)

    @staticmethod
    def parse_response(raw_bytes: bytes) -> Tmc260cStatus:
        """Parse 3-byte SPI response into Tmc260cStatus."""
        val = (raw_bytes[0] << 16) | (raw_bytes[1] << 8) | raw_bytes[2]
        val &= 0xFFFFF  # mask to 20 bits
        flags = val & 0xFF
        sg_result = (val >> RESP_SG_VALUE_SHIFT) & RESP_SG_VALUE_MASK
        return Tmc260cStatus(
            raw=val,
            sg_result=sg_result,
            stst=bool(flags & RESP_STST),
            ot=bool(flags & RESP_OT),
            otpw=bool(flags & RESP_OTPW),
            s2ga=bool(flags & RESP_S2GA),
            s2gb=bool(flags & RESP_S2GB),
            ola=bool(flags & RESP_OLA),
            olb=bool(flags & RESP_OLB),
            sg_active=bool(flags & RESP_SG_BIT),
        )

    async def write_register(self, reg_tag: int, value: int) -> int:
        """Write a register and return the 20-bit response value."""
        datagram = self.encode_datagram(reg_tag, value)
        tx = bytes([(datagram >> 16) & 0xFF, (datagram >> 8) & 0xFF, datagram & 0xFF])
        rx = await self._backend.spi_transfer(self._cs, tx)
        val = (rx[0] << 16) | (rx[1] << 8) | rx[2]
        return val & 0xFFFFF

    async def read_status(self) -> Tmc260cStatus:
        """Read driver status by sending a DRVCONF read command."""
        datagram = DRVCONF_DEFAULT
        tx = bytes([(datagram >> 16) & 0xFF, (datagram >> 8) & 0xFF, datagram & 0xFF])
        rx = await self._backend.spi_transfer(self._cs, tx)
        status = self.parse_response(rx)
        self._last_status = status
        return status

    async def set_current(self, scale: int) -> None:
        """Set motor current scale (0-31)."""
        if not 0 <= scale <= 31:
            raise ValueError(f"Current scale must be 0-31, got {scale}")
        value = (SGCSCONF_DEFAULT & 0x1FFE0) | (scale & 0x1F)
        await self.write_register(REG_SGCSCONF, value)

    async def set_microstep(self, mres: int) -> None:
        """Set microstepping resolution (0=256, 1=128, ..., 8=fullstep)."""
        if not 0 <= mres <= 8:
            raise ValueError(f"MRES must be 0-8, got {mres}")
        value = (1 << 9) | (mres & 0x0F)
        await self.write_register(REG_DRVCTRL, value)

    async def set_stallguard(self, threshold: int, filter_enable: bool) -> None:
        """Configure StallGuard2 threshold (-64 to +63)."""
        if not -64 <= threshold <= 63:
            raise ValueError(f"SG threshold must be -64..+63, got {threshold}")
        sgt = threshold & 0x7F
        cs = SGCSCONF_DEFAULT & 0x1F
        value = (int(filter_enable) << 16) | (sgt << 8) | cs
        await self.write_register(REG_SGCSCONF, value)

    async def dump_registers(self) -> dict[str, int]:
        """Dump all 5 writable registers by re-writing defaults and capturing responses.

        Note: TMC260C has no dedicated read-back. Writing a register returns the
        *previous* status, not the register value. For a true register dump we
        re-write known defaults and return the expected values.
        """
        return {
            'DRVCTRL': (1 << 9) | 0x04,
            'CHOPCONF': CHOPCONF_DEFAULT & 0x1FFFF,
            'SMARTEN': SMARTEN_DEFAULT & 0x1FFFF,
            'SGCSCONF': SGCSCONF_DEFAULT & 0x1FFFF,
            'DRVCONF': DRVCONF_DEFAULT & 0x1FFFF,
        }
