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
    MotionState,
    MotorHomeRequest,
    MotorZeroRequest,
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


def _calibration_service(request: Request):
    return getattr(request.app.state, "calibration_service", None)


from pydantic import BaseModel as _BaseModel


class CalibrationUpdate(_BaseModel):
    axis: int
    steps_per_unit: float


# ---------------------------------------------------------------------------
# GET /api/motor/calibration  +  POST /api/motor/calibration
# ---------------------------------------------------------------------------

@router.get("/calibration", response_model=ApiResponse)
async def get_calibration(svc=Depends(_calibration_service)) -> ApiResponse:
    """Return the active axis steps_per_unit map + per-axis caps."""
    if svc is None:
        return err("calibration not available", "NO_BENCH")
    return ok(svc.all())


@router.post("/calibration", response_model=ApiResponse)
async def update_calibration(
    body: CalibrationUpdate, svc=Depends(_calibration_service)
) -> ApiResponse:
    """Set steps_per_unit for one axis."""
    if svc is None:
        return err("calibration not available", "NO_BENCH")
    try:
        svc.update(body.axis, body.steps_per_unit)
        return ok(svc.all())
    except ValueError as exc:
        return err(str(exc), "INVALID_CALIBRATION")


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
# POST /api/motor/jog/start  +  POST /api/motor/jog/stop  (long-press jog)
# ---------------------------------------------------------------------------

