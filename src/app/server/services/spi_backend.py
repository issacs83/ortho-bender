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
    DRVCTRL_DEFAULT,
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
_INIT_SEQ_CYCLES_FULL = 50      # full init worst case: only when chip is
                                # brand-new (first jog after server start).
_INIT_SEQ_MIN_CYCLES = 5        # minimum full-init cycles before the
                                # responsive-early-exit may fire.
_INIT_GOOD_CYCLES_EXIT = 3      # consecutive cycles with a valid SPI
                                # response after which init is declared done
                                # (cuts cold-start ~525 ms → ~85 ms when the
                                # chip is powered and answering).
_REENABLE_CYCLES = 5            # fast chopper re-enable on subsequent jogs:
                                # CHOPCONF + SGCSCONF only (~15 ms total).
_SILENCE_CYCLES = 5             # chopper-off cycles between jogs.

# Soft-start ramp: acceleration-limited instead of a fixed 12-step/0.36 s
# sweep, so a small speed step reaches target almost immediately while a
# 200 → 8000 Hz jump still ramps over ~1 s. At DRVCTRL 1/16 + DEDGE,
# 8000 Hz/s ≈ 0 → 300 RPM in one second — bench-tune if an axis stalls
# during acceleration. These are the DEFAULTS; per-axis motion profiles
# (services/motion_profiles.py) override them via pulse_step(profile=).
_RAMP_ACCEL_HZ_PER_S = 8000
_RAMP_TICK_S = 0.03
_RAMP_DOWN_MAX_S = 1.0     # cap on decel ramp duration (stop responsiveness)

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


# Init sequence — write order matters for chopper enable.
# SGCSCONF is listed with the module default but _init_chip() substitutes
# the PSU-capped value at write time (see apply_current_cap()).
_INIT_SEQ = [
    ('CHOPCONF', 0x04, CHOPCONF_DEFAULT),
    ('SMARTEN',  0x05, SMARTEN_DEFAULT),
    ('DRVCONF',  0x07, DRVCONF_DEFAULT),
    ('DRVCTRL',  0x00, DRVCTRL_DEFAULT),
    ('SGCSCONF', 0x06, SGCSCONF_DEFAULT),
]


