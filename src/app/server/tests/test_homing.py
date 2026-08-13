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
        self.fail_cs: int | None = None

    def limit_active(self, cs):
        return self.limit.get(cs)

    def get_axis_signals(self, cs):
        return {"vmot": True, "en": False, "sg": False, "dir": 0,
                "step": False, "limit": self.limit_active(cs)}

    async def home_axis(self, cs, direction, seek_hz, latch_hz,
                        backoff_steps, timeout_s=60.0, park_steps=0,
                        max_travel_steps=None):
        self.home_calls.append((cs, direction, seek_hz, latch_hz,
                                backoff_steps, park_steps))
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
    assert park == 0                    # home_park=0 → rest ON the trip point


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
