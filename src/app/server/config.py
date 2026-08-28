"""
config.py — Application configuration loaded from environment variables.

All settings have safe defaults for development (mock mode, localhost).
Production values are supplied via .env file or systemd Environment= directives.

IEC 62304 SW Class: B
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ------------------------------------------------------------------
    # Server
    # ------------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    cors_origins: list[str] = ["*"]

    # ------------------------------------------------------------------
    # Mock mode — disables all hardware access
    # ------------------------------------------------------------------
    mock_mode: bool = True

    # ------------------------------------------------------------------
    # IPC / RPMsg
    # ------------------------------------------------------------------
    ipc_device: str = "/dev/rpmsg0"
    ipc_timeout_s: float = 2.0

    # ------------------------------------------------------------------
    # Motor backend selection
    # ------------------------------------------------------------------
    motor_backend: str = "mock"  # "mock" | "spidev" | "m7"

    # ------------------------------------------------------------------
    # SPI (spidev mode only) — verified 50 kHz for TMC260C bench reliability
    # ------------------------------------------------------------------
    spi_device: str = "/dev/spidev1.0"
    spi_speed_hz: int = 50_000  # 50 kHz verified working (was 2 MHz, noise-prone)

    # ------------------------------------------------------------------
    # GPIO pins (spidev mode only) — i.MX8MP EVK J21 header, verified 2026-05-08
    # 3-axis CS lines (manual GPIO toggle, SPI_NO_CS mode):
    #   LIFT (1층) = gpio5_07 (ECSPI1_MOSI alt5)
    #   BEND (2층) = gpio3_22 (SAI5_RXD1 alt5)
    #   FEED (3층) = gpio5_13 (ECSPI2_SS0 alt5, also cs-gpios in DTS)
    # Shared signals:
    #   STEP = PWM4 on SAI5_RXFS pad (pwmchip2/pwm0), parallel to all 3 chips
    #   DIR  = gpio3_23 (SAI5_RXD3 alt5), parallel to all 3 chips
    # ------------------------------------------------------------------
    gpio_lift_cs: str = "GPIO5_IO07"
    gpio_bend_cs: str = "GPIO3_IO22"
    gpio_feed_cs: str = "GPIO5_IO13"
    gpio_dir: str = "GPIO3_IO23"
    pwm_step_path: str = "/sys/class/pwm/pwmchip2/pwm0"
    pwm_step_export: str = "/sys/class/pwm/pwmchip2/export"

    # ------------------------------------------------------------------
    # Limit switches — PM-L25 photo-interrupters, wired 2026-08-13.
    # Output runs through a 12 V divider (~3.0 V idle) into J21; the line
    # is pulled to GND when the switch triggers → ACTIVE LOW.
    # Live-verified 2026-08-14 (held-block static test — definitive):
    # holding the LIFT-axis sensor blocked activates J21 pin 7, so:
    #   LIFT sensor → J21 pin 7  (UART3_CTS pad, ECSPI1_MISO, GPIO5_IO08)
    #   BEND sensor → J21 pin 11 (UART3_RTS pad, ECSPI1_SS0,  GPIO5_IO09)
    # Empty string = switch not fitted (axis not homable).
    # ------------------------------------------------------------------
    gpio_limit_lift: str = "GPIO5_IO08"
    gpio_limit_bend: str = "GPIO5_IO09"
    # Homing motion parameters (axis-native units: mm or deg).
    # home_dir_*: which jog direction moves TOWARD the switch (+1/-1).
    # Flip after the first live test if the axis runs away from it.
    # Live-verified 2026-08-14: LIFT switch sits in the − jog direction,
    # BEND switch in the + direction (−1 run drove BEND away from it).
    home_dir_lift: int = -1
    home_dir_bend: int = 1
    # Axis-specific homing kinematics (bench-measured 2026-08-15):
    #   LIFT = vertical LINEAR axis (gravity: sinks below its window when
    #          de-energized; careful speeds, full current always)
    #   BEND = continuous ROTARY axis, one window per revolution,
    #          1 rev = 82.6 display units measured, window ~0.7 units —
    #          unidirectional search ≤ 1 rev + margin ALWAYS finds it,
    #          no reversal, no hard stops
    home_seek_speed: float = 4.0       # LIFT fast approach (units/s)
    # BEND seek in °/s. Axis calibrated 2026-08-16 (user-verified disc
    # geometry): sensor disc has 8 slots at 45° — slot spacing measured
    # 1,906 steps → 42.36 steps/°, 15,250 steps/rev. 43°/s ≈ 1,822 Hz,
    # above the ~800-1500 Hz slip/resonance band observed at lower
    # speeds.
    home_seek_speed_bend: float = 43.0
    home_latch_speed: float = 0.5    # slow re-approach for repeatability
    home_backoff: float = 1.0        # intermediate retreat between passes (units)
    # LIFT bidirectional search (CiA 402 methods 23-30 pattern): primary
    # leg down bounded by home_search_range, then reverse up the whole
    # travel. Raise home_search_range if normal operation moves the axis
    # further than this from home.
    home_search_range: float = 15.0  # primary seek leg bound (units)
    # LIFT: the switch sits at the very top of the stroke and there is no
    # travel above it, so the seek leg simply covers the whole stroke —
    # a 15 mm leg followed by a reverse sweep would drive a low carriage
    # into the bottom stop looking for a switch that is above it.
    home_search_range_lift: float = 240.0
    # LIFT seek speed (mm/s). 4 mm/s meant ~60 s to climb the stroke.
    home_seek_speed_lift: float = 20.0
    # Rotary search bound for BEND: 1 revolution + margin, in the
    # calibrated degree units.
    home_rev_bend: float = 380.0     # ° (360 + 5% margin)
    # Pre-probe (LIFT): before the primary DOWN leg, probe UP this far
    # watching for the window — catches the axis-sank-below-window case
    # (the common gravity failure) without ever touching the bottom stop.
    home_preprobe: float = 3.0       # units, 0 = off
    # Reduced motor current during homing. DISABLED by default: CS=10
    # proved too weak on this bench (silent step-loss — the counter ran
    # while the motor stalled, so homing "searched" without moving).
    home_reduced_cs: int = 0
    # StallGuard contact abort during homing search legs (virtual limit
    # switch — abort only, never the datum; Trinamic AN-002). OFF until
    # bench-tuned: SG is unreliable at low velocity and drifts with coil
    # temperature.
    home_stall_abort: bool = False

    # ------------------------------------------------------------------
    # Holding current — LIFT sinks under gravity when de-energized
    # (observed: parked axis sank below its home window). While idle the
    # LIFT chopper stays energized at a reduced CS; it is released only
    # for the duration of other-axis motion (shared STEP line: an
    # energized chip steps along with the active axis) and re-held after.
    # E-STOP / driver-disable always release it.
    # ------------------------------------------------------------------
    # LIFT sign convention: operator asked for "+ is down" (datum 0 at
    # the top switch, bottom = +230 mm). The DIR line is flipped for that
    # axis; the counter keeps following the commanded sign.
    invert_lift: bool = True
    # FEED jogged opposite to BEND on the bench (▶ turned it CCW while
    # BEND turned CW). Same fix: flip that axis' DIR line so every axis
    # agrees that + / ▶ is clockwise. Operator-reported 2026-08-16.
    invert_feed: bool = True
    # Idle holding is OFF for every axis: a motor that nobody commanded
    # must not be energised. Only the axis being driven lights up, and it
    # goes dark again when the move ends.
    #
    # LIFT rides a T8 leadscrew that is not self-locking, so with this off
    # the carriage can sink under its own weight. Set hold_lift = True (or
    # PUT /api/motor/protection {"axes":{"3":{"hold_enabled":true}}}) if
    # that turns out to matter for a given setup.
    hold_lift: bool = False
    # FEED/BEND also free-wheel when de-energized (no gravity load, so it
    # is less obvious) — operator asked for per-axis holding, so they can
    # be held too. Runtime toggle: PUT /api/motor/protection {axes:{...}}
    hold_feed: bool = False
    hold_bend: bool = False
    hold_cs: int = 8
    # LIFT carries the carriage against gravity on a T8 leadscrew, which
    # is not self-locking. It was holding at 8 while FEED — which only
    # has to resist a wire — held at 14. Per-axis defaults, still capped
    # by the PSU preset.
    hold_cs_lift: int = 14                 # holding current scale (< run CS)
    # Final resting position after homing, in units from the datum.
    # <0 = park |value| INSIDE the window (approach direction) — sensor
    # reads solidly tripped at the home pose (the trip edge itself sits
    # in the hysteresis band and is metastable). 0 = exactly on the trip
    # edge. >0 = conventional off-switch pull-off. This machine's home
    # pose IS the switch position (user decision 2026-08-14).
    home_park: float = -0.3
    home_timeout_s: float = 60.0     # per-axis seek timeout

    # Legacy aliases (kept for backwards-compat with diag_router and existing
    # IpcMotorBackend signatures). Map onto the verified pins above.
    gpio_cs1: str = "GPIO5_IO07"  # LIFT
    gpio_cs2: str = "GPIO3_IO22"  # BEND
    gpio_feed_step: str = ""      # not used (PWM4 shared)
    gpio_bend_step: str = ""      # not used (PWM4 shared)

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------
    # "auto" = USB VID hot-plug auto-detect (default)
    # "mock" | "vmbpy" | "novitec" | "v4l2" = force a specific backend
    camera_backend: str = "auto"
    camera_device: str = "/dev/video0"  # V4L2 capture node (v4l2 backend)
    camera_fps: float = 30.0
    camera_jpeg_quality: int = 85
    camera_pixel_format: str = "mono8"

    # ------------------------------------------------------------------
    # Motion limits (soft limits enforced by A53 before sending to M7)
    # ------------------------------------------------------------------
    feed_max_mm: float = 200.0
    bend_max_deg: float = 180.0
    rotate_max_deg: float = 360.0
    feed_max_speed_mm_s: float = 100.0
    bend_max_speed_deg_s: float = 360.0

    # pydantic-settings v2: env vars are OB_<FIELD_NAME> (uppercase)
    model_config = SettingsConfigDict(
        env_prefix="OB_",
        env_file=".env",
        env_file_encoding="utf-8",
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
