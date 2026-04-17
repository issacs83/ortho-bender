"""
routers/system.py — /api/system/* REST endpoints.

Aggregates health data from IPC, camera, and OS into a single status view.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from fastapi import APIRouter, Depends, Request

from ..models.schemas import (
    ApiResponse,
    MotionState,
    SystemRebootRequest,
    err,
    ok,
)
from ..services.camera_service import CameraService
from ..services.ipc_client import (
    IpcClient,
    MSG_DIAG_GET_VERSION,
    MSG_STATUS_HEARTBEAT,
)
from ..services.motor_service import MotorService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/system", tags=["system"])

SDK_VERSION = "0.1.0"

_boot_time = time.monotonic()


def _ipc(request: Request) -> IpcClient:
    return request.app.state.ipc_client


def _motor_service(request: Request) -> MotorService:
    return request.app.state.motor_service


def _camera_service(request: Request) -> CameraService:
    return request.app.state.camera_service


# ---------------------------------------------------------------------------
# GET /api/system/status
# ---------------------------------------------------------------------------

def _driver_probe(request: Request) -> dict:
    return getattr(request.app.state, "driver_probe", {})


@router.get("/status", response_model=ApiResponse)
async def get_system_status(
    ipc: IpcClient = Depends(_ipc),
    motor: MotorService = Depends(_motor_service),
    camera: CameraService = Depends(_camera_service),
    driver_probe: dict = Depends(_driver_probe),
) -> ApiResponse:
    """Aggregate health: IPC link, M7 heartbeat, camera, motion state."""
    uptime_s = time.monotonic() - _boot_time
    cpu_temp: float | None = _read_cpu_temp()

    ipc_ok = ipc.connected
    m7_hb_ok = False
    active_alarms = 0
    motion_state = MotionState.IDLE

    if ipc_ok:
        try:
            resp = await asyncio.wait_for(
                ipc.send_recv(MSG_STATUS_HEARTBEAT), timeout=0.5
            )
            # Heartbeat payload: uptime_ms(4B) state(1B) alarms(2B) wdt_ok(1B) axis_mask(1B)
            import struct
            if len(resp.payload) >= 9:
                _, state, alarms, wdt_ok, _ = struct.unpack_from("<IBHBB", resp.payload)
                m7_hb_ok = bool(wdt_ok)
                active_alarms = alarms
                motion_state = MotionState(state)
        except Exception as exc:
            log.debug("Heartbeat poll failed: %s", exc)

    # Camera status — read from CameraBackend ABC
    camera_connected = camera.is_connected
    camera_model: str | None = None
    if camera_connected:
        try:
            dev = camera.device_info()
            camera_model = dev.get("model")
        except Exception:
            pass

    # Motor driver summary — count connected drivers from probe
    motor_connected = any(
        d.get("connected", False) for d in driver_probe.values()
    ) if driver_probe else False
    motor_model: str | None = None
    if motor_connected:
        chips = [d["chip"] for d in driver_probe.values() if d.get("connected")]
        motor_model = ", ".join(sorted(set(chips))) if chips else None

    return ok({
        "motion_state":     motion_state.value,
        "camera_connected": camera_connected,
        "camera_model":     camera_model,
        "ipc_connected":    ipc_ok,
        "m7_heartbeat_ok":  m7_hb_ok,
        "motor_connected":  motor_connected,
        "motor_model":      motor_model,
        "active_alarms":    active_alarms,
        "uptime_s":         round(uptime_s, 1),
        "cpu_temp_c":       cpu_temp,
        "sdk_version":      SDK_VERSION,
        "driver_probe":     driver_probe,
    })


# ---------------------------------------------------------------------------
# GET /api/system/version
# ---------------------------------------------------------------------------

@router.get("/version", response_model=ApiResponse)
async def get_system_version(
    ipc: IpcClient = Depends(_ipc),
) -> ApiResponse:
    """Return SDK version and M7 firmware version."""
    m7_version: str | None = None
    m7_ts: int | None = None

    if ipc.connected:
        try:
            import struct
            resp = await asyncio.wait_for(
                ipc.send_recv(MSG_DIAG_GET_VERSION), timeout=1.0
            )
            # Version payload: major(1B) minor(1B) patch(1B) reserved(1B) build_ts(4B)
            if len(resp.payload) >= 8:
                major, minor, patch, _, ts = struct.unpack_from("<BBBBI", resp.payload)
                m7_version = f"{major}.{minor}.{patch}"
                m7_ts = ts
        except Exception as exc:
            log.debug("Version query failed: %s", exc)

    return ok({
        "sdk_version":         SDK_VERSION,
        "m7_firmware":         m7_version,
        "m7_build_timestamp":  m7_ts,
    })


# ---------------------------------------------------------------------------
# POST /api/system/reboot
# ---------------------------------------------------------------------------

@router.post("/reboot", response_model=ApiResponse)
async def system_reboot(
    body: SystemRebootRequest,
) -> ApiResponse:
    """
    Schedule a system reboot.

    Requires confirm=true in the request body.
    The reboot is delayed by 2 seconds to allow the HTTP response to be sent.
    """
    if not body.confirm:
        return err("confirm must be true to execute reboot", "REBOOT_NOT_CONFIRMED")

    log.warning("System reboot requested via REST API — rebooting in 2 s")

    async def _deferred_reboot():
        await asyncio.sleep(2.0)
        os.system("reboot")  # noqa: S605  (intentional system reboot)

    asyncio.create_task(_deferred_reboot())

    return ok({"message": "Reboot scheduled in 2 seconds"})


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _read_cpu_temp() -> float | None:
    """Read i.MX8MP SoC temperature from thermal zone sysfs."""
    thermal_paths = [
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/class/thermal/thermal_zone1/temp",
    ]
    for path in thermal_paths:
        try:
            with open(path) as f:
                millideg = int(f.read().strip())
                return round(millideg / 1000.0, 1)
        except (OSError, ValueError):
            continue
    return None
