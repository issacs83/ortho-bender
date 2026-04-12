"""
schemas.py — Pydantic v2 request/response models for the Ortho-Bender SDK API.

Mirrors the IPC protocol structures defined in src/shared/ipc_protocol.h.
All field names follow the B-code convention: L_mm, beta_deg, theta_deg.

IEC 62304 SW Class: B
"""

from __future__ import annotations

from enum import IntEnum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums (mirror ipc_protocol.h)
# ---------------------------------------------------------------------------

class AxisId(IntEnum):
    FEED   = 0  # Wire feed — linear, mm
    BEND   = 1  # Bending die — degrees
    ROTATE = 2  # Wire rotation — degrees (Phase 2)
    LIFT   = 3  # Lift/lower mechanism (Phase 2)


class MotionState(IntEnum):
    IDLE     = 0
    HOMING   = 1
    RUNNING  = 2
    JOGGING  = 3
    STOPPING = 4
    FAULT    = 5
    ESTOP    = 6


class WireMaterial(IntEnum):
    SS_304   = 0   # Stainless steel 304
    NITI     = 1   # Nickel-Titanium (superelastic)
    BETA_TI  = 2   # Beta-Titanium / TMA
    CU_NITI  = 3   # Copper-Nickel-Titanium (thermally activated)


class AlarmSeverity(IntEnum):
    WARNING  = 0
    FAULT    = 1
    CRITICAL = 2


# ---------------------------------------------------------------------------
# Standard response envelope
# ---------------------------------------------------------------------------

class ApiResponse(BaseModel):
    """Standard JSON envelope for all API responses."""
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None
    code: Optional[str] = None


def ok(data: dict) -> ApiResponse:
    return ApiResponse(success=True, data=data)


def err(message: str, code: str = "INTERNAL_ERROR") -> ApiResponse:
    return ApiResponse(success=False, error=message, code=code)


# ---------------------------------------------------------------------------
# Motor API schemas
# ---------------------------------------------------------------------------

class MotorMoveRequest(BaseModel):
    axis: AxisId = Field(..., description="Target axis identifier")
    distance: float = Field(..., description="Distance in mm (feed) or degrees (bend/rotate)")
    speed: float = Field(..., gt=0, description="Speed in mm/s or deg/s")

    @field_validator("distance")
    @classmethod
    def distance_nonzero(cls, v: float) -> float:
        if v == 0.0:
            raise ValueError("distance must be non-zero")
        return v


class MotorJogRequest(BaseModel):
    axis: AxisId = Field(..., description="Target axis identifier")
    direction: int = Field(..., description="+1 for positive, -1 for negative")
    speed: float = Field(..., gt=0, description="Jog speed in mm/s or deg/s")
    distance: float = Field(0.0, ge=0, description="Distance limit (0 = continuous)")

    @field_validator("direction")
    @classmethod
    def direction_valid(cls, v: int) -> int:
        if v not in (1, -1):
            raise ValueError("direction must be +1 or -1")
        return v


class MotorHomeRequest(BaseModel):
    axis_mask: int = Field(
        0,
        ge=0,
        le=0x0F,
        description="Bitmask of axes to home (0 = all enabled axes, e.g. 0x03 = FEED+BEND)"
    )


class MotorResetRequest(BaseModel):
    axis_mask: int = Field(
        0,
        ge=0,
        le=0x0F,
        description="Bitmask of axes to reset (0 = all)"
    )


class AxisStatus(BaseModel):
    axis: AxisId
    position: float     # mm or degrees
    velocity: float     # mm/s or deg/s
    drv_status: int     # TMC5160 DRV_STATUS raw value
    sg_result: int      # StallGuard2 result
    cs_actual: int      # Actual motor current (0-31)


class MotorStatusResponse(BaseModel):
    state: MotionState
    axes: list[AxisStatus]
    current_step: int   # B-code step index during execution
    total_steps: int
    axis_mask: int
    driver_enabled: bool = True   # DRV_ENN line state (TMC260C-PA)


# ---------------------------------------------------------------------------
# Camera API schemas
# ---------------------------------------------------------------------------

class CameraSettingsRequest(BaseModel):
    exposure_us: Optional[float] = Field(
        None, gt=0, description="Exposure time in microseconds"
    )
    gain_db: Optional[float] = Field(
        None, ge=0, description="Analog gain in dB"
    )
    format: Optional[str] = Field(
        None, description="Pixel format: 'mono8', 'mono12', 'rgb8'"
    )

    @field_validator("format")
    @classmethod
    def format_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("mono8", "mono12", "rgb8"):
            raise ValueError("format must be one of: mono8, mono12, rgb8")
        return v


