"""
test_limit_immediate_stop.py — 리밋 가드 발동 = 감속 없이 즉시 정지.

이전에는 가드가 발동해도 '깨끗한 종료' 경로로 취급되어 바닥 주파수까지
감속 램프(최악 1 s)를 탔다 — 그동안 축은 리밋 창을 지나 기구 한계 쪽으로
계속 간다. 리밋을 밟은 순간에는 위치 충실도보다 진행을 멈추는 것이
우선이므로, 가드 발동 시 감속을 건너뛰고 STEP 을 바로 끊는다.

검증 방법: PWM 쓰기를 기록하는 스텁 백엔드로 순항 중 리밋을 밟게 하고,
그 이후 감속 계단(내려가는 주파수 쓰기)이 하나도 없음을 고정한다.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest

from server.services.spi_backend import SpidevMotorBackend

LIFT_CS = 0      # 가드 대상 축 (main.py: guard_axes = {0})


class _GuardedBench(SpidevMotorBackend):
    """PWM/SPI 스텁 + 리밋 스위치 시뮬레이션.

    limit_active() 가 처음 `trip_after` 회는 False(창 밖 — 가드 장전),
    그 뒤로는 True(밟음)를 돌려준다.
    """

    def __init__(self, trip_after: int = 8):
        super().__init__()
        self.hz_writes: list[int] = []
        self._limit_polls = 0
        self._trip_after = trip_after

    async def _pwm_ensure_exported(self):
        pass

    async def _pwm_set_hz(self, hz):
        self.hz_writes.append(int(hz))
        self._pwm_last_period_ns = int(1e9 / hz)   # brake_now/감속 시작점 계산용
        self._pwm_active = True

    async def _pwm_disable(self, kill=False):
        if kill:
            self._pwm_killed = True
        self._pwm_active = False

    async def _init_chip(self, cs):
        self._initialized[cs] = True
        self._chip_active[cs] = True
        return 0

    async def _silence_chip(self, cs):
        self._chip_active[cs] = False

    async def _hold_chip(self, cs):
        self._chip_active[cs] = True

    async def _read_status(self, cs):
        return 0                       # 폴트/스톨 없음

    def _set_dir(self, axis, direction):
        pass

    def _save_state_soon(self):
        pass

    def limit_active(self, cs):
        self._limit_polls += 1
        return self._limit_polls > self._trip_after


async def test_guard_hit_stops_without_decel_ramp():
    """리밋을 밟은 뒤에는 주파수 쓰기가 내려가는 계단(감속 램프)이 없어야
    한다 — 가드 발동 즉시 STEP 차단."""
    b = _GuardedBench(trip_after=8)
    assert b.limit_guard and LIFT_CS in b.guard_axes
    await b.pulse_step(LIFT_CS, 4000, 2000, +1)     # 정밀 경로(≤16) 밖의 순항 이동
    assert b.hz_writes, "PWM 이 켜진 적이 없다 — 시나리오 자체가 깨짐"
    assert b.hz_writes == sorted(b.hz_writes), (
        f"가드 발동 후 감속 계단이 나갔다: {b.hz_writes}")
    assert not b._pwm_active, "가드 발동 후에도 STEP 이 살아 있다"


async def test_guard_disabled_keeps_decel():
    """가드를 끄면(limit_stop=false) 자연 종료 감속은 그대로다 —
    즉시 정지는 리밋 발동에만 적용되는 예외임을 고정한다."""
    b = _GuardedBench(trip_after=10**9)             # 리밋이 절대 안 밟힘
    b.limit_guard = False
    await b.pulse_step(LIFT_CS, 400, 2000, +1)
    # 자연 종료: 감속 램프가 바닥까지 내려간 쓰기를 남긴다
    assert any(b2 < a for a, b2 in zip(b.hz_writes, b.hz_writes[1:])), (
        "자연 종료 감속 램프가 사라졌다")
