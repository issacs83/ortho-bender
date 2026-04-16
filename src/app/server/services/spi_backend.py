"""
spi_backend.py — Linux spidev + gpiod motor backend for test bench.

Uses /dev/spidevX.Y for SPI transfers and gpiod for GPIO control.
STEP pulse generation uses a blocking sleep loop (adequate for bench
test speeds up to 1 kHz; production uses M7 GPT timer ISR).

Requires: python3-spidev, python3-gpiod (on target EVK)

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from .motor_backend import MotorBackend

log = logging.getLogger(__name__)

# i.MX8MP GPIO chip mapping for gpiod
# GPIO3_IOxx -> gpiochip2, GPIO5_IOxx -> gpiochip4
_GPIO_CHIP_MAP = {
    'GPIO3': 'gpiochip2',
    'GPIO5': 'gpiochip4',
}


def _parse_gpio(pin: str) -> tuple[str, int]:
    """Parse 'GPIO3_IO19' -> ('gpiochip2', 19)."""
    parts = pin.split('_IO')
    chip_name = _GPIO_CHIP_MAP.get(parts[0])
    if chip_name is None:
        raise ValueError(f"Unknown GPIO bank: {parts[0]}")
    offset = int(parts[1])
    return chip_name, offset


class SpidevMotorBackend(MotorBackend):
    """Hardware backend using Linux spidev for SPI and gpiod for GPIO."""

    def __init__(
        self,
        spi_device: str = "/dev/spidev1.0",
        spi_speed_hz: int = 2_000_000,
        gpio_cs1: str = "GPIO3_IO19",
        gpio_cs2: str = "GPIO3_IO20",
        gpio_feed_step: str = "GPIO3_IO22",
        gpio_bend_step: str = "GPIO3_IO24",
        gpio_dir: str = "GPIO5_IO06",
    ) -> None:
        self._spi_device = spi_device
        self._spi_speed = spi_speed_hz
        self._gpio_names = {
            'cs1': gpio_cs1,
            'cs2': gpio_cs2,
            'feed_step': gpio_feed_step,
            'bend_step': gpio_bend_step,
            'dir': gpio_dir,
        }
        self._spi: Optional[object] = None
        self._gpio_lines: dict[str, object] = {}
        self.positions: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}

    async def open(self) -> None:
        """Open SPI device and request GPIO lines. Call during app startup."""
        try:
            import spidev
            bus, dev = self._parse_spidev_path(self._spi_device)
            spi = spidev.SpiDev()
            spi.open(bus, dev)
            spi.max_speed_hz = self._spi_speed
            spi.mode = 3  # CPOL=1, CPHA=1
            spi.bits_per_word = 8
            self._spi = spi
            log.info("SPI opened: %s @ %d Hz", self._spi_device, self._spi_speed)
        except ImportError:
            log.error("spidev module not available — install python3-spidev")
            raise

        try:
            import gpiod
            for name, gpio_str in self._gpio_names.items():
                chip_name, offset = _parse_gpio(gpio_str)
                chip = gpiod.Chip(chip_name)
                line = chip.get_line(offset)
                config = gpiod.LineRequest()
                config.consumer = "ortho-bender-diag"
                config.request_type = gpiod.LINE_REQ_DIR_OUT
                line.request(config)
                line.set_value(1 if name.startswith('cs') else 0)  # CS idle high
                self._gpio_lines[name] = line
                log.info("GPIO %s (%s) configured as output", gpio_str, name)
        except ImportError:
            log.error("gpiod module not available — install python3-gpiod")
            raise

    async def close(self) -> None:
        """Release SPI and GPIO resources."""
        if self._spi:
            self._spi.close()
        for line in self._gpio_lines.values():
            line.release()

    @staticmethod
    def _parse_spidev_path(path: str) -> tuple[int, int]:
        """Parse '/dev/spidev1.0' -> (1, 0)."""
        name = path.split('spidev')[1]
        parts = name.split('.')
        return int(parts[0]), int(parts[1])

    async def spi_transfer(self, cs: int, data: bytes) -> bytes:
        """SPI transfer with manual CS for CS1/CS2."""
        if self._spi is None:
            raise RuntimeError("SPI not opened — call open() first")

        # CS0 is hardware-controlled by spidev; CS1/CS2 are GPIO
        if cs == 1:
            self._gpio_lines['cs1'].set_value(0)
        elif cs == 2:
            self._gpio_lines['cs2'].set_value(0)

        try:
            result = self._spi.xfer2(list(data))
            return bytes(result)
        finally:
            if cs == 1:
                self._gpio_lines['cs1'].set_value(1)
            elif cs == 2:
                self._gpio_lines['cs2'].set_value(1)

    async def set_gpio(self, pin: str, value: bool) -> None:
        # Find the line by GPIO name match
        for name, gpio_str in self._gpio_names.items():
            if gpio_str == pin and name in self._gpio_lines:
                self._gpio_lines[name].set_value(int(value))
                return
        log.warning("GPIO %s not configured", pin)

    async def get_gpio(self, pin: str) -> bool:
        for name, gpio_str in self._gpio_names.items():
            if gpio_str == pin and name in self._gpio_lines:
                return bool(self._gpio_lines[name].get_value())
        return False

    async def pulse_step(self, axis: int, count: int,
                         freq_hz: int, direction: int) -> None:
        """Generate STEP pulses via GPIO toggle loop."""
        step_key = 'feed_step' if axis == 0 else 'bend_step'
        step_line = self._gpio_lines.get(step_key)
        dir_line = self._gpio_lines.get('dir')
        if not step_line or not dir_line:
            log.error("GPIO lines not available for axis %d", axis)
            return

        # Set direction
        dir_line.set_value(1 if direction > 0 else 0)
        await asyncio.sleep(0.000005)  # 5 us direction setup time

        half_period = 1.0 / (2 * freq_hz)
        for _ in range(count):
            step_line.set_value(1)
            time.sleep(half_period)
            step_line.set_value(0)
            time.sleep(half_period)

        self.positions[axis] = self.positions.get(axis, 0) + (count * direction)
