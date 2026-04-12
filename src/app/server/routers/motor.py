"""
routers/motor.py — /api/motor/* REST endpoints.

All responses use the standard envelope: {"success": bool, "data": {...}}.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..models.schemas import (
    ApiResponse,
    MotorHomeRequest,
    MotorJogRequest,
    MotorMoveRequest,
    MotorResetRequest,
    err,
    ok,
)
from ..services.motor_service import MotorService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/motor", tags=["motor"])


def _motor_service(request: Request) -> MotorService:
    return request.app.state.motor_service


# ---------------------------------------------------------------------------
# GET /api/motor/status
# ---------------------------------------------------------------------------

@router.get("/status", response_model=ApiResponse)
async def get_motor_status(
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """Return current position, velocity, and state for all active axes."""
    try:
        status = await svc.get_status()
        return ok(status.model_dump())
    except Exception as exc:
        log.error("Motor status query failed: %s", exc)
        return err(str(exc), "MOTOR_STATUS_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/move
# ---------------------------------------------------------------------------

@router.post("/move", response_model=ApiResponse)
async def motor_move(
    body: MotorMoveRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """Move a single axis by the specified distance at the given speed."""
    try:
        status = await svc.move(body.axis, body.distance, body.speed)
        return ok(status.model_dump())
    except Exception as exc:
        log.error("Motor move failed axis=%s dist=%s: %s", body.axis, body.distance, exc)
        return err(str(exc), "MOTOR_MOVE_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/jog
# ---------------------------------------------------------------------------

@router.post("/jog", response_model=ApiResponse)
async def motor_jog(
    body: MotorJogRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """Jog an axis continuously or for a fixed distance."""
    try:
        status = await svc.jog(body.axis, body.direction, body.speed, body.distance)
        return ok(status.model_dump())
    except Exception as exc:
        log.error("Motor jog failed: %s", exc)
        return err(str(exc), "MOTOR_JOG_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/home
# ---------------------------------------------------------------------------

@router.post("/home", response_model=ApiResponse)
async def motor_home(
    body: MotorHomeRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """
    Execute homing sequence using StallGuard2.
    axis_mask=0 homes all enabled axes.
    """
    try:
        status = await svc.home(body.axis_mask)
        return ok(status.model_dump())
    except Exception as exc:
        log.error("Motor home failed (mask=0x%02x): %s", body.axis_mask, exc)
        return err(str(exc), "MOTOR_HOME_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/stop
# ---------------------------------------------------------------------------

@router.post("/stop", response_model=ApiResponse)
async def motor_stop(
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """Controlled deceleration stop (soft stop)."""
    try:
        status = await svc.stop()
        return ok(status.model_dump())
    except Exception as exc:
        log.error("Motor stop failed: %s", exc)
        return err(str(exc), "MOTOR_STOP_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/estop
# ---------------------------------------------------------------------------

@router.post("/estop", response_model=ApiResponse)
async def motor_estop(
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """
    Software E-STOP — immediate halt via IPC (SW path).
    Hardware E-STOP path is handled independently by M7 GPIO ISR + DRV_ENN.
    """
    try:
        status = await svc.estop()
        log.warning("SW E-STOP triggered via REST API")
        return ok(status.model_dump())
    except Exception as exc:
        log.critical("SW E-STOP failed: %s", exc)
        return err(str(exc), "MOTOR_ESTOP_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/reset
# ---------------------------------------------------------------------------

@router.post("/reset", response_model=ApiResponse)
async def motor_reset(
    body: MotorResetRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """Clear fault state and re-enable motor drivers."""
    try:
        status = await svc.reset()
        return ok(status.model_dump())
    except Exception as exc:
        log.error("Motor reset failed: %s", exc)
        return err(str(exc), "MOTOR_RESET_ERROR")
