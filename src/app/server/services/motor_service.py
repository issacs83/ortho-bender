"""
motor_service.py — Motor control service layer.

Translates REST API calls into IPC commands sent to the M7 FreeRTOS core.
Decodes MSG_STATUS_MOTION responses into AxisStatus objects.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import struct
import logging
from typing import Optional

from ..models.schemas import (
    AxisId,
    AxisStatus,
    MotionState,
    MotorStatusResponse,
)
from .ipc_client import (
    IpcClient,
    MSG_MOTION_EXECUTE_BCODE,
    MSG_MOTION_JOG,
    MSG_MOTION_HOME,
    MSG_MOTION_STOP,
    MSG_MOTION_ESTOP,
    MSG_MOTION_RESET,
    MSG_STATUS_MOTION,
    MSG_STATUS_TMC,
    build_jog_payload,
    build_home_payload,
    build_bcode_payload,
)

log = logging.getLogger(__name__)

# Payload struct formats (must mirror ipc_protocol.h)
_MOTION_STATUS_FMT  = "<B4f4fHHB"     # state + pos[4] + vel[4] + curr_step + total + axis_mask
_MOTION_STATUS_SIZE = struct.calcsize(_MOTION_STATUS_FMT)
_TMC_STATUS_FMT     = "<4I4H4H4i"     # drv_status[4] + sg_result[4] + cs_actual[4] + xactual[4]
_TMC_STATUS_SIZE    = struct.calcsize(_TMC_STATUS_FMT)


class MotorService:
    """
    High-level motor control interface.

    All methods are async and safe to call from FastAPI route handlers.
    """

    def __init__(self, ipc: IpcClient) -> None:
        self._ipc = ipc
        # Cache last TMC status so motor status can include it even between polls
        self._last_tmc: Optional[bytes] = None

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def get_status(self) -> MotorStatusResponse:
        """Query current motor position, velocity, and state from M7."""
        resp = await self._ipc.send_recv(MSG_STATUS_MOTION)
        return self._parse_motion_status(resp.payload)

    def _parse_motion_status(self, payload: bytes) -> MotorStatusResponse:
        if len(payload) < _MOTION_STATUS_SIZE:
            log.warning("Motion status payload too short: %d bytes", len(payload))
            # Return safe default
            return MotorStatusResponse(
                state=MotionState.IDLE,
                axes=[],
                current_step=0,
                total_steps=0,
                axis_mask=0,
            )

        raw = struct.unpack_from(_MOTION_STATUS_FMT, payload)
        state       = raw[0]
        positions   = list(raw[1:5])
        velocities  = list(raw[5:9])
        curr_step   = raw[9]
        total_steps = raw[10]
        axis_mask   = raw[11]

        # Parse optional TMC status if appended (concatenated payload)
        tmc_raw = None
        if len(payload) >= _MOTION_STATUS_SIZE + _TMC_STATUS_SIZE:
            tmc_raw = struct.unpack_from(_TMC_STATUS_FMT, payload, _MOTION_STATUS_SIZE)

        axes = []
        for i in range(4):
            if not (axis_mask & (1 << i)):
                continue
            axes.append(AxisStatus(
                axis=AxisId(i),
                position=positions[i],
                velocity=velocities[i],
                drv_status=tmc_raw[i] if tmc_raw else 0,
                sg_result=tmc_raw[4 + i] if tmc_raw else 0,
                cs_actual=tmc_raw[8 + i] if tmc_raw else 0,
            ))

        return MotorStatusResponse(
            state=MotionState(state),
            axes=axes,
            current_step=curr_step,
            total_steps=total_steps,
            axis_mask=axis_mask,
        )

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def move(self, axis: int, distance: float, speed: float) -> MotorStatusResponse:
        """
        Move a single axis by the given distance at the given speed.

        Internally translates to a single-step B-code sequence so the M7
        trajectory manager handles acceleration/deceleration uniformly.
        """
        # Map axis → B-code fields
        L_mm    = distance if axis == AxisId.FEED else 0.0
        beta    = distance if axis == AxisId.ROTATE else 0.0
        theta   = distance if axis == AxisId.BEND else 0.0

        payload = build_bcode_payload(
            steps=[(L_mm, beta, theta)],
            material_id=0,          # SS_304 default
            wire_diameter_mm=0.457,
        )
        await self._ipc.send_recv(MSG_MOTION_EXECUTE_BCODE, payload)
        return await self.get_status()

    async def jog(
        self, axis: int, direction: int, speed: float, distance: float = 0.0
    ) -> MotorStatusResponse:
        """Jog an axis continuously or for a fixed distance."""
        payload = build_jog_payload(axis, direction, speed, distance)
        await self._ipc.send_recv(MSG_MOTION_JOG, payload)
        return await self.get_status()

    async def home(self, axis_mask: int = 0) -> MotorStatusResponse:
        """Execute homing sequence for the specified axes."""
        payload = build_home_payload(axis_mask)
        await self._ipc.send_recv(MSG_MOTION_HOME, payload)
        return await self.get_status()

    async def stop(self) -> MotorStatusResponse:
        """Controlled deceleration stop."""
        await self._ipc.send_recv(MSG_MOTION_STOP)
        return await self.get_status()

    async def estop(self) -> MotorStatusResponse:
        """
        Software E-STOP — immediate halt via IPC.

        Note: hardware E-STOP path is parallel (M7 GPIO ISR + DRV_ENN).
        This call is the SW path only.
        """
        await self._ipc.send_recv(MSG_MOTION_ESTOP)
        return await self.get_status()

    async def reset(self) -> MotorStatusResponse:
        """Reset motor fault state and re-enable drivers."""
        # TODO: add axis_mask payload if M7 firmware supports per-axis reset
        await self._ipc.send_recv(MSG_MOTION_RESET)
        return await self.get_status()

    # ------------------------------------------------------------------
    # Bending sequence (delegated from BendingService)
    # ------------------------------------------------------------------

    async def execute_bcode(
        self,
        steps: list[tuple[float, float, float]],
        material_id: int,
        wire_diameter_mm: float,
    ) -> None:
        """
        Send a full B-code sequence to the M7.

        Blocks until the sequence is dispatched (does NOT wait for completion).
        The caller should poll /api/bending/status or subscribe to /ws/system
        for the MSG_STATUS_BCODE_COMPLETE event.
        """
        payload = build_bcode_payload(steps, material_id, wire_diameter_mm)
        await self._ipc.send_recv(MSG_MOTION_EXECUTE_BCODE, payload)
        log.info("B-code sequence dispatched: %d steps, material=%d", len(steps), material_id)
