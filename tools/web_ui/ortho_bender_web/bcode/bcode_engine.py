"""
B-code validation and springback compensation.
Ported from src/app/cam/cam_engine.cpp.
"""

from .bcode_models import (
    BcodeSequence, BcodeStep, BcodeValidationResult,
    BCODE_MAX_STEPS, BCODE_MIN_FEED_MM, BCODE_MAX_FEED_MM,
    BCODE_MIN_BEND_DEG, BCODE_MAX_BEND_DEG, BCODE_MAX_ROTATE_DEG,
)
from .materials import get_material


def validate_bcode(seq: BcodeSequence) -> BcodeValidationResult:
    """Validate a B-code sequence. Mirrors cam_engine.cpp validate_bcode."""
    errors = []
    warnings = []

    if len(seq.steps) > BCODE_MAX_STEPS:
        errors.append(f"Too many steps: {len(seq.steps)} > {BCODE_MAX_STEPS}")

    if len(seq.steps) == 0:
        errors.append("No steps defined")

    material = get_material(seq.material_id)
    if material is None:
        errors.append(f"Unknown material ID: {seq.material_id}")

    total_length = 0.0
    for i, step in enumerate(seq.steps):
        if step.L_mm < BCODE_MIN_FEED_MM or step.L_mm > BCODE_MAX_FEED_MM:
            errors.append(f"Step {i+1}: feed {step.L_mm}mm out of range [{BCODE_MIN_FEED_MM}, {BCODE_MAX_FEED_MM}]")

        theta = abs(step.theta_deg)
        if theta > 0 and theta < BCODE_MIN_BEND_DEG:
            warnings.append(f"Step {i+1}: bend angle {theta} below minimum {BCODE_MIN_BEND_DEG}")
        if theta > BCODE_MAX_BEND_DEG:
            errors.append(f"Step {i+1}: bend angle {theta} exceeds {BCODE_MAX_BEND_DEG}")

        if abs(step.beta_deg) > BCODE_MAX_ROTATE_DEG:
            errors.append(f"Step {i+1}: rotation {step.beta_deg} exceeds +/-{BCODE_MAX_ROTATE_DEG}")

        if material and theta > material["max_bend_angle_deg"]:
            warnings.append(f"Step {i+1}: bend {theta} exceeds {material['name']} max {material['max_bend_angle_deg']}")

        total_length += step.L_mm

    if total_length > 300.0:
        errors.append(f"Total wire length {total_length:.1f}mm exceeds 300mm")

    return BcodeValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def apply_springback(seq: BcodeSequence) -> BcodeSequence:
    """
    Apply springback compensation.
    Formula from cam_engine.cpp: theta_compensated = theta / (1 - K)
    """
    material = get_material(seq.material_id)
    if material is None:
        return seq

    k = material["springback_ratio"]
    max_angle = material["max_bend_angle_deg"]

    compensated_steps = []
    for step in seq.steps:
        theta = step.theta_deg
        if abs(theta) > 0 and k < 1.0:
            compensated = theta / (1.0 - k)
            # Clamp to material max
            if abs(compensated) > max_angle:
                compensated = max_angle if compensated > 0 else -max_angle
        else:
            compensated = theta

        compensated_steps.append(BcodeStep(
            L_mm=step.L_mm,
            beta_deg=step.beta_deg,
            theta_deg=step.theta_deg,
            theta_compensated_deg=round(compensated, 2),
        ))

    return BcodeSequence(
        material_id=seq.material_id,
        wire_diameter_mm=seq.wire_diameter_mm,
        steps=compensated_steps,
    )
