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
from pydantic import BaseModel

from ..services.camera_service import CameraService
from ..services.ipc_client import (
    IpcClient,
    MSG_DIAG_GET_VERSION,
    MSG_STATUS_HEARTBEAT,
)
from ..services.motor_service import MotorService
from ..services.psu_service import PSU_PRESETS, PsuService

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


def _psu_service(request: Request) -> PsuService:
    return request.app.state.psu_service


class PsuSelectRequest(BaseModel):
    psu_id: str


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

    bench_mode = bool(getattr(motor, "has_bench", False))

    # On the bench there is no M7 — skip the heartbeat round-trip entirely
    # (the mock IPC would just return IDLE / wdt_ok=0 and waste the 0.5 s
    # timeout when the OS is busy). Production keeps the M7 path.
    if ipc_ok and not bench_mode:
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
    elif bench_mode:
        # No M7 on the bench — heartbeat reads as healthy, link is whatever
        # the mock IPC reports, alarms come from the bench fault service
        # (none right now). Motion state is filled in below from MotorService.
        m7_hb_ok = True

    # On the bench MotorService owns the real state (including the sticky
    # _bench_estop_active flag) — see _bench_status().
    if bench_mode:
        try:
            bench_ms = await motor.get_status()
            motion_state = bench_ms.state
        except Exception as exc:
            log.debug("Bench motor status query failed: %s", exc)

    # Camera model — read from actual hardware, not hardcoded.
    # CameraService.get_status is async (returns a CameraStatus dataclass);
    # NullCameraService keeps it sync as a dict for the no-camera path.
    # Treat both shapes uniformly via _attr.
    import inspect as _inspect
    cam_raw = camera.get_status()
    if _inspect.iscoroutine(cam_raw):
        cam_raw = await cam_raw

    def _attr(obj, name, default=None):
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    cam_connected_raw = bool(_attr(cam_raw, "connected", False))
    cam_backend       = _attr(cam_raw, "backend", "") or ""
    cam_device        = _attr(cam_raw, "device")
    camera_model: str | None = _attr(cam_device, "model") or _attr(cam_raw, "device_id")

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
        "camera_connected": cam_connected_raw and cam_backend != "mock",
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
# GET / POST /api/system/psu — Power-supply preset selection
# ---------------------------------------------------------------------------

def _psu_to_dict(psu) -> dict:
    return {"id": psu.id, "label": psu.label, "volts": psu.volts, "amps": psu.amps, "cs_cap": psu.cs_cap}


@router.get("/psu", response_model=ApiResponse)
async def get_psu(svc: PsuService = Depends(_psu_service)) -> ApiResponse:
    """Return the active PSU preset and the available list."""
    return ok({
        "active":  _psu_to_dict(svc.psu),
        "presets": [_psu_to_dict(p) for p in PSU_PRESETS],
    })


@router.post("/psu", response_model=ApiResponse)
async def set_psu(
    body: PsuSelectRequest,
    svc: PsuService = Depends(_psu_service),
) -> ApiResponse:
    """Persist a new PSU preset selection (used by /diag/register guard)."""
    try:
        active = svc.set_psu(body.psu_id)
        return ok({"active": _psu_to_dict(active)})
    except ValueError as exc:
        return err(str(exc), "INVALID_PSU_ID")


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
