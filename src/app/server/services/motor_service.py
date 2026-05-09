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
    MSG_MOTION_SET_DRV_ENABLE,
    MSG_STATUS_MOTION,
    MSG_STATUS_TMC,
    build_jog_payload,
    build_home_payload,
    build_bcode_payload,
    build_drv_enable_payload,
)

log = logging.getLogger(__name__)

# Payload struct formats (must mirror ipc_protocol.h)
_MOTION_STATUS_FMT  = "<B4f4fHHBB"    # state + pos[4] + vel[4] + curr_step + total + axis_mask + drv_enabled
_MOTION_STATUS_SIZE = struct.calcsize(_MOTION_STATUS_FMT)
_TMC_STATUS_FMT     = "<4I4H4H4i"     # drv_status[4] + sg_result[4] + cs_actual[4] + xactual[4]
_TMC_STATUS_SIZE    = struct.calcsize(_TMC_STATUS_FMT)


class MotorService:
    """
    High-level motor control interface.

    All methods are async and safe to call from FastAPI route handlers.
    """

    def __init__(self, ipc: IpcClient, spidev_backend=None) -> None:
        self._ipc = ipc
        # Optional spidev backend — when M7 IPC is in mock mode and a
        # SpidevMotorBackend is provided, motor commands run on the real
        # Veyron 1×2A bench instead of dispatching IPC commands to a
        # non-existent M7. Allows the FastAPI server to drive motors
        # directly on the EVK test bench.
        self._spi_backend = spidev_backend
        # Axis ID → spidev cs (cs=0 LIFT, 1 BEND, 2 FEED). ROTATE not on bench.
        self._axis_to_cs = {
            int(AxisId.LIFT):   0,
            int(AxisId.BEND):   1,
            int(AxisId.FEED):   2,
            int(AxisId.ROTATE): None,
        }
        # Cache last TMC status so motor status can include it even between polls
        self._last_tmc: Optional[bytes] = None

    @property
    def has_bench(self) -> bool:
        return self._spi_backend is not None

    async def _bench_pulse(
        self,
        axis: int,
        distance: float,
        speed: float,
    ) -> None:
        """Translate move/jog (distance, speed) into a bench pulse_step call.

        Conservative mapping (distance/speed are unit-agnostic on bench):
          1 unit distance = 200 microsteps  (matches single full revolution
                                             at 200 step/rev, or 5 mm lead)
          1 unit speed    = 200 Hz step rate
        Hz hard-clamped to [200, 8000] by the backend.
        """
        cs = self._axis_to_cs.get(axis)
        if cs is None:
            raise ValueError(f"Axis {axis} is not present on the bench")
        steps = max(1, int(abs(distance) * 200))
        freq  = max(200, min(int(abs(speed) * 200), 8000))
        direction = 1 if distance >= 0 else -1
        await self._spi_backend.pulse_step(cs, steps, freq, direction)

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
                driver_enabled=False,
            )

        raw = struct.unpack_from(_MOTION_STATUS_FMT, payload)
        state          = raw[0]
        positions      = list(raw[1:5])
        velocities     = list(raw[5:9])
        curr_step      = raw[9]
        total_steps    = raw[10]
        axis_mask      = raw[11]
        driver_enabled = bool(raw[12])

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
            driver_enabled=driver_enabled,
        )

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def move(self, axis: int, distance: float, speed: float) -> MotorStatusResponse:
        """
        Move a single axis by the given distance at the given speed.

        - Bench mode (spidev backend): direct pulse_step on Veyron board.
        - Production (M7 IPC): single-step B-code → M7 trajectory manager.
        """
        if self.has_bench:
            await self._bench_pulse(axis, distance, speed)
            return await self.get_status()

        # IPC path (M7 production)
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
        """Jog an axis continuously or for a fixed distance.

        Bench mode: jog defaults to 1-revolution (200 steps) when distance=0,
        sign matches `direction` argument. Production: dispatches MSG_MOTION_JOG.
        """
        if self.has_bench:
            d = distance if distance != 0.0 else 1.0
            d *= (1 if direction >= 0 else -1)
            await self._bench_pulse(axis, d, speed if speed > 0 else 10.0)
            return await self.get_status()

        payload = build_jog_payload(axis, direction, speed, distance)
        await self._ipc.send_recv(MSG_MOTION_JOG, payload)
        return await self.get_status()

    async def home(self, axis_mask: int = 0) -> MotorStatusResponse:
        """Execute homing sequence for the specified axes.

        Bench mode: no homing switches — returns status only (no movement).
        """
        if self.has_bench:
            log.info("home() ignored on bench (no homing switches)")
            return await self.get_status()
        payload = build_home_payload(axis_mask)
        await self._ipc.send_recv(MSG_MOTION_HOME, payload)
        return await self.get_status()

    async def stop(self) -> MotorStatusResponse:
        """Controlled deceleration stop.

        Bench mode: backend's pulse_step finalize handles silence + PWM disable.
        """
        if self.has_bench:
            return await self.get_status()
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

    async def enable_drivers(self, axis_mask: int = 0) -> MotorStatusResponse:
        """
        Assert TMC260C-PA DRV_ENN (coils energized).

        Standard practice after a disconnect: the drivers will hold position
        again. The M7 handler is authoritative; this just dispatches the IPC.
        """
        payload = build_drv_enable_payload(True, axis_mask)
        await self._ipc.send_recv(MSG_MOTION_SET_DRV_ENABLE, payload)
        return await self.get_status()

    async def disable_drivers(self, axis_mask: int = 0) -> MotorStatusResponse:
        """
        De-energize TMC260C-PA coils by releasing DRV_ENN.

        The M7 refuses this if any axis in the mask is moving. Callers should
        `stop()` first, then `disable_drivers()`.
        """
        payload = build_drv_enable_payload(False, axis_mask)
        await self._ipc.send_recv(MSG_MOTION_SET_DRV_ENABLE, payload)
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
