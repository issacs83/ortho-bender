"""
tmc5072_driver.py — TMC5072 40-bit SPI protocol driver.

The TMC5072 uses 40-bit SPI datagrams: 8-bit address + 32-bit data.
Bit 7 of the address byte: 0=read, 1=write.
The chip contains 2 independent motor channels.

Reference: TMC5072 Datasheet Rev 1.17
Motor 0 registers: 0x00-0x3F (shared) + 0x20-0x3F (motor 0 specific)
Motor 1 registers: 0x40-0x5F (motor 1 specific)
CHOPCONF M0: 0x6C, M1: 0x7C
DRV_STATUS M0: 0x6F, M1: 0x7F

IEC 62304 SW Class: B
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .motor_backend import MotorBackend

# Shared register addresses
GCONF      = 0x00
GSTAT      = 0x01
IC_VERSION = 0x73

# Per-motor register base addresses (motor 0)
RAMPMODE   = 0x20  # M0: 0x20, M1: 0x40
XACTUAL    = 0x21  # M0: 0x21, M1: 0x41
VACTUAL    = 0x22  # M0: 0x22, M1: 0x42
VMAX       = 0x27  # M0: 0x27, M1: 0x47
AMAX       = 0x28  # M0: 0x28, M1: 0x48
DMAX       = 0x29  # M0: 0x29, M1: 0x49
XTARGET    = 0x2D  # M0: 0x2D, M1: 0x4D
IHOLD_IRUN = 0x30  # M0: 0x30, M1: 0x50
RAMP_STAT  = 0x35  # M0: 0x35, M1: 0x55
CHOPCONF   = 0x6C  # M0: 0x6C, M1: 0x7C
DRV_STATUS = 0x6F  # M0: 0x6F, M1: 0x7F


def _motor_reg(base_addr: int, motor: int) -> int:
    """Return register address adjusted for motor channel.

    Motor 0 and motor 1 registers are offset by different amounts
    depending on the register block:
    - Motion/ramp registers (0x20-0x5F): M1 = M0 + 0x20
    - Driver registers (0x6C-0x7F): M1 = M0 + 0x10
    """
    if motor == 0:
        return base_addr
    if base_addr >= 0x6C:
        return base_addr + 0x10  # CHOPCONF: 0x6C -> 0x7C, DRV_STATUS: 0x6F -> 0x7F
    if base_addr >= 0x20:
        return base_addr + 0x20  # RAMPMODE: 0x20 -> 0x40, XACTUAL: 0x21 -> 0x41, etc.
    return base_addr


class Tmc5072Driver:
    """TMC5072 40-bit SPI protocol driver.

    Implements the TMC5072 SPI datagram protocol for two-axis motion control.
    Each SPI transfer is exactly 5 bytes (40 bits).
    """

    def __init__(self, backend: MotorBackend, cs: int) -> None:
        self._backend = backend
        self._cs = cs

    @staticmethod
    def encode_write(addr: int, value: int) -> bytes:
        """Encode a 40-bit write datagram.

        Format: [1|addr(7)] [data_byte3] [data_byte2] [data_byte1] [data_byte0]
        Bit 7 of first byte set to 1 indicates write operation.
        """
        return bytes([
            0x80 | (addr & 0x7F),
            (value >> 24) & 0xFF,
            (value >> 16) & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ])

    @staticmethod
    def encode_read(addr: int) -> bytes:
        """Encode a 40-bit read datagram.

        Format: [0|addr(7)] [0x00] [0x00] [0x00] [0x00]
        Bit 7 of first byte clear (0) indicates read operation.
        """
        return bytes([addr & 0x7F, 0, 0, 0, 0])

    @staticmethod
    def parse_response(rx: bytes) -> int:
        """Extract 32-bit register value from 5-byte SPI response."""
        return (rx[1] << 24) | (rx[2] << 16) | (rx[3] << 8) | rx[4]

    async def read_register(self, addr: int) -> int:
        """Read a TMC5072 register.

        TMC5072 read requires two SPI transfers: first transfer sends
        the read address, second transfer clocks out the register data.
        """
        tx = self.encode_read(addr)
        await self._backend.spi_transfer(self._cs, tx)
        rx = await self._backend.spi_transfer(self._cs, bytes(5))
        return self.parse_response(rx)

    async def write_register(self, addr: int, value: int) -> None:
        """Write a 32-bit value to a TMC5072 register."""
        tx = self.encode_write(addr, value)
        await self._backend.spi_transfer(self._cs, tx)

    async def move_to(
        self,
        motor: int,
        position: int,
        vmax: int,
        amax: int,
    ) -> None:
        """Command motor to move to absolute position using internal ramp generator.

        Sets RAMPMODE=0 (positioning mode), configures velocity/acceleration,
        then writes XTARGET to trigger motion.
        """
        await self.write_register(_motor_reg(RAMPMODE, motor), 0)
        await self.write_register(_motor_reg(VMAX, motor), vmax)
        await self.write_register(_motor_reg(AMAX, motor), amax)
        await self.write_register(_motor_reg(DMAX, motor), amax)
        await self.write_register(_motor_reg(XTARGET, motor), position & 0xFFFFFFFF)

    async def get_position(self, motor: int) -> int:
        """Read current position (XACTUAL) for motor channel.

        Returns signed 32-bit position in microsteps.
        """
        val = await self.read_register(_motor_reg(XACTUAL, motor))
        if val >= 0x80000000:
            val -= 0x100000000
        return val

    async def get_drv_status(self, motor: int) -> int:
        """Read DRV_STATUS register for motor channel.

        Contains StallGuard2 load measurement, overtemperature flags,
        open-load and short-circuit detection bits.
        """
        return await self.read_register(_motor_reg(DRV_STATUS, motor))

    async def dump_registers(self) -> dict[str, int]:
        """Dump key registers for both motor channels.

        Useful for diagnostics and configuration verification.
        Returns a dict with human-readable register names as keys.
        """
        result: dict[str, int] = {}
        result['GCONF'] = await self.read_register(GCONF)
        result['GSTAT'] = await self.read_register(GSTAT)
        for m in (0, 1):
            suffix = f'_M{m}'
            result[f'XACTUAL{suffix}'] = await self.read_register(
                _motor_reg(XACTUAL, m)
            )
            result[f'VACTUAL{suffix}'] = await self.read_register(
                _motor_reg(VACTUAL, m)
            )
            result[f'CHOPCONF{suffix}'] = await self.read_register(
                _motor_reg(CHOPCONF, m)
            )
            result[f'DRV_STATUS{suffix}'] = await self.read_register(
                _motor_reg(DRV_STATUS, m)
            )
        return result
