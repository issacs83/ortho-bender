"""
diag_schemas.py — Pydantic v2 models for the diagnostic API.

IEC 62304 SW Class: B
"""

from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        """Backport for Python < 3.11."""
from typing import Optional

from pydantic import BaseModel, Field


class DriverId(StrEnum):
    TMC260C_0 = "tmc260c_0"
    TMC260C_1 = "tmc260c_1"
    TMC5072   = "tmc5072"


class DiagRegisterWriteRequest(BaseModel):
    value: int = Field(..., ge=0, description="Register value to write")


class DiagRegisterResponse(BaseModel):
    driver: DriverId
    addr: str
    value: int
    value_hex: str


class DiagDumpResponse(BaseModel):
    driver: DriverId
    registers: dict[str, str]  # name -> hex value


class SpiTestResult(BaseModel):
    driver: DriverId
    ok: bool
    latency_us: Optional[float] = None
    error: Optional[str] = None


class SpiTestResponse(BaseModel):
    results: list[SpiTestResult]


class DiagBackendResponse(BaseModel):
    backend: str
    spi_device: Optional[str] = None
    spi_speed_hz: Optional[int] = None
    drivers: list[DriverId]


class StallGuardCalibrationRequest(BaseModel):
    driver: DriverId = Field(..., description="Driver to calibrate")
    speed_hz: int = Field(200, gt=0, le=2000, description="STEP frequency during calibration")
    axis: int = Field(0, ge=0, le=3, description="Axis to jog during calibration")


class StallGuardCalibrationResponse(BaseModel):
    driver: DriverId
    threshold: int
    sg_min: int
    sg_max: int
    sg_avg: float


class WsDiagEvent(BaseModel):
    """200 Hz diagnostic status broadcast over /ws/motor/diag."""
    type: str = "diag_status"
    drivers: dict[str, dict]  # driver_id -> {sg_result, status_flags, ...}
    timestamp_us: int
