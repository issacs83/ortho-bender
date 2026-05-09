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
    AxisSignals,
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
        # Long-press jog: a single bench async task at a time
        import asyncio as _asyncio
        self._asyncio = _asyncio
        self._bench_jog_task: Optional[_asyncio.Task] = None
        # Sticky E-STOP flag — stays True until enable_drivers/reset clears it,
        # so the dashboard can show ESTOP instead of bouncing back to IDLE the
        # moment the jog task finishes. Without this the bar would keep moving
        # because _bench_status returned JOGGING while the cancel was in flight.
        self._bench_estop_active: bool = False
        # Per-axis steps/unit calibration. Late-injected via set_calibration()
        # so main.py can wire it after MotorService construction.
        self._calibration = None  # type: ignore[assignment]
        # Cache last TMC status so motor status can include it even between polls
        self._last_tmc: Optional[bytes] = None

    @property
    def has_bench(self) -> bool:
        return self._spi_backend is not None

    def set_calibration(self, cal) -> None:
        """Inject the CalibrationService used for axis steps/unit conversion."""
        self._calibration = cal

    def _ensure_not_estop(self, action: str) -> None:
        """HARD GATE — refuse motion commands while bench E-STOP is latched.

        2026-05-09 incident: jog buttons stayed active in the dashboard while
        the ESTOP indicator was set, and the operator was able to drive the
        motor with a single press. The backend is the last line of defence —
        even with frontend disable in place, any direct API call must hit
        this and be rejected until enable_drivers()/reset() clears the flag.
        """
        if self._bench_estop_active:
            raise RuntimeError(
                f"E-STOP active — refusing {action}. Press RESET E-STOP "
                f"(or POST /api/motor/reset) before issuing motion commands."
            )

    async def jog_start(
        self,
        axis: int,
        direction: int,
        speed: float = 1000.0,
        continuous: bool = False,
    ) -> dict:
        """Begin bench rotation.

        Two modes:
          - continuous=False (default, used by the long-press ◀ / ▶
            buttons): 5 s safety-fallback duration. Frontend is expected
            to send jog_stop on pointerup; the 5 s cap protects against
            dropped stop requests.
          - continuous=True (used by single-click ◀◀ / ▶▶ buttons):
            60 s duration. Stays on until the user presses the row's
            STOP button (which calls jog_stop). 60 s caps unattended
            runtime in case the user forgets to stop.
        """
        self._ensure_not_estop("jog_start")
        if not self.has_bench:
            payload = build_jog_payload(axis, direction, speed, 0.0)
            await self._ipc.send_recv(MSG_MOTION_JOG, payload)
            return {"status": "jog_started", "bench": False}

        await self.jog_stop()

        cs = self._axis_to_cs.get(axis)
        if cs is None:
            raise ValueError(f"Axis {axis} is not present on the bench")

        # Speed is in axis-native user units (mm/s for FEED/LIFT, deg/s for
        # BEND/ROTATE). The CalibrationService converts to step rate so an
        # operator entering "10 mm/s" feeds the wire at the calibrated rate
        # regardless of motor microstepping or lead-screw spec. 4000 Hz is
        # still the bench safety cap to keep older mechanicals safe.
        cal = self._calibration
        steps_per_unit = cal.steps_per_unit(axis) if cal else 200.0
        speed_clamped = min(abs(speed), cal.speed_limit(axis) if cal else 20.0)
        freq = int(speed_clamped * steps_per_unit)
        freq = max(200, min(freq, 4000))
        max_duration_s = 60 if continuous else 5
        steps = freq * max_duration_s
        dir_sign = 1 if direction >= 0 else -1
        log.info("jog_start axis=%d cs=%d freq=%dHz dir=%+d (max %ds, continuous=%s)",
                 axis, cs, freq, dir_sign, max_duration_s, continuous)
        self._bench_jog_task = self._asyncio.create_task(
            self._spi_backend.pulse_step(cs, steps, freq, dir_sign)
        )
        return {
            "status": "jog_started",
            "bench": True,
            "axis": axis,
            "freq_hz": freq,
            "continuous": continuous,
            "max_duration_s": max_duration_s,
        }

    async def jog_stop(self) -> dict:
        """Stop the current bench jog (long-press release).

        Cancels the background pulse_step task. Its finally block disables
        PWM and silences the active chip. Belt-and-suspenders: also call
        backend pwm_disable to ensure outputs are clean. We do NOT silence
        every chip here (only the running one is touched by pulse_step's
        finally) to minimise deadtime between rapid taps.
        """
        if self._bench_jog_task is not None and not self._bench_jog_task.done():
            self._bench_jog_task.cancel()
            try:
                await self._bench_jog_task
            except (self._asyncio.CancelledError, Exception):
                pass
        self._bench_jog_task = None
        if self.has_bench:
            try:
                await self._spi_backend._pwm_disable()
            except Exception:
                pass
        return {"status": "jog_stopped"}

    async def _bench_pulse(
        self,
        axis: int,
        distance: float,
        speed: float,
    ) -> None:
        """Translate move/jog (distance, speed) into a bench pulse_step call.

        Conservative mapping (units are application-defined on bench):
          1 unit distance = 200 microsteps   (~1 full rev at 200 step/rev)
          1 unit speed    = 1 Hz step rate   (frontend usually sends large
                                              values like 1000, treated as Hz)
        Safety clamps:
          - distance |abs| ≤ 50 units (≤ 10 000 microsteps)
          - freq         ≤ 4000 Hz (single-axis bench safe)
          - duration     ≤ 10 s
        """
        cs = self._axis_to_cs.get(axis)
        if cs is None:
            raise ValueError(f"Axis {axis} is not present on the bench")

        # ---- Safety clamps for frontend-supplied values ----
        # frontend may send large numbers (speed=1000 etc.); treat speed
        # directly as Hz with safe upper bound.
        cal = self._calibration
        steps_per_unit = cal.steps_per_unit(axis) if cal else 200.0
        dist_limit = cal.distance_limit(axis) if cal else 50.0
        speed_lim = cal.speed_limit(axis) if cal else 20.0
        clamped_distance = max(-dist_limit, min(dist_limit, distance))
        steps = max(1, int(abs(clamped_distance) * steps_per_unit))
        speed_clamped = min(abs(speed), speed_lim)
        freq = int(speed_clamped * steps_per_unit)
        freq = max(200, min(freq, 4000))
        # Cap duration to 10 s
        if steps / freq > 10.0:
            steps = freq * 10
        direction = 1 if distance >= 0 else -1
        log.info(
            "bench jog axis=%d cs=%d steps=%d freq=%dHz dir=%+d (req dist=%.3f speed=%.3f)",
            axis, cs, steps, freq, direction, distance, speed,
        )
        await self._spi_backend.pulse_step(cs, steps, freq, direction)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def get_status(self) -> MotorStatusResponse:
        """Query current motor position, velocity, and state.

        Bench mode: synthesize status from SpidevMotorBackend.positions
        (real microstep counts driven via pulse_step). Skips IPC entirely.
        Production: query M7 via IPC.
        """
        if self.has_bench:
            return self._bench_status()
        resp = await self._ipc.send_recv(MSG_STATUS_MOTION)
        return self._parse_motion_status(resp.payload)

    def _bench_status(self) -> MotorStatusResponse:
        """Build MotorStatusResponse from spidev backend's tracked positions.

        Spidev cs (0/1/2) = LIFT/BEND/FEED. Map back to AxisId:
          cs=0 → AxisId.LIFT (3)
          cs=1 → AxisId.BEND (1)
          cs=2 → AxisId.FEED (0)
        AxisId.ROTATE (2) is not on the bench (skipped).
        """
        bench_pos = getattr(self._spi_backend, "positions", {})
        # cs → AxisId int
        cs_to_axis = {0: int(AxisId.LIFT), 1: int(AxisId.BEND), 2: int(AxisId.FEED)}
        axes = []
        axis_mask = 0
        signals_fn = getattr(self._spi_backend, "get_axis_signals", None)
        for cs, axis_int in cs_to_axis.items():
            pos_steps = bench_pos.get(cs, 0)
            # Convert microsteps back to display units (inverse of _bench_pulse: 200 step = 1 unit)
            pos_units = pos_steps / 200.0
            sig_dict = signals_fn(cs) if callable(signals_fn) else None
            axes.append(AxisStatus(
                axis=AxisId(axis_int),
                position=pos_units,
                velocity=0.0,
                drv_status=0,
                sg_result=int(bool(sig_dict.get("sg"))) if sig_dict else 0,
                cs_actual=19,  # CS=19 hardcoded safety value
                signals=AxisSignals(**sig_dict) if sig_dict else None,
            ))
            axis_mask |= (1 << axis_int)
        # Sort by axis id (consistent with frontend ordering 0..3)
        axes.sort(key=lambda a: int(a.axis))
        # Reflect actual motion in the state field so the dashboard's
        # "State: IDLE/JOGGING" indicator matches what the bench is doing.
        # ESTOP is sticky and wins over JOGGING — once the operator hits
        # E-STOP the dashboard must keep showing it until the condition
        # is explicitly cleared by enable_drivers()/reset(), even though
        # the cancelled jog task itself would let state fall back to IDLE.
        bench_jog_active = (
            self._bench_jog_task is not None and not self._bench_jog_task.done()
        )
        if self._bench_estop_active:
            state = MotionState.ESTOP
        elif bench_jog_active:
            state = MotionState.JOGGING
        else:
            state = MotionState.IDLE
        return MotorStatusResponse(
            state=state,
            axes=axes,
            current_step=0,
            total_steps=0,
            axis_mask=axis_mask,
            driver_enabled=True,
        )

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
        self._ensure_not_estop("move")
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
        self._ensure_not_estop("jog")
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
        self._ensure_not_estop("home")
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
        """Software E-STOP — immediate halt.

        Bench: disable PWM and silence all chips synchronously, regardless
        of which axis (if any) is currently running. Critical safety path.
        Production: hardware E-STOP runs in parallel via M7 GPIO ISR + DRV_ENN.
        """
        if self.has_bench:
            # 1) Kill PWM + silence chips immediately. Coils dead first so the
            #    motor is mechanically safe even if step 2 raises.
            try:
                await self._spi_backend._pwm_disable()
            except Exception as exc:
                log.warning("E-STOP PWM disable failed: %s", exc)
            for cs in (0, 1, 2):
                try:
                    await self._spi_backend._silence_chip(cs)
                except Exception as exc:
                    log.warning("E-STOP silence cs=%d failed: %s", cs, exc)
            # 2) Cancel any in-flight jog task. Without this the pulse_step_multi
            #    loop keeps incrementing self._spi_backend.positions even though
            #    the motor is electrically stopped, which makes the dashboard's
            #    progress bar / position readout drift after E-STOP. The user
            #    saw exactly this: motor stopped, UI kept counting.
            if self._bench_jog_task is not None and not self._bench_jog_task.done():
                self._bench_jog_task.cancel()
                try:
                    await self._bench_jog_task
                except (self._asyncio.CancelledError, Exception):
                    pass
            self._bench_jog_task = None
            # 3) Mark sticky ESTOP so _bench_status reports MotionState.ESTOP
            #    until enable_drivers() / reset() acknowledges the operator
            #    has cleared the condition.
            self._bench_estop_active = True
            log.warning("E-STOP triggered on bench: all axes silenced + jog task cancelled")
            return await self.get_status()
        await self._ipc.send_recv(MSG_MOTION_ESTOP)
        return await self.get_status()

    async def enable_drivers(self, axis_mask: int = 0) -> MotorStatusResponse:
        """
        Assert TMC260C-PA DRV_ENN (coils energized).

        Standard practice after a disconnect: the drivers will hold position
        again. The M7 handler is authoritative; this just dispatches the IPC.

        Also clears the sticky bench E-STOP flag — re-enabling the drivers
        is the operator's explicit acknowledgement that the E-STOP condition
        has been resolved.

        IMPORTANT — DO NOT _init_chip every cs here. PWM4 is shared across
        all three TMC260C-PA chips: the silence state on non-target axes is
        what stops them from stepping along with the target. A previous
        version of this method ran _init_chip on cs=0/1/2 to clear the SG
        LED, but that put every chopper into the ON state, so the next jog
        drove all three motors in parallel (2026-05-09 incident). The chips
        stay silenced after E-STOP; the next jog_start re-inits only its
        own axis. SG LED on the silenced axes is the expected indication
        that they are inactive — it clears the moment that axis is jogged.
        """
        if self.has_bench:
            self._bench_estop_active = False
            return await self.get_status()
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
        """Reset motor fault state and clear bench E-STOP latch.

        Same constraint as enable_drivers: do NOT _init_chip every cs here
        — that would chopper-ON all three chips and the next jog would
        drive all axes (PWM is shared). Chips stay silenced; next jog_start
        re-inits only the target axis.
        """
        if self.has_bench:
            self._bench_estop_active = False
            return await self.get_status()
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
