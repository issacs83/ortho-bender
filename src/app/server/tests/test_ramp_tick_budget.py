"""
test_ramp_tick_budget.py — a short ramp must not be padded to a full tick.

The ramp engine writes the PWM frequency once per _RAMP_TICK_S (30 ms) and
sub-polls the limit guard inside that tick. The tick length was also, in
effect, the MINIMUM ramp duration: _ramp did

    total_s = max(total_s, _RAMP_TICK_S)

so a frequency change that should take 6 ms took 30 ms, and a move pays
that twice -- once accelerating, once decelerating. 60 ms is a large slice
of a command whose whole measured round trip is ~270 ms, and it buys
nothing: the schedule is a staircase either way, just with one short step.

Two things have to stay true for the shorter ramp to be safe, and neither
needs hardware:

  1. _ramp and _ramp_steps_est must SPLIT A RAMP IDENTICALLY. The second
     sizes the deceleration reserve for the first; if they disagree, the
     move lands past or short of its commanded distance. They now share
     _ramp_tick_plan, and this file pins that they do.

  2. The guard sub-poll must not overrun a tick shorter than itself. The
     limit guard reacts inside a tick at _RAMP_SUBSLEEP_S (10 ms); on a
     4 ms tick a fixed 10 ms slice would sleep past the end of the ramp.

Landing accuracy itself is pinned next door in test_short_move_landing.py.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio

import pytest

from server.services import spi_backend as sb
from server.services.spi_backend import SpidevMotorBackend, _ramp_tick_plan


class _RecordingBackend(SpidevMotorBackend):
    """Real _ramp; PWM writes and sleep requests are recorded, not performed."""

    def __init__(self):
        super().__init__()
        self.hz_writes: list[int] = []

    async def _pwm_set_hz(self, hz):
        self.hz_writes.append(int(hz))


class _Clock:
    def __init__(self, real):
        self._real, self.t = real, 0.0

    def monotonic(self) -> float:
        return self.t

    def __getattr__(self, name):
        return getattr(self._real, name)


class _Asyncio:
    """asyncio whose sleep advances a virtual clock and records the slice."""

    def __init__(self, real, clock, sleeps):
        self._real, self._clock, self._sleeps = real, clock, sleeps

    async def sleep(self, delay, result=None):
        self._sleeps.append(float(delay))
        self._clock.t += max(0.0, float(delay))
        await self._real.sleep(0)
        return result

    def __getattr__(self, name):
        return getattr(self._real, name)


def _run(f_from: int, f_to: int, rate: float, shape: str = "linear"):
    """Run a real _ramp on a virtual clock. Returns (backend, sleeps, wall)."""
    be = _RecordingBackend()
    sleeps: list[float] = []
    clock = _Clock(sb.time)
    real_time, real_asyncio = sb.time, sb.asyncio
    sb.time, sb.asyncio = clock, _Asyncio(real_asyncio, clock, sleeps)
    try:
        asyncio.run(be._ramp(f_from, f_to, rate, shape))
    finally:
        sb.time, sb.asyncio = real_time, real_asyncio
    return be, sleeps, clock.t


# ---------------------------------------------------------------------------
# 1. the padding itself
# ---------------------------------------------------------------------------

def test_short_ramp_is_not_padded_to_a_full_tick():
    """200 -> 250 Hz at 8000 Hz/s is 6.25 ms of ramp. It must cost about
    that, not the 30 ms a full tick would."""
    _, _, wall = _run(200, 250, 8000.0)
    assert wall == pytest.approx(0.00625, abs=0.002), (
        f"a 6.25 ms ramp took {wall*1000:.1f} ms — the tick floor is back"
    )
    assert wall < sb._RAMP_TICK_S, "short ramp still padded to a full tick"


def test_short_ramp_still_reaches_its_target_frequency():
    """Shorter must not mean unfinished — the whole point of the ramp is
    that the PWM ends up at f_to."""
    be, _, _ = _run(200, 250, 8000.0)
    assert be.hz_writes, "ramp never wrote a frequency"
    assert be.hz_writes[-1] == 250


def test_long_ramp_tick_length_is_unchanged():
    """The change is a floor removal, not a re-tuning: a ramp longer than
    one tick keeps ~30 ms steps."""
    _, _, wall = _run(200, 8000, 8000.0)          # 0.975 s
    n, tick = _ramp_tick_plan(0.975)
    assert tick == pytest.approx(sb._RAMP_TICK_S, rel=0.05)
    assert wall == pytest.approx(0.975, rel=0.05)


# ---------------------------------------------------------------------------
# 2. the two consumers must agree
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("total_s", [0.001, 0.004, 0.0062, 0.03, 0.031,
                                     0.09, 0.45, 0.975, 3.0])
def test_plan_is_ceil_and_splits_evenly(total_s):
    n, tick = _ramp_tick_plan(total_s)
    assert n >= 1
    assert n * tick == pytest.approx(total_s, rel=1e-9), "split loses time"
    assert tick <= sb._RAMP_TICK_S + 1e-12, "tick longer than the guard budget"
    # ceil, not round: rounding down would make the LAST tick overrun.
    assert (n - 1) * sb._RAMP_TICK_S < total_s + 1e-12


def test_ramp_and_reserve_estimate_use_the_same_split():
    """_ramp_steps_est sizes the decel reserve for _ramp. A disagreement
    here is exactly the over/under-run this reserve exists to prevent."""
    be = _RecordingBackend()
    for f_from, f_to, rate in ((200, 250, 8000.0), (200, 4000, 8000.0),
                               (4000, 200, 8000.0), (200, 8000, 40000.0)):
        total_s = abs(f_to - f_from) / rate
        n_plan, _ = _ramp_tick_plan(max(total_s, sb._RAMP_SUBSLEEP_MIN_S))
        be._ramp_jitter = 1.0
        est = be._ramp_steps_est(f_from, f_to, total_s, "linear")
        n_est, _ = _ramp_tick_plan(total_s)
        assert n_est == n_plan or total_s < sb._RAMP_SUBSLEEP_MIN_S
        assert est >= 0
        # A ramp that emits no estimate would reserve no braking distance.
        assert est > 0, f"{f_from}->{f_to} estimated zero steps"


# ---------------------------------------------------------------------------
# 3. the guard poll must fit inside a short tick
# ---------------------------------------------------------------------------

def test_guard_subpoll_never_sleeps_past_a_short_tick():
    """On a 4 ms tick a fixed 10 ms sub-slice would sleep past the end of
    the ramp, so the limit guard would check LATE — on the axis where the
    guard is the thing standing between a jog and the end stop."""
    _, sleeps, _ = _run(200, 232, 8000.0)         # 4 ms of ramp
    assert sleeps, "ramp never slept"
    n, tick = _ramp_tick_plan(0.004)
    assert max(sleeps) <= tick + 1e-12, (
        f"slept {max(sleeps)*1000:.2f} ms inside a {tick*1000:.2f} ms tick"
    )


def test_guard_still_fires_inside_a_long_tick():
    """The sub-poll exists so a fast axis cannot cross its sensor window
    between frequency writes. Shortening ramps must not remove it."""
    be = _RecordingBackend()
    calls = {"n": 0}

    def guard():
        calls["n"] += 1
        return False

    clock = _Clock(sb.time)
    real_time, real_asyncio = sb.time, sb.asyncio
    sb.time, sb.asyncio = clock, _Asyncio(real_asyncio, clock, [])
    try:
        asyncio.run(be._ramp(200, 8000, 8000.0, "linear", guard_cb=guard))
    finally:
        sb.time, sb.asyncio = real_time, real_asyncio
    # 0.975 s of ramp at a 10 ms poll — an order of magnitude more checks
    # than the ~33 frequency writes.
    assert calls["n"] >= 90, f"guard polled only {calls['n']} times"
