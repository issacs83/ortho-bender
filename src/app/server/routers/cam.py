"""
routers/cam.py — /api/cam/* REST endpoints.

3D wire centerline → B-code conversion. Pure-Python pipeline lives in
services.cam_service; this router is a thin HTTP wrapper plus optional
chaining to MotorService for one-shot "generate and execute".

IEC 62304 SW Class: B (preview-only; production bending still routes
through the C++ CamEngine on the A53 host when available).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from ..models.schemas import (
    ApiResponse,
    BcodeStep,
    CamGenerateRequest,
    CamGenerateResponse,
    err,
    ok,
)
from ..services.cam_service import generate_bcode
from ..services.motor_service import MotorService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cam", tags=["cam"])


def _motor_service(request: Request) -> MotorService:
    return request.app.state.motor_service


@router.post("/generate", response_model=ApiResponse)
async def cam_generate(body: CamGenerateRequest) -> ApiResponse:
    """
    Convert a 3D polyline into a B-code sequence (preview, no motion).

    Returns the generated steps along with metadata (segment count,
    total length, max bend angle, warnings). Safe to call repeatedly
    from the frontend for live preview.
    """
    try:
        result = generate_bcode(
            points=body.points,
            material=body.material,
            wire_diameter_mm=body.wire_diameter_mm,
            min_segment_mm=body.min_segment_mm,
            apply_springback=body.apply_springback,
        )
    except ValueError as exc:
        return err(str(exc), "CAM_INVALID_INPUT")
    except Exception as exc:
        log.exception("CAM generate failed")
        return err(str(exc), "CAM_INTERNAL_ERROR")

    response = CamGenerateResponse(
        steps=result.steps,
        segment_count=result.segment_count,
        total_length_mm=result.total_length_mm,
        max_bend_deg=result.max_bend_deg,
        warnings=result.warnings,
    )
    log.info(
        "CAM generate: %d points → %d steps, max_bend=%.1f°, total=%.1fmm",
        len(body.points), len(result.steps), result.max_bend_deg, result.total_length_mm,
    )
    return ok(response.model_dump())


@router.post("/execute", response_model=ApiResponse)
async def cam_execute(
    body: CamGenerateRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """
    Generate B-code from a 3D polyline and dispatch it to the motor service.

    Returns immediately after dispatch; poll /api/bending/status for progress.
    """
    try:
        result = generate_bcode(
            points=body.points,
            material=body.material,
            wire_diameter_mm=body.wire_diameter_mm,
            min_segment_mm=body.min_segment_mm,
            apply_springback=body.apply_springback,
        )
    except ValueError as exc:
        return err(str(exc), "CAM_INVALID_INPUT")

    steps = [(s.L_mm, s.beta_deg, s.theta_deg) for s in result.steps]
    try:
        await svc.execute_bcode(
            steps=steps,
            material_id=int(body.material),
            wire_diameter_mm=body.wire_diameter_mm,
        )
    except Exception as exc:
        log.error("CAM execute dispatch failed: %s", exc)
        return err(str(exc), "CAM_EXECUTE_ERROR")

    log.info("CAM execute dispatched: %d steps", len(steps))
    return ok({
        "dispatched": True,
        "step_count": len(steps),
        "total_length_mm": result.total_length_mm,
        "max_bend_deg": result.max_bend_deg,
        "warnings": result.warnings,
    })
