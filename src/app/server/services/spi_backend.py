"""
spi_backend.py — Linux spidev + gpiod motor backend for test bench.

Implements MotorBackend ABC for the i.MX8MP EVK + Veyron 1×2A ×3 (TMC260C-PA)
test bench. Used both by DiagService (passive register access) and by the
motor service when OB_MOTOR_BACKEND=spidev.

# Verified working configuration (2026-05-08)
  - SPI: /dev/spidev1.0, mode 3 + SPI_NO_CS, 50 kHz
  - 3-axis CS lines (manual GPIO toggle):
      cs=0  →  LIFT  (gpio5_07, ECSPI1_MOSI alt5)
      cs=1  →  BEND  (gpio3_22, SAI5_RXD1 alt5)
      cs=2  →  FEED  (gpio5_13, ECSPI2_SS0 alt5)
  - STEP: PWM4 on SAI5_RXFS pad (pwmchip2/pwm0), parallel to all chips
  - DIR:  gpio3_23 (SAI5_RXD3 alt5), parallel to all chips

# 🚨 HARD SAFETY (cannot override)
  - CS    ≤ 19   (CS=31 burned 1/2층 boards 2026-05-08)
  - TOFF  ≤ 8
  - CHOPCONF defaults frozen at verified 0x99548
  - Init sequence MUST: SPI-first → 500 us CS settle → init 500x SEQ
  - Fault flags (OT/S2G/OL) trigger immediate abort during step pulse

Requires: python3-spidev, python3-gpiod >= 2.0 (on target EVK)

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import struct
import time
from typing import Optional

# Persisted backend state (positions across server restarts).
# Single JSON file readable/writable by the SDK service user.
_STATE_FILE = "/var/lib/ortho-bender/motor-state.json"

from .motor_backend import MotorBackend
from .tmc260c_driver import (
    SAFETY_CS_MAX, SAFETY_TOFF_MAX,
    CHOPCONF_DEFAULT, SMARTEN_DEFAULT, DRVCONF_DEFAULT, SGCSCONF_DEFAULT,
)

log = logging.getLogger(__name__)

# i.MX8MP GPIO chip mapping for gpiod
_GPIO_CHIP_MAP = {
    'GPIO3': '/dev/gpiochip2',
    'GPIO5': '/dev/gpiochip4',
}

# SPI ioctl constants
_SPI_IOC_WR_MODE = 0x40016B01
_SPI_NO_CS = 0x40

# Verified working timings
_CS_SETTLE_S = 0.0005      # 500 us — required for BEND chip on SAI5_RXD1 pad
_DIR_SETUP_S = 0.000010    # 10 us
_INIT_SEQ_CYCLES_FULL = 50      # full init: only when chip is brand-new
                                # (first jog after server start).
_REENABLE_CYCLES = 5            # fast chopper re-enable on subsequent jogs:
                                # CHOPCONF + SGCSCONF only (~15 ms total).
_SILENCE_CYCLES = 5             # chopper-off cycles between jogs.

# Bench convention: ▶ button (direction=+1) must rotate the motor
# clockwise (forward), ◀ button (direction=-1) counter-clockwise.
# The Veyron board's DIR input is wired such that DIR=LOW is CW and
# DIR=HIGH is CCW for our motor mounting, so we drive DIR=LOW when
# the requested direction is positive (+).
_DIR_INVERT = True

# Static safety verification (also done in tmc260c_driver, double-check here)
assert (SGCSCONF_DEFAULT & 0x1F) <= SAFETY_CS_MAX, "SGCSCONF CS exceeds safety"
assert (CHOPCONF_DEFAULT & 0xF) <= SAFETY_TOFF_MAX, "CHOPCONF TOFF exceeds safety"


def _parse_gpio(pin: str) -> tuple[str, int]:
    """Parse 'GPIO5_IO07' -> ('/dev/gpiochip4', 7)."""
    parts = pin.split('_IO')
    chip_path = _GPIO_CHIP_MAP.get(parts[0])
    if chip_path is None:
        raise ValueError(f"Unknown GPIO bank: {parts[0]}")
    offset = int(parts[1])
    return chip_path, offset


# Init sequence — write order matters for chopper enable
_INIT_SEQ = [
    ('CHOPCONF', 0x04, CHOPCONF_DEFAULT),
    ('SMARTEN',  0x05, SMARTEN_DEFAULT),
    ('DRVCONF',  0x07, DRVCONF_DEFAULT),
    ('DRVCTRL',  0x00, 0x00300),
    ('SGCSCONF', 0x06, SGCSCONF_DEFAULT),
]


class SpidevMotorBackend(MotorBackend):
    """Hardware backend using Linux spidev + gpiod v2 for the EVK test bench.

    Implements 3-axis manual CS toggle with SPI_NO_CS, verified working with
    Veyron 1×2A boards stacked on i.MX8MP EVK J21 header (2026-05-08).

    cs=0: LIFT, cs=1: BEND, cs=2: FEED.
    """

    def __init__(
        self,
        spi_device: str = "/dev/spidev1.0",
        spi_speed_hz: int = 50_000,
        gpio_lift_cs: str = "GPIO5_IO07",
        gpio_bend_cs: str = "GPIO3_IO22",
        gpio_feed_cs: str = "GPIO5_IO13",
        gpio_dir:     str = "GPIO3_IO23",
        pwm_step_path:   str = "/sys/class/pwm/pwmchip2/pwm0",
        pwm_step_export: str = "/sys/class/pwm/pwmchip2/export",
        # Legacy kwargs (accepted but mapped to new names for backwards compat)
        gpio_cs1: str | None = None,
        gpio_cs2: str | None = None,
        gpio_feed_step: str | None = None,
        gpio_bend_step: str | None = None,
    ) -> None:
        self._spi_device = spi_device
        self._spi_speed = spi_speed_hz
        self._pwm_path = pwm_step_path
        self._pwm_export = pwm_step_export

        # Logical name -> GPIO pin string. cs=0/1/2 -> LIFT/BEND/FEED.
        self._gpio_names = {
            'lift_cs': gpio_lift_cs,
            'bend_cs': gpio_bend_cs,
            'feed_cs': gpio_feed_cs,
            'dir':     gpio_dir,
        }
        # cs index -> logical name
        self._cs_to_name = {0: 'lift_cs', 1: 'bend_cs', 2: 'feed_cs'}

        self._spi = None
        self._gpio_requests: dict[str, object] = {}     # chip_path -> LineRequest
        self._gpio_map: dict[str, tuple[str, int]] = {} # name -> (chip, offset)

        # Position tracking by axis (compatibility with MotorBackend interface)
        self.positions: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
        self._initialized: dict[int, bool] = {0: False, 1: False, 2: False}

        # Single SPI bus → serialise all transfers to prevent concurrent
        # /api/motor/status reads from racing the running pulse_step task
        # (which would corrupt CS toggling and cause empty HTTP responses).
        self._spi_lock = asyncio.Lock()

    # -------------------------------------------------------------------
    # Persistence (axis positions survive server restarts)
    # -------------------------------------------------------------------
    def _load_state(self) -> None:
        try:
            with open(_STATE_FILE, "r") as f:
                d = json.load(f)
            saved = d.get("positions", {})
            # JSON keys are strings; restore as int axis IDs
            for k, v in saved.items():
                try:
                    self.positions[int(k)] = int(v)
                except (TypeError, ValueError):
                    pass
            log.info("Restored motor positions from %s: %s", _STATE_FILE, self.positions)
        except FileNotFoundError:
            log.info("No saved motor state at %s — starting from zero", _STATE_FILE)
        except Exception as exc:
            log.warning("Failed to load motor state (%s) — starting from zero", exc)

    def _save_state(self) -> None:
        try:
            os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
            tmp = _STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"positions": {str(k): int(v) for k, v in self.positions.items()}}, f)
            os.replace(tmp, _STATE_FILE)
        except Exception as exc:
            log.debug("Save motor state failed: %s", exc)

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------
    async def open(self) -> None:
        """Open SPI device, request GPIO lines, set SPI_NO_CS mode.

        Order is critical: SPI must be opened *before* GPIO request to
        reset spi-imx state (otherwise EBUSY on subsequent reboots).
        """
        # 1. SPI first (resets spi-imx state for clean GPIO request)
        try:
            import spidev
        except ImportError:
            log.error("spidev module not available — install python3-spidev")
            raise

        bus, dev = self._parse_spidev_path(self._spi_device)
        spi = spidev.SpiDev()
        spi.open(bus, dev)
        spi.max_speed_hz = self._spi_speed
        spi.bits_per_word = 8
        try:
            spi.mode = 3
        except OSError:
            # i.MX8MP DTS may set CS_HIGH polarity from cs-gpios
            spi.mode = 3 | 0x04
            log.warning("SPI mode 3 failed, set mode 0x7 (mode 3 + CS_HIGH)")

        # SPI_NO_CS: prevent spi-imx from toggling native CS or cs-gpios.
        # Manual CS toggle in spi_transfer() drives chip selection.
        try:
            fcntl.ioctl(
                spi.fileno(),
                _SPI_IOC_WR_MODE,
                struct.pack('B', 3 | _SPI_NO_CS),
            )
        except OSError as exc:
            log.warning("SPI_NO_CS ioctl failed (%s) — manual toggle still attempted", exc)

        # Dummy transfer to settle spi-imx state
        spi.xfer2([0, 0, 0])
        await asyncio.sleep(0.05)
        self._spi = spi
        log.info("SPI opened: %s @ %d Hz, mode 3 + NO_CS", self._spi_device, self._spi_speed)
        # Restore last known positions from disk
        self._load_state()

        # 2. GPIO request (gpiod v2)
        try:
            import gpiod
            from gpiod.line import Direction, Value
        except ImportError:
            log.error("gpiod >= 2.0 not available — install python3-gpiod")
            raise

        # Group GPIO lines by chip
        chip_lines: dict[str, dict[str, int]] = {}
        for name, gpio_str in self._gpio_names.items():
            chip_path, offset = _parse_gpio(gpio_str)
            self._gpio_map[name] = (chip_path, offset)
            chip_lines.setdefault(chip_path, {})[name] = offset

        for chip_path, lines in chip_lines.items():
            line_cfg = {}
            for name, offset in lines.items():
                # CS lines idle HIGH, DIR idle LOW
                init_value = Value.ACTIVE if name.endswith('_cs') else Value.INACTIVE
                line_cfg[offset] = gpiod.LineSettings(
                    direction=Direction.OUTPUT,
                    output_value=init_value,
                )
            req = gpiod.request_lines(
                chip_path,
                consumer="ortho-bender-spi",
                config=line_cfg,
            )
            self._gpio_requests[chip_path] = req
            log.info("GPIO chip %s: requested %s", chip_path, lines)

    async def close(self) -> None:
        """Release SPI, GPIO, PWM resources."""
        # Persist final positions
        self._save_state()
        # Stop PWM (in case still running)
        try:
            with open(f"{self._pwm_path}/enable", 'w') as f:
                f.write('0\n')
        except Exception:
            pass

        # Silence all chips before closing
        for cs in (0, 1, 2):
            try:
                await self._silence_chip(cs)
            except Exception:
                pass

        if self._spi:
            try:
                self._spi.close()
            except Exception:
                pass
        for req in self._gpio_requests.values():
            try:
                req.release()
            except Exception:
                pass

    @staticmethod
    def _parse_spidev_path(path: str) -> tuple[int, int]:
        name = path.split('spidev')[1]
        parts = name.split('.')
        return int(parts[0]), int(parts[1])

    # -------------------------------------------------------------------
    # GPIO helpers
    # -------------------------------------------------------------------
    def _gpio_set(self, name: str, high: bool) -> None:
        from gpiod.line import Value
        chip_path, offset = self._gpio_map[name]
        self._gpio_requests[chip_path].set_value(
            offset, Value.ACTIVE if high else Value.INACTIVE
        )

    def _gpio_get(self, name: str) -> bool:
        from gpiod.line import Value
        chip_path, offset = self._gpio_map[name]
        return self._gpio_requests[chip_path].get_value(offset) == Value.ACTIVE

    # -------------------------------------------------------------------
    # MotorBackend interface
    # -------------------------------------------------------------------
    async def spi_transfer(self, cs: int, data: bytes) -> bytes:
        """SPI transfer with manual CS toggle (500 us settle).

        cs=0 → LIFT, cs=1 → BEND, cs=2 → FEED.
        Serialised by self._spi_lock so concurrent callers (e.g. status
        readback during a running pulse_step) don't corrupt CS framing.
        """
        if self._spi is None:
            raise RuntimeError("SPI not opened — call open() first")

        cs_name = self._cs_to_name.get(cs)
        if cs_name is None:
            raise ValueError(f"cs={cs} out of range (0=LIFT, 1=BEND, 2=FEED)")

        def _xfer_blocking() -> bytes:
            self._gpio_set(cs_name, False)              # CS active LOW
            time.sleep(_CS_SETTLE_S)
            rx = self._spi.xfer2(list(data))
            time.sleep(_CS_SETTLE_S)
            self._gpio_set(cs_name, True)               # CS idle HIGH
            time.sleep(_CS_SETTLE_S)
            return bytes(rx)

        async with self._spi_lock:
            return await asyncio.to_thread(_xfer_blocking)

    async def set_gpio(self, pin: str, value: bool) -> None:
        for name, gpio_str in self._gpio_names.items():
            if gpio_str == pin and name in self._gpio_map:
                self._gpio_set(name, value)
                return
        log.warning("GPIO %s not in configured pins", pin)

    async def get_gpio(self, pin: str) -> bool:
        for name, gpio_str in self._gpio_names.items():
            if gpio_str == pin and name in self._gpio_map:
                return self._gpio_get(name)
        return False

    async def pulse_step_multi(
        self,
        axes: list[int],
        count: int,
        freq_hz: int,
        direction: int,
    ) -> None:
        """Generate STEP pulses simultaneously on multiple axes.

        All listed axes are initialized then driven by the same PWM4 STEP
        signal (parallel wiring). 3-axis simultaneous is conservative:
        hz clamped to 4000, slow 3 s ramp for PSU transient safety.

        Faults on any axis abort all axes immediately.
        """
        if not axes:
            return
        for a in axes:
            if a not in (0, 1, 2):
                raise ValueError(f"axis {a} out of range (0/1/2)")
        # 3-axis safety: cap hz
        if len(axes) >= 2 and freq_hz > 4000:
            freq_hz = 4000
        if freq_hz < 200:
            freq_hz = 200
        count = max(1, min(count, 1_000_000))
        duration_s = count / freq_hz
        if duration_s > 30.0:
            duration_s = 30.0
            count = int(duration_s * freq_hz)

        self._gpio_set('dir', (direction > 0) != _DIR_INVERT)
        await asyncio.sleep(_DIR_SETUP_S)

        # Sequential init each axis
        for a in axes:
            await self._init_chip(a)
            status = await self._read_status(a)
            if self._has_fault(status):
                log.error("axis %d fault before run: 0x%05X — aborting", a, status)
                for ax in axes:
                    await self._silence_chip(ax)
                raise RuntimeError(f"axis {a} fault (0x{status:05X})")

        await self._pwm_ensure_exported()

        # Slow ramp 3 s with per-axis fault monitoring
        ramp_steps = 30
        ramp_sec = 3.0
        try:
            for i in range(ramp_steps):
                h = int(200 + (freq_hz - 200) * i / (ramp_steps - 1))
                await self._pwm_set_hz(h)
                for a in axes:
                    status = await self._read_status(a)
                    if self._has_fault(status):
                        log.error("axis %d fault during ramp: 0x%05X", a, status)
                        return  # finally block silences and disables PWM
                await asyncio.sleep(ramp_sec / ramp_steps)

            # Hold + monitor
            t0 = time.monotonic()
            while time.monotonic() - t0 < duration_s:
                await asyncio.sleep(0.1)
                for a in axes:
                    status = await self._read_status(a)
                    if self._has_fault(status):
                        log.error("axis %d fault during run: 0x%05X", a, status)
                        return
        finally:
            await self._pwm_disable()
            for a in axes:
                await self._silence_chip(a)

        for a in axes:
            self.positions[a] = self.positions.get(a, 0) + (count * direction)

    async def pulse_step(
        self, axis: int, count: int, freq_hz: int, direction: int
    ) -> None:
        """Generate `count` STEP pulses at `freq_hz` for `axis`.

        Implementation: PWM4 (pwmchip2/pwm0) generates parallel STEP signal
        to all 3 chips. Only the target axis is initialized; others remain
        in silenced state, so only the target motor rotates.

        Safety:
          - CS stays bounded (CHOPCONF/SGCSCONF defaults verified safe)
          - Fault flags (OT/S2G/OL) abort immediately
          - hz clamped to [200, 8000], count clamped to [1, 1_000_000]
        """
        if axis not in (0, 1, 2):
            raise ValueError(f"axis={axis} out of range (0=LIFT, 1=BEND, 2=FEED)")
        if freq_hz < 200:
            freq_hz = 200
        if freq_hz > 8000:
            freq_hz = 8000
        count = max(1, min(count, 1_000_000))
        duration_s = count / freq_hz
        if duration_s > 30.0:
            log.warning("pulse_step duration %.1fs clamped to 30s", duration_s)
            duration_s = 30.0
            count = int(duration_s * freq_hz)

        # Snapshot starting position; finally always reaches here.
        pos_before = self.positions.get(axis, 0)
        # t0 stays None until PWM actually starts ramping → safe finally.
        t0: float | None = None
        elapsed = 0.0

        try:
            # All init/PWM setup INSIDE the try so a cancellation during
            # init still triggers the finally block (silence + position
            # snapshot). This makes the 750 ms init phase cancellable.
            self._gpio_set('dir', (direction > 0) != _DIR_INVERT)
            await asyncio.sleep(_DIR_SETUP_S)
            await self._init_chip(axis)

            # Pre-run fault check
            status = await self._read_status(axis)
            if self._has_fault(status):
                log.error("axis %d fault before run: 0x%05X — aborting", axis, status)
                raise RuntimeError(f"axis {axis} fault detected (0x{status:05X})")

            # PWM4 setup — STEP signal goes live now
            await self._pwm_ensure_exported()
            await self._pwm_set_hz(freq_hz)
            t0 = time.monotonic()

            # Run + fault/stall monitoring with 100 ms polling.
            # Live position update inside the loop so the WebSocket
            # broadcast (also at 100 ms) shows real-time progress.
            stall_since: float | None = None
            STALL_TIMEOUT_S = 0.6
            while time.monotonic() - t0 < duration_s:
                await asyncio.sleep(0.1)
                elapsed = time.monotonic() - t0
                steps_so_far = min(int(elapsed * freq_hz), count)
                self.positions[axis] = pos_before + (steps_so_far * direction)

                status = await self._read_status(axis)
                if self._has_fault(status):
                    log.error("axis %d fault during run: 0x%05X — aborting", axis, status)
                    break
                if self._is_stall(status):
                    if stall_since is None:
                        stall_since = time.monotonic()
                        log.warning("axis %d stall (SG=1) — monitoring", axis)
                    elif time.monotonic() - stall_since >= STALL_TIMEOUT_S:
                        log.error("axis %d persistent stall (>%.1fs) — aborting",
                                  axis, STALL_TIMEOUT_S)
                        break
                else:
                    stall_since = None
        finally:
            # Ensure motor is silenced no matter how we exit (success,
            # cancellation, fault, exception during init).
            try:
                await self._pwm_disable()
            except Exception:
                pass
            try:
                await self._silence_chip(axis)
            except Exception:
                pass
            # Final position snapshot. If t0 was never set (cancel during
            # init), elapsed=0 and position stays at pos_before — correct
            # behaviour because no STEP edges were emitted.
            if t0 is not None:
                elapsed = max(elapsed, time.monotonic() - t0)
                steps_actual = min(int(elapsed * freq_hz), count)
                self.positions[axis] = pos_before + (steps_actual * direction)
            # Persist updated positions so a server restart resumes here
            self._save_state()

    # -------------------------------------------------------------------
    # Internal: TMC260C init / silence / status
    # -------------------------------------------------------------------
    async def _init_chip(self, cs: int) -> None:
        """Lazy init: full SEQ on first call, fast chopper re-enable after.

        TMC260C registers (CHOPCONF, SMARTEN, DRVCONF, DRVCTRL, SGCSCONF)
        are persistent in the chip until power loss or new write. Once
        initialized, subsequent silence→jog cycles only need to toggle
        CHOPCONF (TOFF) and SGCSCONF (CS) to disable/re-enable the
        chopper. This makes short button taps responsive (~15 ms vs ~375 ms).
        """
        if self._initialized.get(cs, False):
            # Fast re-enable: chopper on + current scale
            chopconf_on = self._encode(0x04, CHOPCONF_DEFAULT)
            sgcs_on     = self._encode(0x06, SGCSCONF_DEFAULT)
            tx_chop = bytes([(chopconf_on >> 16) & 0xFF, (chopconf_on >> 8) & 0xFF, chopconf_on & 0xFF])
            tx_sgcs = bytes([(sgcs_on >> 16) & 0xFF, (sgcs_on >> 8) & 0xFF, sgcs_on & 0xFF])
            for _ in range(_REENABLE_CYCLES):
                await self.spi_transfer(cs, tx_chop)
                await self.spi_transfer(cs, tx_sgcs)
            return

        # Full one-time init for a never-touched chip
        for _ in range(_INIT_SEQ_CYCLES_FULL):
            for _name, tag, value in _INIT_SEQ:
                datagram = self._encode(tag, value)
                tx = bytes([
                    (datagram >> 16) & 0xFF,
                    (datagram >> 8)  & 0xFF,
                    datagram         & 0xFF,
                ])
                await self.spi_transfer(cs, tx)
        self._initialized[cs] = True
        log.info("axis cs=%d full init done (one-time)", cs)

    async def _silence_chip(self, cs: int) -> None:
        """Disable chopper (TOFF=0) + zero current.

        Keeps the rest of the chip's register state intact so the next
        _init_chip() call can take the fast re-enable path.
        """
        # CHOPCONF=0x80000 (TOFF=0 → chopper disabled)
        chop_off = self._encode(0x04, 0x80000)
        sgcs_off = self._encode(0x06, 0xD3F00)  # CS=0
        tx_chop = bytes([
            (chop_off >> 16) & 0xFF, (chop_off >> 8) & 0xFF, chop_off & 0xFF,
        ])
        tx_sgcs = bytes([
            (sgcs_off >> 16) & 0xFF, (sgcs_off >> 8) & 0xFF, sgcs_off & 0xFF,
        ])
        for _ in range(_SILENCE_CYCLES):
            await self.spi_transfer(cs, tx_chop)
            await self.spi_transfer(cs, tx_sgcs)
        # NOTE: do NOT clear self._initialized — chip's CHOPCONF/SMARTEN/
        # DRVCONF/DRVCTRL are still in their initialized values. The next
        # _init_chip() takes the fast re-enable path.

    async def _read_status(self, cs: int) -> int:
        """Read 20-bit status by sending DRVCONF (RDSEL=01 → SG_VAL)."""
        datagram = self._encode(0x07, DRVCONF_DEFAULT & 0x1FFFF)
        tx = bytes([
            (datagram >> 16) & 0xFF, (datagram >> 8) & 0xFF, datagram & 0xFF,
        ])
        rx = await self.spi_transfer(cs, tx)
        return ((rx[0] << 16) | (rx[1] << 8) | rx[2]) & 0xFFFFF

    @staticmethod
    def _has_fault(status: int) -> bool:
        """Check OT/OTPW/S2GA/S2GB/OLA/OLB bits (bit 1..6).

        SG (bit 0, StallGuard2 stall indicator) is intentionally NOT
        treated as a hard fault here — the StallGuard2 threshold can
        trip transiently during normal acceleration and on uneven loads.
        Repeated SG stalls are detected separately by _is_persistent_stall().
        """
        return bool((status & 0xFF) & 0x7E)

    @staticmethod
    def _is_stall(status: int) -> bool:
        """SG bit (StallGuard2 stall indicator)."""
        return bool(status & 0x01)

    @staticmethod
    def _encode(reg_tag: int, value: int) -> int:
        """Encode 20-bit datagram from register tag + value (mirrors tmc260c_driver)."""
        if reg_tag == 0x00:  # DRVCTRL
            return value & 0xFFFFF
        return ((reg_tag & 0x07) << 17) | (value & 0x1FFFF)

    # -------------------------------------------------------------------
    # PWM4 control (STEP signal, parallel to all 3 chips)
    # -------------------------------------------------------------------
    async def _pwm_ensure_exported(self) -> None:
        if not os.path.isdir(self._pwm_path):
            try:
                with open(self._pwm_export, 'w') as f:
                    f.write('0\n')
                await asyncio.sleep(0.05)
            except Exception as exc:
                log.error("PWM export failed: %s", exc)
                raise

    async def _pwm_set_hz(self, hz: int) -> None:
        period = int(1e9 / hz)
        duty   = period // 2
        try:
            with open(f"{self._pwm_path}/duty_cycle", 'w') as f: f.write('0\n')
            with open(f"{self._pwm_path}/period",     'w') as f: f.write(f"{period}\n")
            with open(f"{self._pwm_path}/duty_cycle", 'w') as f: f.write(f"{duty}\n")
            with open(f"{self._pwm_path}/enable",     'w') as f: f.write('1\n')
        except Exception as exc:
            log.error("PWM set %d Hz failed: %s", hz, exc)
            raise

    async def _pwm_disable(self) -> None:
        try:
            with open(f"{self._pwm_path}/enable", 'w') as f:
                f.write('0\n')
        except Exception:
            pass
