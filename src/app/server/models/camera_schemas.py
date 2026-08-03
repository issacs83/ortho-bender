"""
camera_schemas.py — Pydantic v2 request/response models for camera feature API.

These mirror the dataclass types in camera_backends but add FastAPI validation,
serialization, and OpenAPI schema generation.

IEC 62304 SW Class: B
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class NumericRangeSchema(BaseModel):
    min: float
    max: float
    step: float = 1.0

class DeviceInfoSchema(BaseModel):
    model: str
    serial: str
    firmware: str
    vendor: str

class FrameMetaSchema(BaseModel):
    timestamp_us: int
    exposure_us: float
    gain_db: float
    temperature_c: Optional[float] = None
    fps_actual: float
    width: int
    height: int

class FeatureCapabilitySchema(BaseModel):
    supported: bool
    range: Optional[NumericRangeSchema] = None
    auto_available: Optional[bool] = None
    available_values: Optional[list[str]] = None
    slots: Optional[list[str]] = None

class ExposureRequest(BaseModel):
    auto: bool = False
    time_us: Optional[float] = Field(None, gt=0, description="Exposure time μs")

class ExposureResponse(BaseModel):
    auto: bool
    time_us: float
    range: NumericRangeSchema
    auto_available: bool
    invalidated: list[str] = []

class GainRequest(BaseModel):
    auto: bool = False
    value_db: Optional[float] = Field(None, ge=0, description="Gain in dB")

class GainResponse(BaseModel):
    auto: bool
    value_db: float
    range: NumericRangeSchema
    auto_available: bool
    invalidated: list[str] = []

class RoiRequest(BaseModel):
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    offset_x: int = Field(0, ge=0)
    offset_y: int = Field(0, ge=0)

class RoiResponse(BaseModel):
    width: int
    height: int
    offset_x: int
    offset_y: int
    width_range: NumericRangeSchema
    height_range: NumericRangeSchema
    offset_x_range: NumericRangeSchema
    offset_y_range: NumericRangeSchema
    invalidated: list[str] = []

class PixelFormatRequest(BaseModel):
    format: str = Field(..., description="e.g. 'mono8', 'mono12', 'rgb8'")

class PixelFormatResponse(BaseModel):
    format: str
    available: list[str]
    invalidated: list[str] = []

class FrameRateRequest(BaseModel):
    enable: bool
    value: Optional[float] = Field(None, gt=0)

class FrameRateResponse(BaseModel):
    enable: bool
    value: float
    range: NumericRangeSchema
    invalidated: list[str] = []

class TriggerRequest(BaseModel):
    mode: str = Field(..., description="'freerun', 'software', 'external'")
    source: Optional[str] = None

class TriggerResponse(BaseModel):
    mode: str
    source: Optional[str] = None
    available_modes: list[str]
    available_sources: list[str]
    invalidated: list[str] = []

class TemperatureResponse(BaseModel):
    value_c: float

class UserSetSlotRequest(BaseModel):
    slot: str

class UserSetResponse(BaseModel):
    current_slot: str
    available_slots: list[str]
    default_slot: str

class CameraStatusSchema(BaseModel):
    connected: bool
    streaming: bool
    device: Optional[DeviceInfoSchema] = None
    current_exposure_us: Optional[float] = None
    current_gain_db: Optional[float] = None
    current_temperature_c: Optional[float] = None
    current_fps: Optional[float] = None
    current_pixel_format: Optional[str] = None
    current_roi: Optional[dict] = None
    current_trigger_mode: Optional[str] = None

class ConnectResponse(BaseModel):
    device: DeviceInfoSchema
    capabilities: dict[str, FeatureCapabilitySchema]


def _range_to_schema(r) -> NumericRangeSchema:
    return NumericRangeSchema(min=r.min, max=r.max, step=r.step)

def _invalidated_to_str(features: list) -> list[str]:
    return [f.value if hasattr(f, 'value') else str(f) for f in features]

def exposure_to_response(info) -> ExposureResponse:
    return ExposureResponse(
        auto=info.auto, time_us=info.time_us,
        range=_range_to_schema(info.range),
        auto_available=info.auto_available,
        invalidated=_invalidated_to_str(info.invalidated),
    )

def gain_to_response(info) -> GainResponse:
    return GainResponse(
        auto=info.auto, value_db=info.value_db,
        range=_range_to_schema(info.range),
        auto_available=info.auto_available,
        invalidated=_invalidated_to_str(info.invalidated),
    )

def roi_to_response(info) -> RoiResponse:
    return RoiResponse(
        width=info.width, height=info.height,
        offset_x=info.offset_x, offset_y=info.offset_y,
        width_range=_range_to_schema(info.width_range),
        height_range=_range_to_schema(info.height_range),
        offset_x_range=_range_to_schema(info.offset_x_range),
        offset_y_range=_range_to_schema(info.offset_y_range),
        invalidated=_invalidated_to_str(info.invalidated),
    )

def pixel_format_to_response(info) -> PixelFormatResponse:
    return PixelFormatResponse(
        format=info.format, available=info.available,
        invalidated=_invalidated_to_str(info.invalidated),
    )

def frame_rate_to_response(info) -> FrameRateResponse:
    return FrameRateResponse(
        enable=info.enable, value=info.value,
        range=_range_to_schema(info.range),
        invalidated=_invalidated_to_str(info.invalidated),
    )

def trigger_to_response(info) -> TriggerResponse:
    return TriggerResponse(
        mode=info.mode, source=info.source,
        available_modes=info.available_modes,
        available_sources=info.available_sources,
        invalidated=_invalidated_to_str(info.invalidated),
    )

def userset_to_response(info) -> UserSetResponse:
    return UserSetResponse(
        current_slot=info.current_slot,
        available_slots=info.available_slots,
        default_slot=info.default_slot,
    )

def status_to_schema(status) -> CameraStatusSchema:
    device = None
    if status.device:
        device = DeviceInfoSchema(
            model=status.device.model, serial=status.device.serial,
            firmware=status.device.firmware, vendor=status.device.vendor,
        )
    return CameraStatusSchema(
        connected=status.connected, streaming=status.streaming,
        device=device,
        current_exposure_us=status.current_exposure_us,
        current_gain_db=status.current_gain_db,
        current_temperature_c=status.current_temperature_c,
        current_fps=status.current_fps,
        current_pixel_format=status.current_pixel_format,
        current_roi=status.current_roi,
        current_trigger_mode=status.current_trigger_mode,
    )

def capabilities_to_schema(caps: dict) -> dict[str, FeatureCapabilitySchema]:
    result = {}
    for feature, cap in caps.items():
        key = feature.value if hasattr(feature, 'value') else str(feature)
        r = _range_to_schema(cap.range) if cap.range else None
        result[key] = FeatureCapabilitySchema(
            supported=cap.supported, range=r,
            auto_available=cap.auto_available,
            available_values=cap.available_values,
            slots=cap.slots,
        )
    return result
