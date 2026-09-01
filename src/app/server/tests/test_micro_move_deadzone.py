"""
test_micro_move_deadzone.py — 2 스텝 미만의 절대 이동도 회차마다 움직여야 한다.

move_to 의 착지 허용오차(모터 2 스텝)는 큰 이동의 램프 잔차를 위한 것인데,
그 판정이 2 스텝 미만의 '지령 자체'까지 삼켰다: 63.662 steps/unit 의 FEED
에서 0.03 unit(1.9 step) 지령을 절대 그리드로 반복하면 절반이, 0.018 unit
(1.15 step)이면 13/20 이 통째로 무동작이었다 (2026-09-01 obtest feed.step
보드 실측). 총량은 그리드가 지켜 주지만 회차 단위 이동이 0 과 2배 사이를
오간다 — 미세 이송이 목표인 기계에서 가장 아픈 지점이다.

수정: 갭이 허용오차 안이라도 온전한 스텝이 1개 이상 남아 있으면 그 정수
스텝만큼 내보낸다. 서브스텝 잔차(<1 step)는 물리적으로 낼 수 없으므로
그대로 남는다.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest

from server.services.motor_service import MotorService
from server.services.motor_backend import MockMotorBackend

FEED_AXIS = 0
FEED_CS = 2
SPU = 63.662             # #48 이후의 FEED 기본 캘리브레이션


class _Bench(MockMotorBackend):
    """프로덕션 pulse_step 시그니처(profile=)를 받는 모의 벤치 —
    스텝 카운터는 지령 그대로 적산된다."""
    async def pulse_step(self, axis, count, freq_hz, direction, profile=None):
        self.positions[axis] = self.positions.get(axis, 0) + count * direction


class _Cal:
    """스텝/단위 변환만 답하는 캘리브레이션 스텁."""
    def steps_per_unit(self, axis): return SPU if axis == FEED_AXIS else 200.0
    def distance_limit(self, axis): return 200.0
    def speed_limit(self, axis): return 125.7


@pytest.fixture
def svc():
    s = MotorService(ipc=None, spidev_backend=_Bench())
    s.set_calibration(_Cal())
    return s


def _pos(svc) -> float:
    return svc._spi_backend.positions.get(FEED_CS, 0) / SPU


@pytest.mark.parametrize("step_units, label", [
    (0.03, "1.9 step — 옛 데드존 한복판"),
    (0.018, "1.15 step — obtest 0.03 mm 재현"),
])
async def test_sub_tolerance_steps_move_every_time(svc, step_units, label):
    """온전한 스텝이 남아 있는 회차는 반드시 움직인다
    (예전에는 절반 이상이 무동작)."""
    start = _pos(svc)
    zero_moves = 0
    for i in range(1, 21):
        target = start + step_units * i
        before = _pos(svc)
        await svc.move_to(FEED_AXIS, target, speed=5)
        after = _pos(svc)
        if abs(target - before) * SPU >= 1.0 and after == before:
            zero_moves += 1
    assert zero_moves == 0, (
        f"{label}: 온전한 스텝이 남아 있는데도 {zero_moves}/20 회 무동작")


async def test_total_lands_within_one_step(svc):
    """20회 누적 후 총량은 1 스텝 이내로 착지한다 (그리드 보존)."""
    step_units = 0.03
    start = _pos(svc)
    for i in range(1, 21):
        await svc.move_to(FEED_AXIS, start + step_units * i, speed=5)
    err_steps = abs((_pos(svc) - start) - step_units * 20) * SPU
    assert err_steps <= 1.0, f"총량 오차 {err_steps:.2f} step (> 1 step)"


async def test_true_substep_command_never_overshoots(svc):
    """1 스텝 미만의 잔차는 낼 수 없다 — 대신 잔차가 쌓여 스텝이 되면
    움직이고, 카운터가 목표를 1 스텝 넘게 앞서는 일은 없어야 한다
    (_bench_pulse 의 max(1,...) 과잉 방출 방지 고정)."""
    step_units = 0.008          # 0.51 step
    start = _pos(svc)
    moved_any = False
    for i in range(1, 11):
        target = start + step_units * i
        await svc.move_to(FEED_AXIS, target, speed=5)
        pos = _pos(svc)
        if pos != start:
            moved_any = True
        assert (pos - target) * SPU <= 1.0, "목표를 1 스텝 넘게 과잉 방출"
    assert moved_any, "잔차가 5 스텝 누적되는 동안 한 번도 못 움직였다"


async def test_normal_move_unaffected(svc):
    """정상 크기 이동(수백 스텝)은 이전과 동일하게 목표 ±1 스텝에 착지."""
    await svc.move_to(FEED_AXIS, 5.0, speed=50)
    assert abs(_pos(svc) - 5.0) * SPU <= 1.0


@pytest.mark.parametrize("step_units", [0.03, 0.018])
async def test_two_hundred_reps_all_move(svc, step_units):
    """20회 x 10세트 = 200회 절대 그리드 반복 — 온전한 스텝이 남는 지령은
    한 번도 빠짐없이 움직여야 한다 (사용자 요구 사양)."""
    start = _pos(svc)
    pos = start
    zero_moves = 0
    for i in range(1, 201):
        target = start + step_units * i
        before = pos
        await svc.move_to(FEED_AXIS, target, speed=5)
        pos = _pos(svc)
        if abs(target - before) * SPU >= 1.0 and pos == before:
            zero_moves += 1
    assert zero_moves == 0, f"{zero_moves}/200 회 무동작"
    err_steps = abs((pos - start) - step_units * 200) * SPU
    assert err_steps <= 1.0, f"200회 누적 오차 {err_steps:.2f} step"
