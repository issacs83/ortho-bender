"""
B-code REST endpoints.
"""

import asyncio
import time
from fastapi import APIRouter, HTTPException

from ..bcode.bcode_models import BcodeSequence
from ..bcode.bcode_engine import validate_bcode, apply_springback
from ..bcode.materials import get_all_materials
from ..motor import motor_api
from ..motor.serial_client import client
from ..protocol.constants import MID_FEEDER, MID_BENDER, MID_LIFTER

router = APIRouter(prefix="/api/bcode", tags=["bcode"])

# Execution state
_execution_state = {
    "running": False,
    "current_step": 0,
    "total_steps": 0,
    "cancel": False,
}


def get_execution_state() -> dict:
    return {
        "running": _execution_state["running"],
        "step": _execution_state["current_step"],
        "total": _execution_state["total_steps"],
    }


@router.get("/materials")
def materials():
    return get_all_materials()


@router.post("/validate")
def validate(seq: BcodeSequence):
    result = validate_bcode(seq)
    return result.model_dump()


@router.post("/compensate")
def compensate(seq: BcodeSequence):
    result = apply_springback(seq)
    return result.model_dump()


@router.post("/execute")
async def execute(seq: BcodeSequence):
    """Execute B-code sequence step by step on hardware."""
    if not client.connected:
        raise HTTPException(status_code=503, detail="Not connected")
    if _execution_state["running"]:
        raise HTTPException(status_code=409, detail="Already executing")

    # Validate first
    validation = validate_bcode(seq)
    if not validation.valid:
        raise HTTPException(status_code=400, detail=validation.errors)

    # Apply springback if not already compensated
    compensated = apply_springback(seq)

    _execution_state["running"] = True
    _execution_state["total_steps"] = len(compensated.steps)
    _execution_state["current_step"] = 0
    _execution_state["cancel"] = False

    async def run_steps():
        try:
            for i, step in enumerate(compensated.steps):
                if _execution_state["cancel"]:
                    motor_api.stop_all()
                    break
                _execution_state["current_step"] = i + 1

                # 1. Feed wire by L_mm
                feed_steps = motor_api.mm_to_steps(step.L_mm)
                await asyncio.to_thread(
                    motor_api.move_vel, MID_FEEDER, "ccw", feed_steps, 200
                )
                # Wait for feed to complete
                for _ in range(200):  # 20s max
                    if _execution_state["cancel"]:
                        break
                    moving = await asyncio.to_thread(motor_api.in_motion, MID_FEEDER)
                    if not moving:
                        break
                    await asyncio.sleep(0.1)

                if _execution_state["cancel"]:
                    break

                # 2. Bend by theta_compensated_deg
                if abs(step.theta_compensated_deg) > 0.1:
                    bend_steps = motor_api.deg_to_steps(
                        abs(step.theta_compensated_deg), MID_BENDER
                    )
                    direction = "cw" if step.theta_compensated_deg > 0 else "ccw"
                    await asyncio.to_thread(
                        motor_api.move_vel, MID_BENDER, direction, bend_steps, 1000
                    )
                    for _ in range(200):
                        if _execution_state["cancel"]:
                            break
                        moving = await asyncio.to_thread(motor_api.in_motion, MID_BENDER)
                        if not moving:
                            break
                        await asyncio.sleep(0.1)

                if _execution_state["cancel"]:
                    break

                # 3. Reset bend to home position
                if abs(step.theta_compensated_deg) > 0.1:
                    await asyncio.to_thread(
                        motor_api.move_abs, MID_BENDER, "cw", 0, 1000
                    )
                    for _ in range(200):
                        if _execution_state["cancel"]:
                            break
                        moving = await asyncio.to_thread(motor_api.in_motion, MID_BENDER)
                        if not moving:
                            break
                        await asyncio.sleep(0.1)

        finally:
            _execution_state["running"] = False

    asyncio.create_task(run_steps())
    return {"ok": True, "steps": len(compensated.steps)}


@router.post("/stop")
def stop_execution():
    _execution_state["cancel"] = True
    motor_api.stop_all()
    return {"ok": True}


@router.get("/execution_state")
def execution_state():
    return get_execution_state()