class SpidevMotorBackend(MotorBackend):
    """Hardware backend using Linux spidev + gpiod v2 for the EVK test bench.

    Implements 3-axis manual CS toggle with SPI_NO_CS, verified working with
    Veyron 1×2A boards stacked on i.MX8MP EVK J21 header (2026-05-08).

    cs=0: LIFT, cs=1: BEND, cs=2: FEED.
    """

    is_real_hardware = True

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
        gpio_limit_lift: str = "",
        gpio_limit_bend: str = "",
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
        # Limit switch inputs (PM-L25, ACTIVE LOW — divider idles ~3 V,
        # switch pulls to GND). Optional: empty pin string = not fitted.
        self._gpio_inputs: set[str] = set()
        for name, pin in (('limit_lift', gpio_limit_lift),
                          ('limit_bend', gpio_limit_bend)):
            if pin:
                self._gpio_names[name] = pin
                self._gpio_inputs.add(name)
        # cs index -> limit input name (FEED cs=2 has no switch)
        self._cs_to_limit = {0: 'limit_lift', 1: 'limit_bend'}
        # cs index -> logical name
        self._cs_to_name = {0: 'lift_cs', 1: 'bend_cs', 2: 'feed_cs'}

        self._spi = None
        self._gpio_requests: dict[str, object] = {}     # chip_path -> LineRequest
        self._gpio_map: dict[str, tuple[str, int]] = {} # name -> (chip, offset)

        # Position tracking by axis (compatibility with MotorBackend interface)
        self.positions: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
        self._initialized: dict[int, bool] = {0: False, 1: False, 2: False}

        # Lightweight signal tracking — surfaced via get_axis_signals() so
        # the Motor Control jog rows can show 12V/EN/SG/DIR/STEP LEDs.
        # `_chip_active` is the current chopper state (init→True, silence→False)
        # `_chip_responsive` is whether the chip answered SPI on probe (proxy
        #   for "VMot 12 V is up" — SPI returns 0xFF/0x00 with no power).
        # `_last_sg` is the latest StallGuard bit observed per cs.
        # `_last_dir` is the last value driven on the shared DIR line (+1/-1).
        # `_pwm_active` reflects the PWM4 enable state.
        # `_active_axis` is the cs the jog/move task is currently targeting.
        self._chip_active: dict[int, bool] = {0: False, 1: False, 2: False}
        self._chip_responsive: dict[int, bool] = {0: False, 1: False, 2: False}
        self._last_sg: dict[int, bool] = {0: False, 1: False, 2: False}
        self._last_dir: int = 0   # 0 = unknown / not driven yet
        self._pwm_active: bool = False
        # E-STOP kill latch: once set, _pwm_set_hz refuses to touch the PWM
        # (an in-flight ramp tick would otherwise re-enable STEP output
        # ≤30 ms after E-STOP killed it, until the task cancel lands).
        # Cleared only when a new legitimate motion begins in pulse_step —
        # and motion commands are gated on E-STOP reset upstream.
        self._pwm_killed: bool = False
        self._active_axis: Optional[int] = None

        # Single SPI bus → serialise all transfers to prevent concurrent
        # /api/motor/status reads from racing the running pulse_step task
        # (which would corrupt CS toggling and cause empty HTTP responses).
        self._spi_lock = asyncio.Lock()

        # PSU-derived current-scale cap (see apply_current_cap). Starts at
        # the absolute hardware limit; main.py narrows it from the active
        # PSU preset so _init_chip never writes a CS the supply can't feed.
        self._cs_scale_cap: int = SAFETY_CS_MAX

        # Gravity-axis holding: cs values in hold_axes stay energized at
        # hold_cs while idle (LIFT sinks when de-energized). The shared
        # STEP line means a held chip steps along with any active axis,
        # so held axes are released for the duration of other-axis motion
        # and re-held afterwards. main.py populates from config.
        self.hold_axes: set[int] = set()
        self.hold_cs: int = 8

        # Limit guard: stop an axis that ENTERS its limit window during
        # normal motion (edge-triggered; starting inside the window keeps
        # the guard disarmed until the axis leaves it). Toggled via
        # PUT /api/motor/protection.
        self.limit_guard: bool = True

        # Axes homed against their switch — persisted with positions so a
        # restart keeps both the counter and its "datum is real" status.
        self.homed_persist: set[int] = set()

        # PWM sysfs write-state (see _pwm_set_hz): avoids the
        # duty=0 → enable re-toggle on every ramp tick, which produced up
        # to one dead period of STEP output per tick.
        self._pwm_enabled: bool = False
        self._pwm_last_period_ns: int = 0

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
            try:
                self.homed_persist = {int(x) for x in d.get("homed", [])}
            except (TypeError, ValueError):
                self.homed_persist = set()
            log.info("Restored motor positions from %s: %s (homed=%s)",
                     _STATE_FILE, self.positions, sorted(self.homed_persist))
        except FileNotFoundError:
            log.info("No saved motor state at %s — starting from zero", _STATE_FILE)
        except Exception as exc:
            log.warning("Failed to load motor state (%s) — starting from zero", exc)

    def _save_state(self) -> None:
        try:
            os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
            tmp = _STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({
                    "positions": {str(k): int(v) for k, v in self.positions.items()},
                    "homed": sorted(self.homed_persist),
                }, f)
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
                if name in self._gpio_inputs:
                    # Limit switches: input, no bias — the external divider
                    # (~500 Ω Thevenin) defines the level.
                    line_cfg[offset] = gpiod.LineSettings(
                        direction=Direction.INPUT,
                    )
                else:
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
        # Track DIR for the LED row. The actual logical direction is the
        # raw pin value XORed with _DIR_INVERT — see pulse_step() which
        # applies the same XOR before driving the line.
        if name == 'dir':
            logical_pos = (high != _DIR_INVERT)
            self._last_dir = +1 if logical_pos else -1

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

        self._pwm_killed = False   # new motion — clear E-STOP kill latch
        # Shared STEP: held axes not taking part must be released first.
        for h in self.hold_axes - set(axes):
            if self._chip_active.get(h):
                await self._silence_chip(h)
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
                if a in self.hold_axes and not self._pwm_killed:
                    await self._hold_chip(a)
                else:
                    await self._silence_chip(a)
            if not self._pwm_killed:
                for h in self.hold_axes - set(axes):
                    try:
                        await self._hold_chip(h)
                    except Exception as exc:
                        log.warning("re-hold cs=%d failed: %s", h, exc)

        for a in axes:
            self.positions[a] = self.positions.get(a, 0) + (count * direction)

    async def pulse_step(
        self, axis: int, count: int, freq_hz: int, direction: int,
        profile: dict | None = None,
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
            self._pwm_killed = False   # new motion — clear E-STOP kill latch
            self._active_axis = axis
            await self._yield_held(axis)   # shared STEP: release held axes
            self._gpio_set('dir', (direction > 0) != _DIR_INVERT)
            await asyncio.sleep(_DIR_SETUP_S)
            await self._init_chip(axis)

            # Pre-run fault check
            status = await self._read_status(axis)
            if self._has_fault(status):
                log.error("axis %d fault before run: 0x%05X — aborting", axis, status)
                raise RuntimeError(f"axis {axis} fault detected (0x{status:05X})")

            # PWM4 setup — STEP signal goes live now.
            # Acceleration-limited soft start (per-axis motion profile:
            # start floor, accel rate, linear vs S-curve shape). A small
            # speed change reaches target in ~one tick while a full jump
            # ramps at the configured acceleration.
            p = profile or {}
            start_hz = int(p.get("start_hz", 200))
            accel = float(p.get("accel_hz_s", _RAMP_ACCEL_HZ_PER_S))
            decel = float(p.get("decel_hz_s", _RAMP_ACCEL_HZ_PER_S))
            shape = p.get("shape", "linear")
            await self._pwm_ensure_exported()
            h = min(start_hz, freq_hz)
            floor_hz = h
            # Short-move peak cap: limit the cruise frequency so that
            # accel + decel alone cannot exceed the commanded step count
            # (triangle profile). Without this a 0.2-unit tap ramps to
            # full speed and the two ramps overshoot the move ~2-3x.
            if accel > 0 and decel > 0:
                denom = 1.0 / (2.0 * accel) + 1.0 / (2.0 * decel)
                f_reach = int((floor_hz * floor_hz + count / denom) ** 0.5)
                if f_reach < freq_hz:
                    freq_hz = max(floor_hz, f_reach)
            span = max(0, freq_hz - floor_hz)
            # Decel rate: honour the profile but never take longer than
            # _RAMP_DOWN_MAX_S so a stop always feels responsive.
            eff_decel = max(decel, span / _RAMP_DOWN_MAX_S) if span else decel
            # Limit-switch guard (edge-triggered, armed only once the axis
            # is outside its window): shared between the ramp (10 ms
            # sub-polling) and the cruise monitor. A fast axis crosses
            # the ~0.7 u window in tens of ms — the old 100 ms-only
            # check could fly straight through without noticing.
            guard = {"armed": self.limit_guard and self.limit_active(axis) is False,
                     "hit": False}

            def guard_check() -> bool:
                if not self.limit_guard or guard["hit"]:
                    return guard["hit"]
                lim = self.limit_active(axis)
                if lim is False:
                    guard["armed"] = True
                elif lim and guard["armed"]:
                    guard["hit"] = True
                return guard["hit"]

            await self._pwm_set_hz(h)
            # Ramp-up with live step accounting: everything emitted during
            # the ramp counts toward both the position display AND the
            # commanded distance (a short jog can complete entirely inside
            # the ramp — it used to be invisible and to overshoot ~2x).
            ramp_up = await self._ramp(h, freq_hz, accel, shape,
                                       track=(axis, direction),
                                       guard_cb=guard_check)
            # Budget the natural-end decel ramp too, so ramp+cruise+decel
            # lands near the commanded step count.
            if span and eff_decel > 0:
                decel_t = (1.5 if shape == "scurve" else 1.0) * span / eff_decel
                decel_est = int((freq_hz + floor_hz) / 2.0 * decel_t)
            else:
                decel_est = 0
            remaining = max(0, count - ramp_up - decel_est)
            if guard["hit"]:
                remaining = 0   # guard fired inside the ramp — go stop
            duration_s = remaining / freq_hz
            pos_mid = self.positions.get(axis, 0)
            t0 = time.monotonic()

            # Cruise + monitoring: limit guard and position at 10 ms
            # (a fast axis crosses its sensor window in tens of ms),
            # SPI fault/stall reads at 100 ms.
            stall_since: float | None = None
            STALL_TIMEOUT_S = 0.6
            clean_end = True
            next_status_t = 0.0
            try:
                while time.monotonic() - t0 < duration_s:
                    await asyncio.sleep(0.01)
                    elapsed = time.monotonic() - t0
                    steps_so_far = min(int(elapsed * freq_hz), remaining)
                    self.positions[axis] = pos_mid + (steps_so_far * direction)

                    if guard_check():
                        log.warning("axis %d limit switch tripped mid-motion "
                                    "— stopping (limit guard)", axis)
                        break   # clean_end stays True → decel stop
                    if elapsed < next_status_t:
                        continue
                    next_status_t = elapsed + 0.1
                    status = await self._read_status(axis)
                    if self._has_fault(status):
                        log.error("axis %d fault during run: 0x%05X — aborting", axis, status)
                        clean_end = False   # faults halt hard, no decel
                        break
                    if self._is_stall(status):
                        if stall_since is None:
                            stall_since = time.monotonic()
                            log.warning("axis %d stall (SG=1) — monitoring", axis)
                        elif time.monotonic() - stall_since >= STALL_TIMEOUT_S:
                            log.error("axis %d persistent stall (>%.1fs) — aborting",
                                      axis, STALL_TIMEOUT_S)
                            clean_end = False
                            break
                    else:
                        stall_since = None
                else:
                    # Natural end: settle the cruise-phase count exactly.
                    self.positions[axis] = pos_mid + (remaining * direction)
            except asyncio.CancelledError:
                # Graceful stop (jog_stop / task cancel): decelerate before
                # the finally block silences the chopper — UNLESS E-STOP
                # already killed the PWM (self._pwm_active False), in which
                # case the motor is electrically stopped and any ramp here
                # would delay the safety path.
                # Settle the cruise steps emitted since the last 100 ms
                # tick before the decel ramp takes over the accounting.
                elapsed = time.monotonic() - t0
                self.positions[axis] = pos_mid + (
                    min(int(elapsed * freq_hz), remaining) * direction)
                if self._pwm_active:
                    try:
                        await self._ramp(freq_hz, floor_hz, eff_decel, shape,
                                         track=(axis, direction))
                    except Exception:
                        pass
                raise
            # Controlled stop (natural end / limit guard): decelerate to
            # the floor so high-speed jogs don't slam to zero
            # (missed-step/resonance risk at 1/16 microstep speeds).
            # The guard may fire inside the ramp-up, so start the decel
            # from the frequency the PWM is actually at.
            if clean_end and self._pwm_active:
                cur_hz = freq_hz
                if self._pwm_last_period_ns:
                    cur_hz = min(freq_hz, max(floor_hz,
                                 int(1e9 / self._pwm_last_period_ns)))
                await self._ramp(cur_hz, floor_hz, eff_decel, shape,
                                 track=(axis, direction))
        finally:
            # Ensure motor is safe no matter how we exit (success,
            # cancellation, fault, exception during init): gravity axes
            # go to reduced-current hold, the rest are silenced, and
            # released bystanders are re-held (all skipped after E-STOP).
            try:
                await self._pwm_disable()
            except Exception:
                pass
            await self._finish_axis(axis)
            # Positions are maintained LIVE through every phase (ramp-up
            # integral, cruise ticks, decel integral) — no end-of-motion
            # recompute, which used to erase everything a short jog did
            # inside its ramp. pos_before/t0 remain for log context only.
            _ = pos_before, t0
            # Persist updated positions so a server restart resumes here
            self._save_state()
            # Clear active_axis after this jog/move ends so the STEP LED
            # only highlights an axis while its motion is in flight.
            if self._active_axis == axis:
                self._active_axis = None

    # -------------------------------------------------------------------
    # Signal helpers (LED row on the dashboard)
    # -------------------------------------------------------------------
    def get_axis_signals(self, cs: int) -> dict:
        """Return a snapshot of the five LED signals for one cs.

        - vmot:  chip last responded on SPI → VMot 12 V is up.
        - en:    chopper currently ON for this cs (init done, not silenced).
        - sg:    StallGuard bit at last DRV_STATUS read for this cs.
                 Note: while a chip is silenced (no coil current) SG reads as
                 1 because StallGuard interprets zero current as a stall.
                 The frontend can mask this by checking `en`.
        - dir:   +1 / -1 — last logical direction driven on the shared DIR
                 line. 0 means "never driven yet". Only meaningful for the
                 axis that PWM is currently targeting.
        - step:  PWM4 enabled AND this cs is the active axis. STEP signal
                 reaches every chip in parallel, but only the chopper-on
                 (en=1) chip responds — so we tag step=1 only on the cs
                 that is the current target.
        """
        return {
            "vmot": bool(self._chip_responsive.get(cs, False)),
            "en":   bool(self._chip_active.get(cs, False)),
            "sg":   bool(self._last_sg.get(cs, False)),
            "dir":  int(self._last_dir),
            "step": bool(self._pwm_active and self._active_axis == cs),
            "limit": self.limit_active(cs),
        }

    # -------------------------------------------------------------------
    # Gravity-axis holding
    # -------------------------------------------------------------------
    async def _hold_chip(self, cs: int) -> None:
        """Energize `cs` at reduced holding current (idle gravity hold)."""
        cap = self._cs_scale_cap
        try:
            self.apply_current_cap(min(cap, int(self.hold_cs)))
            await self._init_chip(cs)
        finally:
            self.apply_current_cap(cap)

    async def _yield_held(self, active_cs: int) -> None:
        """Release held axes before motion on another axis — the shared
        STEP line would step every energized chip in parallel."""
        for h in self.hold_axes - {active_cs}:
            if self._chip_active.get(h):
                try:
                    await self._silence_chip(h)
                except Exception as exc:
                    log.warning("yield held cs=%d failed: %s", h, exc)

    async def _finish_axis(self, cs: int) -> None:
        """End-of-motion chip handling: hold gravity axes, silence the
        rest, then re-hold released bystanders. After E-STOP
        (_pwm_killed) everything stays silenced — re-energizing here
        would undo the E-STOP's chip silencing."""
        try:
            if cs in self.hold_axes and not self._pwm_killed:
                await self._hold_chip(cs)
            else:
                await self._silence_chip(cs)
        except Exception:
            pass
        if not self._pwm_killed:
            for h in self.hold_axes - {cs}:
                try:
                    await self._hold_chip(h)
                except Exception as exc:
                    log.warning("re-hold cs=%d failed: %s", h, exc)

    # -------------------------------------------------------------------
    # Limit switches + homing
    # -------------------------------------------------------------------
    def limit_active(self, cs: int) -> bool | None:
        """Live limit switch state for one cs (True = tripped).

        ACTIVE LOW: the PM-L25 divider idles high (~3 V) and the sensor
        pulls the line to GND when the flag enters the slot. Returns None
        when the axis has no switch fitted (FEED) or GPIO isn't up yet.
        """
        name = self._cs_to_limit.get(cs)
        if name is None or name not in self._gpio_inputs:
            return None
        chip_path, _ = self._gpio_map.get(name, (None, None))
        if chip_path is None or chip_path not in self._gpio_requests:
            return None
        try:
            return not self._gpio_get(name)
        except Exception:
            return None

    def _limit_tripped_debounced(self, cs: int) -> bool:
        """Two consecutive reads agree — rejects single-sample noise."""
        return bool(self.limit_active(cs)) and bool(self.limit_active(cs))

    async def _home_move(
        self, cs: int, direction: int, freq_hz: int,
        max_steps: int, stop_when: str | None,
        fault_check_s: float = 0.25,
        stall_abort: bool = False,
    ) -> tuple[bool, int]:
        """One homing segment: run STEP at `freq_hz` until the limit
        condition is met or `max_steps` elapse.

        stop_when: 'trip' → stop when switch goes active,
                   'release' → stop when switch goes inactive,
                   None → run exactly max_steps (fixed distance).
        Returns (condition_met, steps_done). PWM stops dead at the end of
        every segment — homing speeds sit inside the motor's self-start
        region, so no ramp is needed and the stop is step-accurate to one
        poll interval.
        """
        poll_s = 0.005
        self._gpio_set('dir', (direction > 0) != _DIR_INVERT)
        self._last_dir = 1 if direction > 0 else -1
        await asyncio.sleep(_DIR_SETUP_S)
        await self._pwm_ensure_exported()
        pos_start = self.positions.get(cs, 0)
        await self._pwm_set_hz(freq_hz)
        t0 = time.monotonic()
        met = False
        steps = 0
        next_fault_t = fault_check_s
        sg_hits = 0
        try:
            while steps < max_steps:
                await asyncio.sleep(poll_s)
                elapsed = time.monotonic() - t0
                steps = min(int(elapsed * freq_hz), max_steps)
                self.positions[cs] = pos_start + steps * (1 if direction > 0 else -1)
                if stop_when == 'trip' and self._limit_tripped_debounced(cs):
                    met = True
                    break
                if stop_when == 'release' and self.limit_active(cs) is False:
                    met = True
                    break
                if elapsed >= next_fault_t:
                    next_fault_t += fault_check_s
                    status = await self._read_status(cs)
                    if self._has_fault(status):
                        raise RuntimeError(
                            f"axis cs={cs} fault during homing (0x{status:05X})")
                    if stall_abort:
                        # StallGuard as a virtual limit switch (abort only,
                        # never the datum — AN-002). Two consecutive SG
                        # readings = mechanical contact: stop this leg as
                        # if the travel bound was reached.
                        if self._last_sg.get(cs):
                            sg_hits += 1
                            if sg_hits >= 2:
                                log.warning("home_move cs=%d: stall detected "
                                            "after %d steps — leg aborted", cs, steps)
                                break
                        else:
                            sg_hits = 0
        finally:
            await self._pwm_disable()
            self.positions[cs] = pos_start + steps * (1 if direction > 0 else -1)
        return met, steps

    async def home_axis(
        self, cs: int, direction: int,
        seek_hz: int, latch_hz: int, backoff_steps: int,
        timeout_s: float = 60.0, park_steps: int = 0,
        max_travel_steps: int | None = None,
        search_range_steps: int | None = None,
        reduced_cs: int = 0,
        rotary: bool = False,
        preprobe_steps: int = 0,
        stall_abort: bool = False,
    ) -> None:
        """Home one axis against its mid-travel window sensor.

        Bidirectional search per CiA 402 methods 23-30 (adapted for a
        soft travel bound instead of end limit switches), with GRBL-style
        two-pass latching:

        S1 RELEASE   on the switch? retreat (-dir) until clear + backoff.
        S2 PRIMARY   seek in `direction`, bounded by search_range_steps —
                     the flag can rest on EITHER side of the window, so
                     "not found within the primary leg" usually means
                     wrong side, NOT a fault.
        S3 REVERSE   seek in -direction across the whole travel
                     (max_travel_steps). Still nothing → sensor fault.
        S4 CANONICAL back off (-dir) until released + backoff. Whichever
                     leg found the window, this exits it on the SAME side,
                     so the latch always approaches from one direction —
                     required because the PM-L25's 0.05 mm hysteresis and
                     asymmetric 20/80 µs response make mixed-direction
                     datums several times worse than its 0.01 mm spec.
        S5 LATCH     slow approach in `direction`; datum = trip edge.
        S6 PARK      park_steps=0 rests exactly on the trip point (this
                     machine's home pose IS the switch position);
                     park_steps>0 = conventional pull-off.

        reduced_cs > 0 temporarily narrows the current-scale cap during
        homing (Duet M913 / Marlin *_CURRENT_HOME practice) so any
        hard-stop contact stalls gently. Do NOT use on gravity axes.

        Runs as the bench motion task: jog_stop / E-STOP cancel it, and
        the finally block silences the chip either way.
        """
        if self.limit_active(cs) is None:
            raise RuntimeError(f"axis cs={cs} has no limit switch configured")
        direction = 1 if direction > 0 else -1
        seek_hz = max(200, min(int(seek_hz), 2000))
        latch_hz = max(50, min(int(latch_hz), 500))
        backoff_steps = max(20, int(backoff_steps))
        # Travel bounds. Release moves are capped at a flag-length
        # (10 backoffs): a switch that will not free within that is stuck.
        if max_travel_steps is None:
            max_travel_steps = int(50 * 200)   # conservative 50-unit default
        if search_range_steps is None:
            search_range_steps = max_travel_steps
        max_primary = min(int(timeout_s * seek_hz), search_range_steps)
        max_reverse = min(int(timeout_s * seek_hz), max_travel_steps)
        max_release = backoff_steps * 10
        self._pwm_killed = False   # new motion — clear E-STOP kill latch
        self._active_axis = cs
        cap_before = self._cs_scale_cap
        try:
            await self._yield_held(cs)   # shared STEP: release held axes
            if reduced_cs > 0:
                # Narrow (never widen) the cap so _init_chip writes a
                # gentler CS for the homing moves; restored in finally.
                self.apply_current_cap(min(cap_before, int(reduced_cs)))
            await self._init_chip(cs)
            status = await self._read_status(cs)
            if self._has_fault(status):
                raise RuntimeError(f"axis cs={cs} fault before homing (0x{status:05X})")

            # S1 — clear the switch if we're starting on it
            if self._limit_tripped_debounced(cs):
                met, _ = await self._home_move(
                    cs, -direction, seek_hz, max_release, 'release')
                if not met:
                    raise RuntimeError(
                        f"axis cs={cs} limit stuck active — sensor/wiring "
                        f"suspect, aborting after bounded retreat")
                await self._home_move(cs, -direction, seek_hz, backoff_steps, None)
            elif preprobe_steps > 0 and not rotary:
                # S1b — pre-probe AGAINST the approach direction: on a
                # gravity axis the common off-window start is "sank just
                # below the window", and the primary leg would dive into
                # the bottom stop. A short opposite probe catches that
                # case without ever touching the stop.
                met, _ = await self._home_move(
                    cs, -direction, seek_hz, preprobe_steps, 'trip')
                if met:
                    log.info("home_axis cs=%d: window found on pre-probe", cs)
                    met, _ = await self._home_move(
                        cs, -direction, seek_hz, max_release, 'release')
                    if not met:
                        raise RuntimeError(
                            f"axis cs={cs} limit did not release after "
                            f"pre-probe — sensor stuck")
                    await self._home_move(
                        cs, -direction, seek_hz, backoff_steps, None)

            if not self._limit_tripped_debounced(cs):
                # S2 — primary seek. Rotary axis: one window per
                # revolution, so a single leg bounded at 1 rev + margin
                # ALWAYS crosses it — no reversal exists to need.
                met, _ = await self._home_move(
                    cs, direction, seek_hz, max_primary, 'trip',
                    stall_abort=stall_abort)
                if not met and rotary:
                    raise RuntimeError(
                        f"axis cs={cs} window not seen within one full "
                        f"revolution — check sensor power/wiring")
                if not met:
                    # S3 — linear axis on the wrong side: reverse and
                    # search the whole travel. The primary leg may have
                    # wedged the carriage into a hard stop, so break away
                    # slowly for the first stretch before full seek speed.
                    log.info("home_axis cs=%d: window not in primary leg "
                             "(%d steps) — reversing", cs, max_primary)
                    met, _ = await self._home_move(
                        cs, -direction, latch_hz, backoff_steps * 2, 'trip')
                    if not met:
                        met, _ = await self._home_move(
                            cs, -direction, seek_hz, max_reverse, 'trip',
                            stall_abort=stall_abort)
                    if not met:
                        raise RuntimeError(
                            f"axis cs={cs} home window not found in either "
                            f"direction — check sensor power/wiring")

            # S4 — canonicalize: exit the window on the -direction side
            # (works for both legs: primary entered from -dir and backs
            # out; reverse entered from +dir and crosses through).
            met, _ = await self._home_move(
                cs, -direction, seek_hz, max_release, 'release')
            if not met:
                raise RuntimeError(
                    f"axis cs={cs} limit did not release on backoff — "
                    f"sensor stuck, aborting")
            await self._home_move(cs, -direction, seek_hz, backoff_steps, None)

            # 4) Slow latch pass
            met, _ = await self._home_move(
                cs, direction, latch_hz,
                backoff_steps * 4 + int(2.0 * latch_hz), 'trip')
            if not met:
                raise RuntimeError(f"axis cs={cs} latch pass missed the switch")

            # 5) Datum at the (repeatable) slow trip point
            self.positions[cs] = 0

            # 6) Park. >0 = conventional pull-off (outside the window),
            # <0 = advance INSIDE the window so the sensor reads solidly
            # tripped at rest — the trip edge itself sits inside the
            # sensor's hysteresis band and reads clear/tripped at random
            # (observed live: BEND parked at 0 read clear, LIFT tripped).
            if park_steps > 0:
                await self._home_move(cs, -direction, seek_hz, park_steps, None)
            elif park_steps < 0:
                await self._home_move(cs, direction, latch_hz, -park_steps, None)
            log.info("home_axis cs=%d complete: datum set, resting at %+d steps",
                     cs, self.positions[cs])
        finally:
            # Restore the run current cap narrowed for reduced-CS homing.
            if reduced_cs > 0:
                self.apply_current_cap(cap_before)
            try:
                await self._pwm_disable()
            except Exception:
                pass
            await self._finish_axis(cs)
            self._save_state()
            if self._active_axis == cs:
                self._active_axis = None

    # -------------------------------------------------------------------
    # Internal: TMC260C init / silence / status
    # -------------------------------------------------------------------
    def apply_current_cap(self, cs_cap: int) -> None:
        """Narrow the SGCSCONF current scale written by _init_chip.

        Called by main.py with PsuService.cs_cap (and again whenever the
        operator changes the PSU preset). Without this, every jog wrote
        SGCSCONF_DEFAULT (CS=19) regardless of the selected supply — the
        UnsafeRegisterWrite guard only protects the /diag/register path.
        The cap only ever narrows: it is clamped to SAFETY_CS_MAX.
        """
        capped = max(0, min(int(cs_cap), SAFETY_CS_MAX))
        if capped != self._cs_scale_cap:
            log.info("SGCSCONF current cap: CS ≤ %d (PSU-derived)", capped)
        self._cs_scale_cap = capped

    def _sgcs_on_value(self) -> int:
        """SGCSCONF with the current scale limited to the PSU cap."""
        default_cs = SGCSCONF_DEFAULT & 0x1F
        cs = min(default_cs, self._cs_scale_cap)
        return (SGCSCONF_DEFAULT & ~0x1F) | cs

    async def _init_chip(self, cs: int) -> None:
        """Lazy init: full SEQ on first call, fast chopper re-enable after.

        TMC260C registers (CHOPCONF, SMARTEN, DRVCONF, DRVCTRL, SGCSCONF)
        are persistent in the chip until power loss or new write. Once
        initialized, subsequent silence→jog cycles only need to toggle
        CHOPCONF (TOFF) and SGCSCONF (CS) to disable/re-enable the
        chopper. This makes short button taps responsive (~15 ms vs ~375 ms).

        The full init loop exits early once the chip has produced
        _INIT_GOOD_CYCLES_EXIT consecutive valid SPI responses (after a
        minimum of _INIT_SEQ_MIN_CYCLES cycles) — an unpowered or absent
        chip returns 0x00000/0xFFFFF and still gets the full 50 cycles.
        """
        if self._initialized.get(cs, False):
            # Fast re-enable: chopper on + current scale
            chopconf_on = self._encode(0x04, CHOPCONF_DEFAULT)
            sgcs_on     = self._encode(0x06, self._sgcs_on_value())
            tx_chop = bytes([(chopconf_on >> 16) & 0xFF, (chopconf_on >> 8) & 0xFF, chopconf_on & 0xFF])
            tx_sgcs = bytes([(sgcs_on >> 16) & 0xFF, (sgcs_on >> 8) & 0xFF, sgcs_on & 0xFF])
            for _ in range(_REENABLE_CYCLES):
                await self.spi_transfer(cs, tx_chop)
                await self.spi_transfer(cs, tx_sgcs)
            self._chip_active[cs] = True
            self._chip_responsive[cs] = True
            return

        # Full one-time init for a never-touched chip
        good_cycles = 0
        for cycle in range(_INIT_SEQ_CYCLES_FULL):
            rx = b"\x00\x00\x00"
            for _name, tag, value in _INIT_SEQ:
                if tag == 0x06:  # SGCSCONF: substitute PSU-capped value
                    value = self._sgcs_on_value()
                datagram = self._encode(tag, value)
                tx = bytes([
                    (datagram >> 16) & 0xFF,
                    (datagram >> 8)  & 0xFF,
                    datagram         & 0xFF,
                ])
                rx = await self.spi_transfer(cs, tx)
            status = ((rx[0] << 16) | (rx[1] << 8) | rx[2]) & 0xFFFFF
            if status not in (0x00000, 0xFFFFF):
                good_cycles += 1
            else:
                good_cycles = 0
            if (cycle + 1 >= _INIT_SEQ_MIN_CYCLES
                    and good_cycles >= _INIT_GOOD_CYCLES_EXIT):
                log.info("axis cs=%d init early-exit after %d cycles", cs, cycle + 1)
                break
        self._initialized[cs] = True
        self._chip_active[cs] = True
        self._chip_responsive[cs] = True
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
        # Mark chopper-off for the LED row; chip is still considered
        # responsive (we just talked to it).
        self._chip_active[cs] = False
        self._chip_responsive[cs] = True

    async def _read_status(self, cs: int) -> int:
        """Read 20-bit status by sending DRVCONF (RDSEL=01 → SG_VAL)."""
        datagram = self._encode(0x07, DRVCONF_DEFAULT & 0x1FFFF)
        tx = bytes([
            (datagram >> 16) & 0xFF, (datagram >> 8) & 0xFF, datagram & 0xFF,
        ])
        rx = await self.spi_transfer(cs, tx)
        status = ((rx[0] << 16) | (rx[1] << 8) | rx[2]) & 0xFFFFF
        # Cache SG bit + responsiveness for the LED row. SPI lines float
        # to 0xFF when VMot is dead, so a 0xFFFFF read means "no power".
        self._chip_responsive[cs] = (status != 0xFFFFF and status != 0)
        self._last_sg[cs] = bool(status & 0x01)
        return status

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
    async def _ramp(self, f_from: int, f_to: int, rate_hz_s: float,
                    shape: str = "linear",
                    track: tuple[int, int] | None = None,
                    guard_cb=None) -> int:
        """Slew the PWM frequency f_from → f_to. Returns the estimated
        STEP edges emitted (trapezoid integral of the schedule);
        track=(cs, direction) live-updates the position counter each tick.

        linear: constant slope = rate_hz_s (trapezoidal velocity).
        scurve: smoothstep schedule f(τ) = f0 + Δf·(3τ²−2τ³) — jerk-
        limited with C1-continuous acceleration; T is chosen so the PEAK
        slope equals rate_hz_s (smoothness never exceeds the configured
        acceleration). At the ~30 ms tick this is a frequency schedule,
        not per-step shaping — adequate for the bench PWM path.
        """
        span = abs(f_to - f_from)
        if span == 0 or rate_hz_s <= 0:
            await self._pwm_set_hz(f_to)
            return 0
        if shape == "scurve":
            total_s = 1.5 * span / rate_hz_s   # smoothstep peak slope = 1.5·Δf/T
        else:
            total_s = span / rate_hz_s
        total_s = max(total_s, _RAMP_TICK_S)

        def emitted(elapsed_s: float) -> int:
            """Closed-form ∫f dt over [0, elapsed] of the schedule —
            counts partial ticks, so even a cancel a few ms into the
            ramp credits the STEP edges that were actually emitted."""
            e = max(0.0, min(elapsed_s, total_s))
            tau = e / total_s
            df = f_to - f_from
            if shape == "scurve":
                # ∫(3τ²-2τ³)dτ = τ³ - τ⁴/2
                integ = tau ** 3 - tau ** 4 / 2.0
            else:
                integ = tau * tau / 2.0
            return int(f_from * e + df * total_s * integ)

        t = 0.0
        t_wall = time.monotonic()
        base = self.positions.get(track[0], 0) if track else 0
        aborted = False
        try:
            while t < total_s and not aborted:
                # Sub-sleep in 10 ms slices so the limit guard can react
                # inside a tick — a fast axis crosses its sensor window
                # in a few tens of ms.
                slept = 0.0
                while slept < _RAMP_TICK_S:
                    await asyncio.sleep(0.01)
                    slept += 0.01
                    if guard_cb is not None and guard_cb():
                        aborted = True
                        break
                if aborted:
                    break
                t = min(total_s, t + _RAMP_TICK_S)
                tau = t / total_s
                s = tau * tau * (3.0 - 2.0 * tau) if shape == "scurve" else tau
                await self._pwm_set_hz(int(round(f_from + (f_to - f_from) * s)))
                if track:
                    self.positions[track[0]] = base + emitted(
                        time.monotonic() - t_wall) * track[1]
        finally:
            # Wall-clock accounting: whatever actually elapsed (complete
            # ticks, a truncated tick, or a cancel mid-sleep) is what the
            # PWM emitted. Without this a quick jog tap that dies inside
            # the ramp shows zero displacement while the motor moved.
            if track:
                self.positions[track[0]] = base + emitted(
                    time.monotonic() - t_wall) * track[1]
        return emitted(time.monotonic() - t_wall)

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
        """Program the PWM to `hz` without gapping a running STEP train.

        First activation uses the safe duty=0 → period → duty → enable
        order. While already enabled, only period/duty are rewritten, in
        an order that keeps duty_cycle ≤ period at every instant (the
        sysfs PWM API rejects the write otherwise):
          - period grows:  write period first, then duty
          - period shrinks: write duty first (new duty < old period), then period
        The previous implementation re-ran the full duty=0/enable dance on
        every ramp tick — up to one dead STEP period per tick, i.e. lost
        steps 12× per soft-start.
        """
        if self._pwm_killed:
            return   # E-STOP killed the PWM; ignore ramp ticks until cancel lands
        period = int(1e9 / hz)
        duty   = period // 2
        try:
            if not self._pwm_enabled:
                with open(f"{self._pwm_path}/duty_cycle", 'w') as f: f.write('0\n')
                with open(f"{self._pwm_path}/period",     'w') as f: f.write(f"{period}\n")
                with open(f"{self._pwm_path}/duty_cycle", 'w') as f: f.write(f"{duty}\n")
                with open(f"{self._pwm_path}/enable",     'w') as f: f.write('1\n')
                self._pwm_enabled = True
            elif period >= self._pwm_last_period_ns:
                with open(f"{self._pwm_path}/period",     'w') as f: f.write(f"{period}\n")
                with open(f"{self._pwm_path}/duty_cycle", 'w') as f: f.write(f"{duty}\n")
            else:
                with open(f"{self._pwm_path}/duty_cycle", 'w') as f: f.write(f"{duty}\n")
                with open(f"{self._pwm_path}/period",     'w') as f: f.write(f"{period}\n")
            self._pwm_last_period_ns = period
            self._pwm_active = True
        except Exception as exc:
            log.error("PWM set %d Hz failed: %s", hz, exc)
            self._pwm_enabled = False
            raise

    async def _pwm_disable(self, kill: bool = False) -> None:
        """Stop STEP output. kill=True (E-STOP path) also latches the PWM
        off so concurrent ramp ticks cannot re-enable it."""
        if kill:
            self._pwm_killed = True
        try:
            with open(f"{self._pwm_path}/enable", 'w') as f:
                f.write('0\n')
        except Exception:
            pass
        self._pwm_active = False
        self._pwm_enabled = False
