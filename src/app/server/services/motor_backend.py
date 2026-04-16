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

    def __init__(self) -> None:
        self.positions: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
        self._gpio_state: dict[str, bool] = {}
        self._sg_value: int = 512  # mid-range StallGuard2

    async def spi_transfer(self, cs: int, data: bytes) -> bytes:
        n = len(data)
        if n == 3:
            # TMC260C 20-bit mock response: STST=1 (standstill), SG=512
            sg = self._sg_value
            # Response format: [19:10]=SG, [9:8]=00, [7:0]=status
            # STST bit is bit 7
            val = ((sg & 0x3FF) << 10) | 0x80  # STST=1
            return bytes([(val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF])
        elif n == 5:
            # TMC5072 40-bit mock response: status byte + 32-bit register value
            # Status byte: bits[7:4]=driver status, bits[1:0]=reset/driver_error
            return bytes([0x00, 0x00, 0x00, 0x00, 0x00])
        return bytes(n)

    async def set_gpio(self, pin: str, value: bool) -> None:
        self._gpio_state[pin] = value

    async def get_gpio(self, pin: str) -> bool:
        return self._gpio_state.get(pin, False)

    async def pulse_step(self, axis: int, count: int,
                         freq_hz: int, direction: int) -> None:
        self.positions[axis] = self.positions.get(axis, 0) + (count * direction)
