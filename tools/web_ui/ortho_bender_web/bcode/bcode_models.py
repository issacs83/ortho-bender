"""
B-code Pydantic models. Mirrors src/shared/bcode_types.h.
"""

from pydantic import BaseModel, Field

# Constants from bcode_types.h
BCODE_MAX_STEPS = 128
BCODE_MIN_FEED_MM = 0.5
BCODE_MAX_FEED_MM = 200.0
BCODE_MIN_BEND_DEG = 0.5
BCODE_MAX_BEND_DEG = 180.0
BCODE_MAX_ROTATE_DEG = 360.0


class BcodeStep(BaseModel):
    L_mm: float = Field(description="Feed length in mm")
    beta_deg: float = Field(default=0.0, description="Rotation angle in degrees")
    theta_deg: float = Field(description="Bend angle in degrees")
    theta_compensated_deg: float = Field(default=0.0, description="After springback compensation")


class BcodeSequence(BaseModel):
    material_id: int = Field(default=0, ge=0, le=3)
    wire_diameter_mm: float = Field(default=0.4, gt=0)
    steps: list[BcodeStep] = Field(default_factory=list)


class BcodeValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
