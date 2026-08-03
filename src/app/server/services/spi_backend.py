"""
spi_backend.py — Linux spidev + gpiod motor backend for test bench.

Uses /dev/spidevX.Y for SPI transfers and gpiod v2 API for GPIO control.
STEP pulse generation uses a blocking sleep loop (adequate for bench
test speeds up to 1 kHz; production uses M7 GPT timer ISR).

Requires: python3-spidev, python3-gpiod >= 2.0 (on target EVK)

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
    'GPIO3': '/dev/gpiochip2',
    'GPIO5': '/dev/gpiochip4',
}


def _parse_gpio(pin: str) -> tuple[str, int]:
    """Parse 'GPIO3_IO19' -> ('/dev/gpiochip2', 19)."""
    parts = pin.split('_IO')
    chip_path = _GPIO_CHIP_MAP.get(parts[0])
    if chip_path is None:
        raise ValueError(f"Unknown GPIO bank: {parts[0]}")
    offset = int(parts[1])
    return chip_path, offset


class SpidevMotorBackend(MotorBackend):
    """Hardware backend using Linux spidev for SPI and gpiod v2 for GPIO."""

    is_real_hardware = True

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
        # gpiod v2: LineRequest objects keyed by chip path
        self._gpio_requests: dict[str, object] = {}
        # Map logical name -> (chip_path, offset) for value access
        self._gpio_map: dict[str, tuple[str, int]] = {}
        self.positions: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}

    async def open(self) -> None:
        """Open SPI device and request GPIO lines. Call during app startup."""
        try:
            import spidev
            bus, dev = self._parse_spidev_path(self._spi_device)
            spi = spidev.SpiDev()
            spi.open(bus, dev)
            spi.max_speed_hz = self._spi_speed
            spi.bits_per_word = 8
            # TMC requires SPI Mode 3 (CPOL=1, CPHA=1).
            # On i.MX8MP ECSPI, the kernel may include CS_HIGH (0x4) based on
            # DTS cs-gpios polarity, making mode readback 0x7 instead of 0x3.
            try:
                spi.mode = 3
            except OSError:
                spi.mode = 3 | 0x04  # mode 3 + CS_HIGH
                log.warning("SPI mode 3 failed, set mode 0x7 (mode 3 + CS_HIGH)")
            self._spi = spi
            log.info("SPI opened: %s @ %d Hz", self._spi_device, self._spi_speed)
        except ImportError:
            log.error("spidev module not available — install python3-spidev")
            raise

        try:
            import gpiod
            from gpiod.line import Direction, Value

            # Group GPIO lines by chip for efficient request
            chip_lines: dict[str, dict[str, int]] = {}  # chip_path -> {name: offset}
            for name, gpio_str in self._gpio_names.items():
                chip_path, offset = _parse_gpio(gpio_str)
                self._gpio_map[name] = (chip_path, offset)
                chip_lines.setdefault(chip_path, {})[name] = offset

            for chip_path, lines in chip_lines.items():
                offsets = list(lines.values())
                names = list(lines.keys())

                # Build per-line output config with initial values
                line_cfg = {
                    offset: gpiod.LineSettings(
                        direction=Direction.OUTPUT,
                        output_value=Value.ACTIVE if name.startswith('cs') else Value.INACTIVE,
                    )
                    for name, offset in zip(names, offsets)
                }

                req = gpiod.request_lines(
                    chip_path,
                    consumer="ortho-bender-diag",
                    config=line_cfg,
                )
                self._gpio_requests[chip_path] = req
                log.info("GPIO chip %s: requested lines %s", chip_path,
                         {n: o for n, o in zip(names, offsets)})

        except ImportError:
            log.error("gpiod module not available — install python3-gpiod >= 2.0")
            raise

    def _gpio_set(self, name: str, high: bool) -> None:
        """Set a GPIO line by logical name."""
        from gpiod.line import Value
        chip_path, offset = self._gpio_map[name]
        req = self._gpio_requests[chip_path]
        req.set_value(offset, Value.ACTIVE if high else Value.INACTIVE)

    def _gpio_get(self, name: str) -> bool:
        """Read a GPIO line by logical name."""
        from gpiod.line import Value
        chip_path, offset = self._gpio_map[name]
        req = self._gpio_requests[chip_path]
        return req.get_value(offset) == Value.ACTIVE

    async def close(self) -> None:
        """Release SPI and GPIO resources."""
        if self._spi:
            self._spi.close()
        for req in self._gpio_requests.values():
            req.release()

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
            self._gpio_set('cs1', False)
        elif cs == 2:
            self._gpio_set('cs2', False)

        try:
            result = self._spi.xfer2(list(data))
            return bytes(result)
        finally:
            if cs == 1:
                self._gpio_set('cs1', True)
            elif cs == 2:
                self._gpio_set('cs2', True)

    async def set_gpio(self, pin: str, value: bool) -> None:
        for name, gpio_str in self._gpio_names.items():
            if gpio_str == pin and name in self._gpio_map:
                self._gpio_set(name, value)
                return
        log.warning("GPIO %s not configured", pin)

    async def get_gpio(self, pin: str) -> bool:
        for name, gpio_str in self._gpio_names.items():
            if gpio_str == pin and name in self._gpio_map:
                return self._gpio_get(name)
        return False

    async def pulse_step(self, axis: int, count: int,
                         freq_hz: int, direction: int) -> None:
        """Generate STEP pulses via GPIO toggle loop.

        Runs in a thread to avoid blocking the asyncio event loop.
        """
        step_key = 'feed_step' if axis == 0 else 'bend_step'
        if step_key not in self._gpio_map or 'dir' not in self._gpio_map:
            log.error("GPIO lines not available for axis %d", axis)
            return

        def _pulse_blocking():
            self._gpio_set('dir', direction > 0)
            time.sleep(0.000005)  # 5 us direction setup time
            half_period = 1.0 / (2 * freq_hz)
            for _ in range(count):
                self._gpio_set(step_key, True)
                time.sleep(half_period)
                self._gpio_set(step_key, False)
                time.sleep(half_period)

        await asyncio.to_thread(_pulse_blocking)
        self.positions[axis] = self.positions.get(axis, 0) + (count * direction)
