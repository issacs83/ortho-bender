"""
test_homing.py — Limit-switch homing: service plan/state logic + /limits API.

Uses a stub bench backend (no hardware): verifies axis filtering, Hz
computation from calibration, homed/error bookkeeping, and the REST
surface. The spidev home_axis motion engine itself is hardware-bound and
is verified live on the bench.
"""

import asyncio

import pytest

from server.services.motor_service import MotorService


class _StubBench:
    """Minimal bench backend: LIFT(cs0)/BEND(cs1) switches, FEED none."""
    is_real_hardware = True

    def __init__(self):
        self.positions = {0: 0, 1: 0, 2: 0, 3: 0}
        self.limit = {0: False, 1: False}
        self.home_calls: list[tuple] = []
        self.pulse_calls: list[tuple] = []
        self.fail_cs: int | None = None
        self.limit_guard = True
        self.hold_axes: set[int] = set()
        self.hold_cs = 8
        self.homed_persist: set[int] = set()

    async def pulse_step(self, cs, steps, freq, direction, profile=None):
        self.pulse_calls.append((cs, steps, freq, direction))

    async def _hold_chip(self, cs):
        pass

    async def _silence_chip(self, cs):
        pass

    def _save_state(self):
        pass

    def limit_active(self, cs):
        return self.limit.get(cs)

    def get_axis_signals(self, cs):
        return {"vmot": True, "en": False, "sg": False, "dir": 0,
                "step": False, "limit": self.limit_active(cs)}

    async def home_axis(self, cs, direction, seek_hz, latch_hz,
                        backoff_steps, timeout_s=60.0, park_steps=0,
                        max_travel_steps=None, search_range_steps=None,
                        reduced_cs=0, rotary=False, preprobe_steps=0,
                        stall_abort=False):
        self.home_calls.append((cs, direction, seek_hz, latch_hz,
                                backoff_steps, park_steps))
        self.last_kwargs = dict(max_travel_steps=max_travel_steps,
                                search_range_steps=search_range_steps,
                                reduced_cs=reduced_cs, rotary=rotary,
                                preprobe_steps=preprobe_steps,
                                stall_abort=stall_abort)
        if self.fail_cs == cs:
            raise RuntimeError(f"axis cs={cs} homing timeout")
        self.positions[cs] = park_steps


@pytest.fixture
def svc():
    return MotorService(ipc=None, spidev_backend=_StubBench())


async def _wait_homing_done(svc, timeout=2.0):
    for _ in range(int(timeout / 0.01)):
        if not svc._bench_homing:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("homing sequence did not finish")


@pytest.mark.asyncio
async def test_home_all_homes_lift_and_bend(svc):
    await svc.home(0)
    await _wait_homing_done(svc)
    called_cs = [c[0] for c in svc._spi_backend.home_calls]
    assert called_cs == [0, 1]          # LIFT then BEND
    st = svc.limit_status()
    assert sorted(st["homed"]) == [1, 3]
    assert st["error"] is None and st["homing"] is False


@pytest.mark.asyncio
async def test_home_mask_selects_single_axis(svc):
    await svc.home(0x02)                # BEND only
    await _wait_homing_done(svc)
    assert [c[0] for c in svc._spi_backend.home_calls] == [1]
    assert svc.limit_status()["homed"] == [1]


@pytest.mark.asyncio
async def test_home_rejects_axes_without_switch(svc):
    with pytest.raises(RuntimeError):
        await svc.home(0x01)            # FEED has no switch


@pytest.mark.asyncio
async def test_home_failure_recorded_and_sequence_stops(svc):
    svc._spi_backend.fail_cs = 0        # LIFT fails
    await svc.home(0)
    await _wait_homing_done(svc)
    st = svc.limit_status()
    assert "timeout" in (st["error"] or "")
    assert st["homed"] == []            # BEND not attempted after failure
    assert [c[0] for c in svc._spi_backend.home_calls] == [0]


@pytest.mark.asyncio
async def test_home_speeds_scale_with_calibration(svc):
    class _Cal:
        def steps_per_unit(self, axis):
            return 400.0
        def distance_limit(self, axis):
            return 100.0
    svc.set_calibration(_Cal())
    await svc.home(0x08)                # LIFT
    await _wait_homing_done(svc)
    _, _, seek_hz, latch_hz, backoff, park = svc._spi_backend.home_calls[0]
    assert seek_hz == 1600              # 4.0 u/s × 400
    assert latch_hz == 200              # 0.5 u/s × 400
    assert backoff == 400               # 1.0 u × 400
    assert park == -120                 # home_park=-0.3 u × 400 → inside window
    kw = svc._spi_backend.last_kwargs
    assert kw["search_range_steps"] == 6000   # 15 u × 400 (primary leg)
    assert kw["max_travel_steps"] == 44000    # 100 u × 1.1 × 400
    assert kw["reduced_cs"] == 0              # LIFT = gravity axis, full current
    assert kw["rotary"] is False              # LIFT = linear axis
    assert kw["preprobe_steps"] == 1200       # 3 u × 400 sank-below probe


@pytest.mark.asyncio
async def test_bend_homes_in_rotary_mode(svc):
    await svc.home(0x02)                # BEND
    await _wait_homing_done(svc)
    kw = svc._spi_backend.last_kwargs
    assert kw["rotary"] is True               # unidirectional, 1 window/rev
    assert kw["search_range_steps"] == 76000  # 380° (1 rev + margin) × 200
    assert kw["preprobe_steps"] == 0          # rotary needs no pre-probe
    assert kw["reduced_cs"] == 0              # CS=10 slippage — disabled


@pytest.mark.asyncio
async def test_limit_status_reflects_switch_state(svc):
    svc._spi_backend.limit[1] = True
    st = svc.limit_status()
    assert st["limits"] == {3: False, 1: True}


@pytest.mark.asyncio
async def test_home_blocked_during_estop(svc):
    svc._bench_estop_active = True
    with pytest.raises(RuntimeError):
        await svc.home(0)


@pytest.mark.asyncio
async def test_homed_flag_persisted_to_backend(svc):
    await svc.home(0x08)                # LIFT
    await _wait_homing_done(svc)
    assert 3 in svc._spi_backend.homed_persist
    assert 3 in svc.limit_status()["homed"]


@pytest.mark.asyncio
async def test_protection_get_and_set(svc):
    be = svc._spi_backend
    be.hold_axes = {0}
    assert svc.get_protection() == {
        "limit_stop": True, "hold_enabled": True, "hold_cs": 8}
    p = await svc.set_protection(limit_stop=False, hold_enabled=False, hold_cs=5)
    assert p == {"limit_stop": False, "hold_enabled": False, "hold_cs": 5}
    assert be.limit_guard is False and be.hold_axes == set()


@pytest.mark.asyncio
async def test_move_to_is_absolute(svc):
    be = svc._spi_backend
    be.positions[1] = 400               # BEND counter at +2.0 units
    await svc.move_to(1, -1.0, 5)       # target -1.0 → delta -3.0 units
    cs, steps, freq, direction = be.pulse_calls[0]
    assert cs == 1 and direction == -1
    assert steps == 600                 # 3.0 u × 200 steps/u
