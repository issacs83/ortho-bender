"""
Motor control REST endpoints.
"""

from fastapi import APIRouter, HTTPException

from ..protocol.constants import MOTOR_IDS, MID_BENDER, MID_FEEDER, MID_LIFTER, MID_CUTTER
from ..motor.motor_models import JogRequest, MoveAbsRequest, InitRequest
from ..motor import motor_api
from ..motor.serial_client import client

router = APIRouter(prefix="/api/motor", tags=["motor"])


def _resolve_motor(name: str) -> int:
    mid = MOTOR_IDS.get(name.lower())
    if mid is None:
        raise HTTPException(status_code=404, detail=f"Unknown motor: {name}")
    if not client.connected:
        raise HTTPException(status_code=503, detail="Not connected")
    return mid


@router.post("/{name}/jog")
def jog(name: str, req: JogRequest):
    mid = _resolve_motor(name)
    ok = motor_api.move_vel(mid, req.direction, req.steps, req.speed, req.accel, req.decel)
    return {"ok": ok}


@router.post("/{name}/move_abs")
def move_abs(name: str, req: MoveAbsRequest):
    mid = _resolve_motor(name)
    ok = motor_api.move_abs(mid, req.direction, req.steps, req.speed, req.accel, req.decel)
    return {"ok": ok}


@router.post("/{name}/init")
def init(name: str, req: InitRequest = InitRequest()):
    mid = _resolve_motor(name)
    ok = motor_api.ml_init(mid)
    return {"ok": ok}


@router.post("/{name}/stop")
def stop_motor(name: str):
    mid = _resolve_motor(name)
    ok = motor_api.stop(mid)
    return {"ok": ok}


@router.get("/{name}/position")
def position(name: str):
    mid = _resolve_motor(name)
    pos = motor_api.get_position(mid)
    if pos is None:
        return {"ok": False}
    phys, unit = motor_api.position_physical(mid, pos)
    return {"ok": True, "steps": pos, "physical": round(phys, 2), "unit": unit}


@router.get("/{name}/state")
def state(name: str):
    mid = _resolve_motor(name)
    s = motor_api.get_state(mid)
    if s is None:
        return {"ok": False}
    return {"ok": True, "state": "moving" if s != 0 else "idle"}


@router.post("/stop_all")
def stop_all():
    if not client.connected:
        raise HTTPException(status_code=503, detail="Not connected")
    ok = motor_api.stop_all()
    return {"ok": ok}


@router.post("/init_all")
def init_all():
    if not client.connected:
        raise HTTPException(status_code=503, detail="Not connected")
    results = {}
    for mid, name in [(MID_BENDER, "bender"), (MID_FEEDER, "feeder"),
                       (MID_LIFTER, "lifter"), (MID_CUTTER, "cutter")]:
        results[name] = motor_api.ml_init(mid)
    return {"ok": all(results.values()), "results": results}


@router.get("/sensors")
def sensors():
    if not client.connected:
        raise HTTPException(status_code=503, detail="Not connected")
    s = motor_api.get_sensor_state()
    if s is None:
        return {"ok": False}
    return {"ok": True, **s}
