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


def _run_ramp(target_steps: int, f_from=200, f_to=4000, rate=8000.0):
    """Accelerate toward f_to but abort once target_steps are emitted,
    exactly as pulse_step does. Returns steps actually credited."""
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

    asyncio.run(go())
    return travelled()


# ---------------------------------------------------------------------------
# The regression itself
# ---------------------------------------------------------------------------

# f_from matters as much as the target. The bench move that failed had
# already reached roughly 400 Hz when it passed its 20-step target, which
# is where a fixed 10 ms slice costs four steps; starting from the 200 Hz
# floor the same target only costs two and the bug hides.
# LOAD-BEARING: only [20,800] and [40,400] actually fail when the adaptive
# slice is reverted to a fixed 10 ms. The rest pass on broken code too --
# at low f_cur a fixed slice emits fewer steps than the tolerance, which is
# the same blind spot the comment above describes. They are kept as guards
# against a different regression, but if you trim this list, keep those two
# or the file stops detecting the bug it exists for.
@pytest.mark.parametrize("target,f_from", [
    (20, 400),    # 0.1 mm on LIFT at 200 steps/mm — the reported failure
    (20, 800),    # load-bearing
    (40, 400),    # load-bearing
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
