"""
test_uniform_step_mode.py — '완전 균일' 축은 같은 거리 지령에 매회 같은
스텝 수가 나간다.

mm 그리드와 스텝 그리드는 pi 때문에 통약 불가능하다: 0.1 unit 은 정수
스텝이 아니므로 '평균 정확'(절대 그리드, ±1 스텝 교대)과 '등간격'은 동시에
가질 수 없다. uniform 모드는 지령 거리(현재 위치 기준)를 정수 스텝으로
스냅해 등간격을 택한다 — 카운터가 항상 격자 위이므로 같은 델타는 항상
같은 반올림을 얻는다. FEED 가 기본 대상이다(main.py).

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest

from server.services.motor_service import MotorService
from server.services.motor_backend import MockMotorBackend

FEED_AXIS, FEED_CS = 0, 2
SPU = 127.324


class _Bench(MockMotorBackend):
    def __init__(self):
        super().__init__()
        self.snap_axes = {FEED_AXIS}
        self.mres_map = {FEED_CS: 3}
        self.saves = 0

    async def pulse_step(self, axis, count, freq_hz, direction, profile=None):
        self.positions[axis] = self.positions.get(axis, 0) + count * direction

    def usteps_for(self, cs):
        return 32

    def set_axis_microstep(self, cs, microsteps):
        return 1.0

    def _save_state_soon(self):
        self.saves += 1


class _Cal:
    def steps_per_unit(self, axis): return SPU if axis == FEED_AXIS else 200.0
    def distance_limit(self, axis): return 200.0
    def speed_limit(self, axis): return 8000.0 / self.steps_per_unit(axis)
    def update(self, axis, v): pass


@pytest.fixture
def svc():
    s = MotorService(ipc=None, spidev_backend=_Bench())
    s.set_calibration(_Cal())
    return s


async def test_repeated_delta_moves_identical_steps(svc):
    """'현재 위치 + 0.1' 반복 — 매회 정확히 round(0.1 x spu) = 13 step."""
    b = svc._spi_backend
    deltas = []
    for _ in range(20):
        before = b.positions[FEED_CS]
        cur = before / SPU
        await svc.move_to(FEED_AXIS, cur + 0.1, speed=5)
        deltas.append(b.positions[FEED_CS] - before)
    assert deltas == [13] * 20, f"등간격 깨짐: {deltas}"


async def test_absolute_ladder_degrades_to_grid(svc):
    """절대 좌표 래더(i x 0.1)를 보내는 클라이언트: 폭주 없이 절대
    그리드(±1 step 추종)로 퇴화한다."""
    b = svc._spi_backend
    for i in range(1, 21):
        await svc.move_to(FEED_AXIS, 0.1 * i, speed=5)
    err_steps = abs(b.positions[FEED_CS] - 0.1 * 20 * SPU)
    assert err_steps <= 1.0, f"래더 추종 이탈: {err_steps:.2f} step"


async def test_non_uniform_axis_unchanged(svc):
    """uniform 이 꺼진 축(BEND)은 기존 절대 그리드 그대로 — 목표에
    ±0.5 step 으로 착지한다 (스냅 없음)."""
    b = svc._spi_backend
    await svc.move_to(1, 10.0, speed=30)           # BEND, spu 200
    assert abs(b.positions[1] - 10.0 * 200.0) <= 1


async def test_api_toggle_and_persistence(svc):
    b = svc._spi_backend
    out = await svc.set_microstep(FEED_AXIS, uniform=False)
    assert out["0"]["uniform"] is False and FEED_AXIS not in b.snap_axes
    assert b.saves >= 1                             # 영속화 예약됨
    out = await svc.set_microstep(FEED_AXIS, uniform=True)
    assert out["0"]["uniform"] is True and FEED_AXIS in b.snap_axes


async def test_uniform_toggle_allowed_without_microsteps(svc):
    """uniform 만 바꿀 때는 microsteps 검증(모션 중 거부 등)을 타지 않는다."""
    out = await svc.set_microstep(FEED_AXIS, microsteps=None, uniform=True)
    assert out["0"]["microsteps"] == 32             # 분주비는 그대로
