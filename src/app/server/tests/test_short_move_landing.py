"""
test_short_move_landing.py — a short move must stop where it was told.

A 0.1 mm LIFT command used to travel 0.12 mm, every time, and ten of them
accumulated 0.2 mm. Long moves were unaffected, so the defect sat exactly
where a machine aiming at 0.1 mm control can least afford it.

The cause was the ramp polling its abort condition on a FIXED sub-sleep:
at the ~400 Hz a short triangle profile reaches, 10 ms is four steps, so
the axis was already four steps past the target before anything checked.
The fix shrinks the slice as the axis closes in. Nothing about that needs
hardware to verify, and a regression would be silent -- the axis would
simply overshoot again -- so it is pinned here.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio

import pytest

from server.services.spi_backend import SpidevMotorBackend


class _RampOnlyBackend(SpidevMotorBackend):
    """Real _ramp, with the PWM write replaced by a recorder.

    _ramp is the code under test, so it must be the production method --
    a reimplementation of the sub-sleep here would pass while the real
    loop overshot.
    """

    def __init__(self):
        super().__init__()
        self.hz_writes: list[int] = []

    async def _pwm_set_hz(self, hz):
        self.hz_writes.append(int(hz))


AXIS = 0
DIRECTION = 1


class _VirtualClock:
    """Deterministic time for _ramp: sleeps advance a counter, not the wall.

    _ramp credits steps from elapsed time x frequency, so with real sleeps
    this file measures host scheduling as much as the algorithm. A real
    asyncio.sleep(1 ms) -- the _RAMP_SUBSLEEP_MIN_S floor -- returns late
    under load, and late means extra steps credited: [100,400] failed about
    one run in three on main that way, always at +3 against a tolerance
    of 2, because a 100-step target reaches a higher f_cur before aborting
    and each millisecond of slop costs proportionally more.

    Advancing time by exactly the requested amount removes the host from
    the measurement without weakening it: the overshoot the fix targets is
    a function of slice length x frequency, and both are preserved here.
    Verified by mutation -- reverting the adaptive slice to a fixed 10 ms
    still fails the load-bearing cases under this clock.
    """

    def __init__(self, real_module):
        self._real = real_module
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t

    def __getattr__(self, name):          # everything else is the real time
        return getattr(self._real, name)


class _VirtualAsyncio:
    """asyncio with sleep() replaced by 'advance the clock, yield once'."""

    def __init__(self, real_module, clock: _VirtualClock):
        self._real = real_module
        self._clock = clock

    async def sleep(self, delay, result=None):
        self._clock.t += max(0.0, float(delay))
        await self._real.sleep(0)         # let the loop run, cost no wall time
        return result

    def __getattr__(self, name):
        return getattr(self._real, name)


def _run_ramp(target_steps: int, f_from=200, f_to=4000, rate=8000.0):
    """Accelerate toward f_to but abort once target_steps are emitted,
    exactly as pulse_step does. Returns steps actually credited."""
    from server.services import spi_backend as sb

    be = _RampOnlyBackend()
    be.positions[AXIS] = 0
    start = 0

    def travelled() -> int:
        return abs(be.positions.get(AXIS, 0) - start)

    async def go():
        await be._ramp(
            f_from, f_to, rate, "linear",
            track=(AXIS, DIRECTION),
            abort_cb=lambda: travelled() >= target_steps,
            remaining_cb=lambda: target_steps - travelled(),
        )

    clock = _VirtualClock(sb.time)
    real_time, real_asyncio = sb.time, sb.asyncio
    sb.time, sb.asyncio = clock, _VirtualAsyncio(real_asyncio, clock)
    try:
        asyncio.run(go())
    finally:
        sb.time, sb.asyncio = real_time, real_asyncio
    return travelled()


# ---------------------------------------------------------------------------
# The regression itself
# ---------------------------------------------------------------------------

# f_from matters as much as the target. The bench move that failed had
# already reached roughly 400 Hz when it passed its 20-step target, which
# is where a fixed 10 ms slice costs four steps; starting from the 200 Hz
# floor the same target only costs two and the bug hides.
# LOAD-BEARING, re-measured under the virtual clock: reverting the adaptive
# slice to a fixed 10 ms fails [20,800], [100,400] and
# test_overshoot_does_not_grow_with_speed. Under real sleeps it failed only
# [20,800] and [40,400] -- host jitter was masking the reported case itself,
# which is the second reason the clock is virtual. [40,400] and [10,200] pass
# on broken code and are kept as guards against a different regression; if
# you trim this list, keep the three above or the file stops detecting the
# bug it exists for. Re-run the mutation after any change here.
#
# [20,400] USED TO FAIL on that mutant too, and no longer does -- worth
# knowing why, because it looks like lost coverage and is not. The ramp
# advanced its schedule with `t += _RAMP_TICK_S`, and 15 additions of 0.03
# reach 0.44999999999999996, just under the 0.45 s this ramp lasts. That
# bought a 16th, near-empty tick whose steps the mutant credited, putting
# the overshoot at 3 against a tolerance of 2. _ramp_tick_plan now splits
# the ramp into n EQUAL ticks (2026-08-31, adaptive-tick change), the
# phantom tick is gone, and the same mutant lands on 2 -- detected by the
# three cases above instead of four. The unmutated code emits exactly 20,
# 20, 100, 40 and 10 steps: zero overshoot on every case in this file.
# The split itself is pinned in test_ramp_tick_budget.py.
@pytest.mark.parametrize("target,f_from", [
    (20, 400),    # 0.1 mm on LIFT at 200 steps/mm — the reported failure
    (20, 800),    # load-bearing
    (40, 400),
    (100, 400),
    (10, 200),
])
def test_ramp_does_not_run_past_a_short_target(target, f_from):
    """0.1 mm on LIFT is 20 steps at 200 steps/mm. Overshoot must stay
    near one step, not the four a fixed 10 ms poll emitted at speed."""
    got = _run_ramp(target, f_from=f_from)
    overshoot = got - target
    assert overshoot >= 0, "ramp credited fewer steps than it aborted on"
    assert overshoot <= 2, (
        f"target {target} steps -> emitted {got} (+{overshoot}). "
        f"A fixed sub-sleep overshoots by f_cur x slice; the poll must "
        f"shrink as the axis closes in."
    )


def test_overshoot_does_not_grow_with_speed():
    """The old failure scaled with frequency -- faster ramp, more steps
    past the target. The adaptive slice removes that coupling, so a
    higher ceiling must not cost more overshoot."""
    slow = _run_ramp(20, f_to=800)
    fast = _run_ramp(20, f_to=6000)
    assert fast - 20 <= 2, f"fast ramp overshot by {fast - 20} steps"
    assert (fast - 20) <= (slow - 20) + 1, (
        f"overshoot grew with speed: {slow - 20} -> {fast - 20} steps"
    )


def test_ramp_without_remaining_cb_still_runs():
    # Note: this file pins the LANDING, but reaches it through remaining_cb
    # specifically. A different mechanism achieving the same accuracy would
    # fail these tests while being correct -- if you replace the approach,
    # rewrite the assertions around the observable (steps emitted vs
    # commanded), not around this parameter.
    """Callers with no step target (a plain speed change) pass no
    remaining_cb and must keep working."""
    be = _RampOnlyBackend()

    async def go():
        return await be._ramp(200, 1000, 8000.0, "linear")

    steps = asyncio.run(go())
    assert steps >= 0
    assert be.hz_writes, "ramp never wrote a frequency"
    assert be.hz_writes[-1] == 1000, "ramp did not reach its target frequency"