class CameraStatusResponse(BaseModel):
    connected: bool
    device_id: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    exposure_us: Optional[float] = None
    gain_db: Optional[float] = None
    format: Optional[str] = None
    backend: Optional[str] = None   # "vimba_x", "gstreamer", "uvc_fallback"
    fps: Optional[float] = None
    power_state: str = "off"        # "on" | "standby" | "off"


# ---------------------------------------------------------------------------
# Bending API schemas
# ---------------------------------------------------------------------------

class BcodeStep(BaseModel):
    """Single B-code step: Feed → Rotate → Bend."""
    L_mm: float = Field(
        ...,
        ge=0.5,
        le=200.0,
        description="Wire feed length in millimeters"
    )
    beta_deg: float = Field(
        0.0,
        ge=-360.0,
        le=360.0,
        description="Wire rotation angle in degrees"
    )
    theta_deg: float = Field(
        ...,
        ge=0.0,
        le=180.0,
        description="Bend angle in degrees (before springback compensation)"
    )


class BendingExecuteRequest(BaseModel):
    steps: list[BcodeStep] = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Ordered list of B-code steps (max 128)"
    )
    material: WireMaterial = Field(
        WireMaterial.SS_304,
        description="Wire material — affects springback compensation"
    )
    wire_diameter_mm: float = Field(
        0.457,
        gt=0.0,
        le=2.0,
        description="Wire diameter in mm (e.g. 0.457 = 0.018 inch)"
    )


class BendingStatusResponse(BaseModel):
    running: bool
    current_step: int
    total_steps: int
    progress_pct: float
    material: Optional[WireMaterial] = None
    wire_diameter_mm: Optional[float] = None


# ---------------------------------------------------------------------------
# CAM API schemas (3D curve → B-code)
# ---------------------------------------------------------------------------

class Point3D(BaseModel):
    x: float
    y: float
    z: float


class CamGenerateRequest(BaseModel):
    points: list[Point3D] = Field(
        ...,
        min_length=2,
        max_length=512,
        description="Ordered 3D points along target wire centerline (mm)",
    )
    material: WireMaterial = WireMaterial.SS_304
    wire_diameter_mm: float = Field(0.457, gt=0.0, le=2.0)
    min_segment_mm: float = Field(
        1.0, gt=0.0, le=50.0,
        description="Discretization segment length floor (mm)",
    )
    apply_springback: bool = Field(
        True,
        description="Apply per-material springback overbend to theta",
    )


class CamGenerateResponse(BaseModel):
    steps: list[BcodeStep]
    segment_count: int
    total_length_mm: float
    max_bend_deg: float
    warnings: list[str] = []


# ---------------------------------------------------------------------------
# System API schemas
# ---------------------------------------------------------------------------

class SystemStatusResponse(BaseModel):
    motion_state: MotionState
    camera_connected: bool
    ipc_connected: bool       # RPMsg link to M7 healthy
    m7_heartbeat_ok: bool
    active_alarms: int
    uptime_s: float
    cpu_temp_c: Optional[float] = None


class SystemVersionResponse(BaseModel):
    sdk_version: str          # Python SDK version
    m7_firmware: Optional[str] = None   # Semantic version from M7
    m7_build_timestamp: Optional[int] = None


class SystemRebootRequest(BaseModel):
    confirm: bool = Field(..., description="Must be true to execute reboot")


# ---------------------------------------------------------------------------
# WebSocket event schemas
# ---------------------------------------------------------------------------

class WsMotorEvent(BaseModel):
    """100 ms motor status broadcast over /ws/motor."""
    type: str = "motor_status"
    state: MotionState
    axes: list[AxisStatus]
    timestamp_us: int


class WsCameraFrame(BaseModel):
    """Camera frame event over /ws/camera (JPEG as base64)."""
    type: str = "camera_frame"
    frame_b64: str      # base64-encoded JPEG
    width: int
    height: int
    timestamp_us: int


class WsSystemEvent(BaseModel):
    """System-level event over /ws/system."""
    type: str           # "alarm", "state_change", "heartbeat"
    severity: Optional[AlarmSeverity] = None
    alarm_code: Optional[int] = None
    message: str
    timestamp_us: int
