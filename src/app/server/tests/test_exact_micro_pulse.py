"""
test_exact_micro_pulse.py — 초소형 이동은 정확히 지령한 스텝 수만큼 나간다.

램프 기계는 시간 적분으로 스텝을 계수해서 초소형 이동에서 ±1 스텝을
흘린다. 그 1 스텝이 카운터를 목표보다 앞세우면 다음 미세 지령의 갭이
1 스텝 밑으로 떨어져 통째로 무시된다 — 보드 실측(2026-09-01)에서 20회
반복 중 1~2회가 그렇게 빠졌다. "지령하면 반드시 움직인다"를 보장하려면
초소형 이동의 카운터 전진이 정확히 count 여야 한다. pulse_step 의
정밀 경로(_EXACT_PULSE_MAX_STEPS 이하)가 그 일을 하고, 여기서 고정한다.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest

from server.services import spi_backend as sb
from server.services.spi_backend import SpidevMotorBackend

FEED_CS = 2      # 리밋 스위치 없는 축 — limit_active() 가 None 을 돌려준다


class _PwmStubBackend(SpidevMotorBackend):
    """SPI/GPIO/PWM 하드웨어 접근을 전부 기록용 스텁으로 바꾼 실제 백엔드.

    pulse_step 의 정밀 경로가 검증 대상이므로 pulse_step 자체는 프로덕션
    코드 그대로 돈다 — 여기서 재구현하면 실제 경로가 틀려도 통과해 버린다.
    """

    def __init__(self):
        super().__init__()
        self.hz_writes: list[int] = []

    async def _pwm_ensure_exported(self):
        pass

    async def _pwm_set_hz(self, hz):
        self.hz_writes.append(int(hz))
        self._pwm_active = True

    async def _pwm_disable(self, kill=False):
        if kill:
            self._pwm_killed = True
        self._pwm_active = False

    async def _init_chip(self, cs):
        self._initialized[cs] = True
        self._chip_active[cs] = True
        return 0                      # 폴트 없음

    async def _silence_chip(self, cs):
        self._chip_active[cs] = False

    async def _hold_chip(self, cs):
        self._chip_active[cs] = True

    def _set_dir(self, axis, direction):
        pass

    def _save_state_soon(self):
        pass                          # 테스트 종료 시 잔류 태스크 경고 방지


@pytest.fixture
def bench():
    return _PwmStubBackend()


@pytest.mark.parametrize("count", [1, 2, 5, 16])
async def test_micro_pulse_emits_exact_count(bench, count):
    """정밀 경로 범위의 count 는 카운터가 정확히 count 만큼 전진한다."""
    start = bench.positions[FEED_CS]
    await bench.pulse_step(FEED_CS, count, 200, +1)
    assert bench.positions[FEED_CS] - start == count


async def test_micro_pulse_exact_in_reverse(bench):
    """음의 방향도 동일하다."""
    start = bench.positions[FEED_CS]
    await bench.pulse_step(FEED_CS, 3, 200, -1)
    assert bench.positions[FEED_CS] - start == -3


async def test_micro_pulse_repeats_never_drift(bench):
    """1~2 스텝 지령 40회 연타 — 누적 오차 0 스텝이어야 한다.

    램프 경로였다면 회차마다 ±1 스텝이 새어 나와 수 스텝씩 표류한다."""
    start = bench.positions[FEED_CS]
    expect = 0
    for i in range(40):
        n = 1 + (i % 2)
        await bench.pulse_step(FEED_CS, n, 200, +1)
        expect += n
    assert bench.positions[FEED_CS] - start == expect


def test_threshold_covers_micro_traffic():
    """정밀 경로 상한 고정: 미세 이송(FEED 0.25 unit = 16 step 이하)을 덮는다.
    낮추면 미세 반복 보장이 깨지고, 크게 올리면 정상 이동이 램프를 잃는다."""
    assert sb._EXACT_PULSE_MAX_STEPS == 16