@router.post("/jog/start", response_model=ApiResponse)
async def motor_jog_start(
    body: MotorJogRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """Begin continuous bench jog.

    Two patterns supported:
      - long-press (default, body.continuous=False): pointerdown → start,
        pointerup → /jog/stop. 5 s safety fallback.
      - single-click continuous (body.continuous=True): one click → run,
        manual STOP button → /jog/stop. 60 s safety fallback.
    """
    try:
        result = await svc.jog_start(
            body.axis, body.direction, body.speed, continuous=body.continuous
        )
        return ok(result)
    except Exception as exc:
        log.error("Motor jog/start failed: %s", exc)
        return err(str(exc), "MOTOR_JOG_START_ERROR")


@router.post("/jog/stop", response_model=ApiResponse)
async def motor_jog_stop(
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """Stop the current bench jog (long-press release)."""
    try:
        result = await svc.jog_stop()
        return ok(result)
    except Exception as exc:
        log.error("Motor jog/stop failed: %s", exc)
        return err(str(exc), "MOTOR_JOG_STOP_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/home
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field


class MotionProfileUpdate(BaseModel):
    """Partial per-axis motion profile update — omitted fields keep their value.

    Unknown fields are rejected (422) so a client still sending the
    pre-0.3.0 `accel_hz_s`/`decel_hz_s` names fails loudly instead of
    "succeeding" with no effect.
    """
    model_config = {"extra": "forbid"}
    jog_speed: float | None = Field(None, gt=0, le=360,
                                    description="Default jog rate (mm/s or deg/s)")
    max_speed: float | None = Field(None, gt=0, le=360,
                                    description="Machine velocity limit — all motion "
                                                "commands are clamped to this "
                                                "(GRBL $110-112 analog)")
    step_size: float | None = Field(None, gt=0, le=360,
                                    description="Incremental jog distance (mm or deg)")
    start_hz: int | None = Field(None, ge=50, le=2000,
                                 description="Ramp floor frequency (Hz)")
    accel: float | None = Field(None, ge=1, le=200,
                                description="Acceleration in physical units "
                                            "(mm/s² or deg/s²; converted to STEP "
                                            "slew via axis calibration)")
    decel: float | None = Field(None, ge=1, le=200,
                                description="Deceleration for stop/finish ramps "
                                            "(mm/s² or deg/s²)")
    shape: str | None = Field(None, pattern="^(linear|scurve)$",
                              description="Velocity profile: trapezoidal 'linear' "
                                          "or jerk-limited 'scurve'")


def _profiles(request: Request):
    return request.app.state.motion_profiles


@router.get("/profiles", response_model=ApiResponse)
async def get_motion_profiles(request: Request) -> ApiResponse:
    """Per-axis motion profiles (jog defaults + acceleration shaping).

    accel/decel are physical (mm/s² or deg/s²) and converted to STEP
    slew via the axis calibration at command time. S-curve uses a
    smoothstep frequency schedule whose peak slope equals the configured
    accel, so switching shape never exceeds the configured acceleration.
    Applied by the bench to every jog/move ramp, including the
    deceleration ramp on stop and end-of-travel.
    """
    return ok({"profiles": _profiles(request).all()})


@router.put("/profiles/{axis}", response_model=ApiResponse)
async def update_motion_profile(
    axis: int, body: MotionProfileUpdate, request: Request,
) -> ApiResponse:
    """Update one axis' motion profile (partial; persisted on the board)."""
    try:
        updated = _profiles(request).update(
            axis, body.model_dump(exclude_none=True))
        return ok({"axis": axis, "profile": updated})
    except ValueError as exc:
        return err(str(exc), "MOTOR_PROFILE_ERROR")


@router.post("/zero", response_model=ApiResponse)
async def motor_set_zero(
    body: MotorZeroRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """Zero-point (datum) setting — declare the current physical position.

    Jog the axis to a known reference (mechanical stop, mark, or a limit
    switch once wired) and call this to define the position counter as
    `value` (default 0). No motion occurs; the counter persists across
    restarts. Homing via the two bench limit switches will build on this
    once they are powered and wired.
    """
    try:
        status = await svc.set_zero(int(body.axis), body.value)
        return ok(status.model_dump())
    except (RuntimeError, ValueError) as exc:
        return err(str(exc), "MOTOR_ZERO_ERROR")


@router.get("/limits", response_model=ApiResponse)
async def motor_limits(
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """Live limit switch states + homing bookkeeping.

    Response: `limits` maps axis id → switch tripped (only axes with a
    switch fitted appear: 1=BEND, 3=LIFT), `homed` lists axes homed since
    server start, `homing` is True while a homing sequence runs, `error`
    holds the last homing failure (or null). Switch states also stream in
    every axis' `signals.limit` over /ws/motor.
    """
    try:
        return ok(svc.limit_status())
    except Exception as exc:
        log.error("Motor limits query failed: %s", exc)
        return err(str(exc), "MOTOR_LIMITS_ERROR")


class AxisHoldUpdate(BaseModel):
    """Torque settings for one axis."""
    model_config = {"extra": "forbid"}
    hold_enabled: bool | None = None
    hold_cs: int | None = Field(
        None, ge=1, le=19,
        description="Idle holding current scale (1-19).")
    run_cs: int | None = Field(
        None, ge=1, le=19,
        description="Coil current while this axis MOVES (1-19). Still "
                    "clamped by the PSU preset cap: ask for more than the "
                    "supply allows and run_cs_effective reports what you "
                    "actually get. 19 is the ceiling -- two boards were "
                    "destroyed at CS=31.")


class ProtectionUpdate(BaseModel):
    """Partial protection/holding settings update (omitted = keep)."""
    model_config = {"extra": "forbid"}
    limit_stop: bool | None = Field(
        None, description="Stop an axis that ENTERS its limit window during "
                          "normal motion (edge-triggered; leaving the window "
                          "from a parked-at-home start is never blocked)")
    hold_enabled: bool | None = Field(
        None, description="Idle holding current on LIFT (gravity axis) — "
                          "prevents sinking; audible chopper hiss while held")
    hold_cs: int | None = Field(
        None, ge=1, le=19,
        description="Holding torque current scale (1-19, PSU cap still "
                    "applies). Lower = quieter + less holding torque")
    axes: dict[int, AxisHoldUpdate] | None = Field(
        None,
        description="Per-axis holding torque, e.g. "
                    "{\"0\": {\"hold_enabled\": true, \"hold_cs\": 12}}. "
                    "Axis ids: 0=FEED, 1=BEND, 3=LIFT (ROTATE not fitted)")


class MoveToRequest(BaseModel):
    model_config = {"extra": "forbid"}
    axis: int = Field(ge=0, le=3)
    position: float = Field(ge=-100000, le=100000,
                            description="Absolute target (user units)")
    speed: float = Field(gt=0, le=360)


@router.get("/protection", response_model=ApiResponse)
async def get_protection(svc: MotorService = Depends(_motor_service)) -> ApiResponse:
    """Motion protection + holding-torque settings (limit_stop /
    hold_enabled / hold_cs)."""
    try:
        return ok(svc.get_protection())
    except Exception as exc:
        return err(str(exc), "MOTOR_PROTECTION_ERROR")


@router.put("/protection", response_model=ApiResponse)
async def update_protection(
    body: ProtectionUpdate,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """Update protection settings; holding changes apply immediately
    while the bench is idle."""
    try:
        result = await svc.set_protection(
            limit_stop=body.limit_stop,
            hold_enabled=body.hold_enabled,
            hold_cs=body.hold_cs,
            axes={k: v.model_dump(exclude_none=True)
                  for k, v in (body.axes or {}).items()} or None)
        return ok(result)
    except (RuntimeError, ValueError) as exc:
        return err(str(exc), "MOTOR_PROTECTION_ERROR")


class StallGuardUpdate(BaseModel):
    """StallGuard2 tuning. LOWER sgt = more sensitive; +63 (power-on
    default) effectively disables stall reporting."""
    model_config = {"extra": "forbid"}
    axis: int | None = Field(None, ge=0, le=3)
    sgt: int | None = Field(None, ge=-64, le=63)
    filter: bool | None = Field(
        None, description="SFILT — average over 4 electrical periods "
                          "(smoother, 4x slower response)")


@router.get("/stallguard", response_model=ApiResponse)
async def get_stallguard(svc: MotorService = Depends(_motor_service)) -> ApiResponse:
    """Per-axis StallGuard threshold, live SG_RESULT and stall flag."""
    try:
        return ok(svc.get_stallguard())
    except Exception as exc:
        return err(str(exc), "MOTOR_SG_ERROR")


@router.put("/stallguard", response_model=ApiResponse)
async def update_stallguard(
    body: StallGuardUpdate,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """Set the StallGuard threshold for one axis (persisted on the board)."""
    try:
        return ok(await svc.set_stallguard(axis=body.axis, sgt=body.sgt,
                                           filter=body.filter))
    except (RuntimeError, ValueError) as exc:
        return err(str(exc), "MOTOR_SG_ERROR")


@router.post("/move_to", response_model=ApiResponse)
async def motor_move_to(
    body: MoveToRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """Absolute move to `position` (user units). POST /move is RELATIVE
    (moves BY `distance`); this endpoint computes the delta from the
    current counter — what the UI's 'Move To Position' means."""
    try:
        status = await svc.move_to(body.axis, body.position, body.speed)
        return ok(status.model_dump())
    except (RuntimeError, ValueError) as exc:
        return err(str(exc), "MOTOR_MOVE_ERROR")
    except Exception as exc:
        log.error("move_to failed axis=%s pos=%s: %s", body.axis, body.position, exc)
        return err(str(exc), "MOTOR_MOVE_ERROR")


@router.post("/home", response_model=ApiResponse)
async def motor_home(
    body: MotorHomeRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """Limit-switch homing (GRBL-style two-pass).

    Homes each requested axis that has a switch (0x02=BEND, 0x08=LIFT;
    axis_mask=0 = all homable): fast seek → back off → slow latch →
    datum 0 at the switch → pull-off. Returns immediately with
    state=HOMING; watch /ws/motor for completion and GET /limits for
    the result. POST /jog/stop or E-STOP cancels.
    """
    try:
        status = await svc.home(body.axis_mask)
        return ok(status.model_dump())
    except RuntimeError as exc:
        return err(str(exc), "MOTOR_HOME_ERROR")
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
# POST /api/motor/enable  /  /api/motor/disable  (TMC260C-PA DRV_ENN)
# ---------------------------------------------------------------------------

@router.post("/enable", response_model=ApiResponse)
async def motor_enable(
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """
    Assert TMC260C-PA DRV_ENN — re-energize stepper coils on all axes.
    After this call the motors hold position again.
    """
    try:
        status = await svc.enable_drivers()
        return ok(status.model_dump())
    except Exception as exc:
        log.error("Motor enable failed: %s", exc)
        return err(str(exc), "MOTOR_ENABLE_ERROR")


@router.post("/disable", response_model=ApiResponse)
async def motor_disable(
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """
    De-energize TMC260C-PA coils (release DRV_ENN).

    Rejects with 409 MOTOR_BUSY if any axis is still moving — callers must
    issue /stop first. VMot 12V is NOT cut; this is a standard industrial
    driver-disable, safe to toggle from client code.
    """
    try:
        current = await svc.get_status()
        if current.state not in (MotionState.IDLE, MotionState.FAULT, MotionState.ESTOP):
            return err(
                f"Cannot disable drivers in state {current.state.name} — stop motion first",
                "MOTOR_BUSY",
            )
        status = await svc.disable_drivers()
        return ok(status.model_dump())
    except Exception as exc:
        log.error("Motor disable failed: %s", exc)
        return err(str(exc), "MOTOR_DISABLE_ERROR")


# ---------------------------------------------------------------------------
# POST /api/motor/reset
# ---------------------------------------------------------------------------

@router.post("/reset", response_model=ApiResponse)
async def motor_reset(
    body: MotorResetRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """Clear fault state and re-enable motor drivers.

    On the bench this also runs the TMC26x latch-clear sequence, so a
    latched short-detect fault no longer needs a physical power cycle.
    The response carries `fault_clear` naming any axis that stayed
    faulted — those genuinely need power removed.
    """
    try:
        status = await svc.reset()
        data = status.model_dump()
        report = getattr(svc, "_last_fault_clear", None)
        if report:
            data["fault_clear"] = report
        return ok(data)
    except Exception as exc:
        log.error("Motor reset failed: %s", exc)
        return err(str(exc), "MOTOR_RESET_ERROR")
