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
    # SPI (spidev mode only)
    # ------------------------------------------------------------------
    spi_device: str = "/dev/spidev1.0"
    spi_speed_hz: int = 2_000_000

    # ------------------------------------------------------------------
    # GPIO pins (spidev mode only) — i.MX8MP J21 header
    # ------------------------------------------------------------------
    gpio_cs1: str = "GPIO3_IO19"
    gpio_cs2: str = "GPIO3_IO20"
    gpio_feed_step: str = "GPIO3_IO22"
    gpio_bend_step: str = "GPIO3_IO24"
    gpio_dir: str = "GPIO5_IO06"

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
