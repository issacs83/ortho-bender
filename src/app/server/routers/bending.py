"""
routers/bending.py — /api/bending/* REST endpoints.

Orchestrates B-code sequence execution:
  1. Validates the B-code sequence (step count, angles, feed length)
  2. Applies per-material springback compensation
  3. Dispatches to MotorService → IPC → M7 FreeRTOS

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, Request

from ..models.schemas import (
    ApiResponse,
    BendingExecuteRequest,
    BendingStatusResponse,
    WireMaterial,
    err,
    ok,
)
from ..services.motor_service import MotorService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/bending", tags=["bending"])

# ---------------------------------------------------------------------------
# Springback compensation table (empirical, per-material)
# Override with NPU inference result when available.
# ---------------------------------------------------------------------------

# Material → (springback_factor, notes)
# theta_compensated = theta_deg * springback_factor
_SPRINGBACK_FACTOR: dict[int, float] = {
    WireMaterial.SS_304:  1.10,    # 10% overbend for stainless steel
    WireMaterial.NITI:    1.35,    # 35% — superelastic high springback
    WireMaterial.BETA_TI: 1.15,   # 15% — TMA moderate
    WireMaterial.CU_NITI: 1.30,   # 30% — thermally activated, temp-dependent
}


# ---------------------------------------------------------------------------
# Bending state (singleton per app — not persistent across restarts)
# ---------------------------------------------------------------------------

class _BendingState:
    def __init__(self) -> None:
        self.running = False
        self.current_step = 0
        self.total_steps = 0
        self.material: Optional[int] = None
        self.wire_diameter_mm: Optional[float] = None
        self.start_time: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def progress_pct(self) -> float:
        if self.total_steps == 0:
            return 0.0
        return round(100.0 * self.current_step / self.total_steps, 1)

    def to_response(self) -> BendingStatusResponse:
        return BendingStatusResponse(
            running=self.running,
            current_step=self.current_step,
            total_steps=self.total_steps,
            progress_pct=self.progress_pct,
            material=WireMaterial(self.material) if self.material is not None else None,
            wire_diameter_mm=self.wire_diameter_mm,
        )


_state = _BendingState()


def _motor_service(request: Request) -> MotorService:
    return request.app.state.motor_service


# ---------------------------------------------------------------------------
# POST /api/bending/execute
# ---------------------------------------------------------------------------

@router.post("/execute", response_model=ApiResponse)
async def bending_execute(
    body: BendingExecuteRequest,
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """
    Execute a B-code wire bending sequence.

    Springback compensation is applied automatically based on material.
    The call returns immediately after dispatch; poll /status for progress.
    """
    async with _state._lock:
        if _state.running:
            return err("Bending sequence already in progress", "BENDING_BUSY")

        # Apply springback compensation
        factor = _SPRINGBACK_FACTOR.get(body.material.value, 1.0)
        steps = [
            (s.L_mm, s.beta_deg, min(s.theta_deg * factor, 180.0))
            for s in body.steps
        ]

        log.info(
            "Bending execute: %d steps, material=%s, wire=%.3f mm, springback=%.2f",
            len(steps), body.material.name, body.wire_diameter_mm, factor,
        )

        _state.running = True
        _state.current_step = 0
        _state.total_steps = len(steps)
        _state.material = body.material.value
        _state.wire_diameter_mm = body.wire_diameter_mm
        _state.start_time = time.monotonic()

    async def _run_sequence() -> None:
        try:
            await svc.execute_bcode(
                steps=steps,
                material_id=body.material.value,
                wire_diameter_mm=body.wire_diameter_mm,
            )
            # Poll motor status for progress until motion returns to IDLE.
            while True:
                await asyncio.sleep(0.1)
                try:
                    st = await svc.get_status()
                except Exception as poll_exc:
                    log.debug("bcode progress poll failed: %s", poll_exc)
                    break
                async with _state._lock:
                    _state.current_step = st.current_step or _state.current_step
                # MotionState: 0=IDLE, 2=RUNNING, 6=ESTOP
                if int(st.state) != 2:
                    break
            async with _state._lock:
                if _state.total_steps:
                    _state.current_step = _state.total_steps
                _state.running = False
            log.info("Bending sequence completed (%d steps)", _state.total_steps)
        except Exception as exc:
            async with _state._lock:
                _state.running = False
            log.error("Bending execute failed: %s", exc)

    asyncio.create_task(_run_sequence())
    return ok(_state.to_response().model_dump())


# ---------------------------------------------------------------------------
# GET /api/bending/status
# ---------------------------------------------------------------------------

@router.get("/status", response_model=ApiResponse)
async def bending_status() -> ApiResponse:
    """Return current bending sequence progress."""
    return ok(_state.to_response().model_dump())


# ---------------------------------------------------------------------------
# POST /api/bending/stop
# ---------------------------------------------------------------------------

@router.post("/stop", response_model=ApiResponse)
async def bending_stop(
    svc: MotorService = Depends(_motor_service),
) -> ApiResponse:
    """Interrupt the running bending sequence with a controlled stop."""
    try:
        status = await svc.stop()
        async with _state._lock:
            _state.running = False
        log.info("Bending sequence stopped by user")
        return ok({"motor": status.model_dump(), "bending": _state.to_response().model_dump()})
    except Exception as exc:
        log.error("Bending stop failed: %s", exc)
        return err(str(exc), "BENDING_STOP_ERROR")
