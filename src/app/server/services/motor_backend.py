"""
motor_backend.py — Abstract motor backend + mock implementation.

The MotorBackend ABC defines the transport layer for SPI, GPIO, and
STEP pulse operations. Three implementations exist:

  MockMotorBackend   — no hardware, simulated responses (default)
  SpidevMotorBackend — Linux spidev + gpiod (test bench)
  IpcMotorBackend    — RPMsg to M7 (production, future)

IEC 62304 SW Class: B
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class MotorBackend(ABC):
    """Transport abstraction for motor driver communication."""

    # Real-hardware backends (spidev, IPC) override to True.
    # Used by diag_service to avoid reporting mock responses as
    # "driver connected" — mock SPI returns plausible patterns that
    # would otherwise fool chip-ID probes.
    is_real_hardware: bool = False

    @abstractmethod
    async def spi_transfer(self, cs: int, data: bytes) -> bytes:
        """Send SPI datagram to chip-select `cs`, return response bytes."""
        ...

    @abstractmethod
    async def set_gpio(self, pin: str, value: bool) -> None:
        """Set a GPIO output pin high (True) or low (False)."""
        ...

    @abstractmethod
    async def get_gpio(self, pin: str) -> bool:
        """Read a GPIO input pin value."""
        ...

    @abstractmethod
    async def pulse_step(self, axis: int, count: int,
                         freq_hz: int, direction: int) -> None:
        """Generate `count` STEP pulses at `freq_hz` for `axis`."""
        ...


class MockMotorBackend(MotorBackend):
    """Simulated backend for development and CI testing."""

    # Mock TMC5072 register values for probe identification
    _TMC5072_REGS: dict[int, int] = {
        0x00: 0x00000000,  # GCONF
        0x01: 0x00000001,  # GSTAT (reset flag)
        0x73: 0x00000010,  # IC_VERSION (TMC5072 = 0x10)
    }

    def __init__(self) -> None:
        self.positions: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
        self._gpio_state: dict[str, bool] = {}
        self._sg_value: int = 512  # mid-range StallGuard2
        self._tmc5072_pending: dict[int, int | None] = {}  # cs -> pending read addr

    async def spi_transfer(self, cs: int, data: bytes) -> bytes:
        n = len(data)
        if n == 3:
            # TMC260C 20-bit mock response: STST=1 (standstill), SG=512
            sg = self._sg_value
            val = ((sg & 0x3FF) << 10) | 0x80  # STST=1
            return bytes([(val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF])
        elif n == 5:
            # TMC5072 40-bit: simulate read protocol (2-transfer sequence)
            addr = data[0] & 0x7F
            is_write = bool(data[0] & 0x80)
            if is_write:
                return bytes(5)
            # Read request: first transfer stores address, second returns data
            pending = self._tmc5072_pending.pop(cs, None)
            if pending is not None:
                # Second transfer — return register value for pending address
                val = self._TMC5072_REGS.get(pending, 0)
                return bytes([0x00, (val >> 24) & 0xFF, (val >> 16) & 0xFF,
                              (val >> 8) & 0xFF, val & 0xFF])
            else:
                # First transfer — store read address for next transfer
                self._tmc5072_pending[cs] = addr
                return bytes(5)
        return bytes(n)

    async def set_gpio(self, pin: str, value: bool) -> None:
        self._gpio_state[pin] = value

    async def get_gpio(self, pin: str) -> bool:
        return self._gpio_state.get(pin, False)

    async def pulse_step(self, axis: int, count: int,
                         freq_hz: int, direction: int) -> None:
        self.positions[axis] = self.positions.get(axis, 0) + (count * direction)
