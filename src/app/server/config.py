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

    # Legacy aliases (kept for backwards-compat with diag_router and existing
    # IpcMotorBackend signatures). Map onto the verified pins above.
    gpio_cs1: str = "GPIO5_IO07"  # LIFT
    gpio_cs2: str = "GPIO3_IO22"  # BEND
    gpio_feed_step: str = ""      # not used (PWM4 shared)
    gpio_bend_step: str = ""      # not used (PWM4 shared)

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------
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
