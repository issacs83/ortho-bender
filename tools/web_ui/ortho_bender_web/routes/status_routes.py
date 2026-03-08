"""
Connection and status REST endpoints.
"""

from fastapi import APIRouter

from ..motor.serial_client import client
from ..motor.motor_models import ConnectRequest
from ..motor.motor_api import get_version

router = APIRouter(prefix="/api", tags=["status"])


@router.post("/connect")
def connect(req: ConnectRequest):
    ok = client.connect(req.port, req.baudrate)
    if ok:
        ver = get_version()
        return {"ok": True, "port": req.port, "version": ver}
    return {"ok": False, "error": "Connection failed"}


@router.post("/disconnect")
def disconnect():
    client.disconnect()
    return {"ok": True}


@router.get("/status")
def status():
    from ..motor.motor_api import get_all_status
    if not client.connected:
        return {"connected": False, "motors": {}, "sensors": {}}
    data = get_all_status()
    return {"connected": True, **data}
