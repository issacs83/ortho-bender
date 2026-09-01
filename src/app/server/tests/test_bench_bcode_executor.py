"""
test_bench_bcode_executor.py — 벤딩 시퀀스가 벤치 모터를 실제로 움직인다.

execute_bcode 는 지금까지 M7 IPC 로만 갔고, 벤치의 M7 은 mock 이라 벤딩
시퀀스는 진행률 시뮬레이션일 뿐 모터가 한 스텝도 돌지 않았다. 이 실행기는
시퀀스를 서버 내부 루프로 풀어 move_to(절대 스텝 그리드)로 실행한다 —
스텝마다 FEED 이송 -> (ROTATE 미장착: beta 생략) -> BEND 굽힘/복귀.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import asyncio

import pytest

from server.services.motor_service import MotorService
from server.services.motor_backend import MockMotorBackend

FEED_AXIS, BEND_AXIS = 0, 1
FEED_CS, BEND_CS = 2, 1
SPU_FEED, SPU_BEND = 127.324, 23.0167


class _Bench(MockMotorBackend):
    """프로덕션 pulse_step 시그니처를 받고 지령 스텝을 그대로 적산하는 벤치."""
    async def pulse_step(self, axis, count, freq_hz, direction, profile=None):
        self.positions[axis] = self.positions.get(axis, 0) + count * direction


class _SlowBench(_Bench):
    """이동마다 이벤트를 기다리는 벤치 — 시퀀스 중간 개입 테스트용."""
    def __init__(self):
        super().__init__()
        self.gate = asyncio.Event()
        self.gate.set()
        self.moves = 0

    async def pulse_step(self, axis, count, freq_hz, direction, profile=None):
        await self.gate.wait()
        self.moves += 1
        await super().pulse_step(axis, count, freq_hz, direction, profile)


class _Cal:
    def steps_per_unit(self, axis):
        return {FEED_AXIS: SPU_FEED, BEND_AXIS: SPU_BEND}.get(int(axis), 200.0)
    def distance_limit(self, axis): return 360.0
    def speed_limit(self, axis): return 8000.0 / self.steps_per_unit(axis)
    def update(self, axis, v): pass


def _svc(bench=None):
    s = MotorService(ipc=None, spidev_backend=bench or _Bench())
    s.set_calibration(_Cal())
    return s


async def test_sequence_moves_feed_and_returns_bend():
    svc = _svc()
    b = svc._spi_backend
    steps = [(5.0, 0.0, 30.0), (3.0, 0.0, 45.0), (2.0, 0.0, 0.0)]
    await svc.execute_bcode(steps, material_id=0, wire_diameter_mm=0.5)
    await svc._bcode_task

    # FEED: 총 10 mm 가 절대 그리드로 나갔다 (±1 step)
    feed_units = b.positions[FEED_CS] / SPU_FEED
    assert feed_units == pytest.approx(10.0, abs=1.5 / SPU_FEED)
    # BEND: 굽혔다가 시작 각도로 복귀 (±1 step)
    assert abs(b.positions[BEND_CS]) <= 1
    # 진행 상태 완결
    assert svc._bcode == {"current": 3, "total": 3,
                          "error": None, "aborted": False}


async def test_beta_skipped_without_rotate_axis():
    """beta≠0 스텝은 ROTATE 미장착 경고 후 생략 — 예외 없이 완주한다."""
    svc = _svc()
    await svc.execute_bcode([(2.0, 15.0, 20.0)], 0, 0.5)
    await svc._bcode_task
    assert svc._bcode["error"] is None
    assert svc._bcode["current"] == 1


async def test_stop_aborts_remaining_steps():
    bench = _SlowBench()
    svc = _svc(bench)
    bench.gate.clear()                      # 첫 이동을 게이트에 세워둔다
    await svc.execute_bcode([(2.0, 0.0, 10.0)] * 5, 0, 0.5)
    await asyncio.sleep(0.02)
    await svc.stop()                        # generation 증가 + 현재 모션 취소
    bench.gate.set()
    await svc._bcode_task
    assert svc._bcode["aborted"] is True
    assert svc._bcode["current"] < 5

async def test_estop_records_error():
    svc = _svc()
    svc._bench_estop_active = True          # move_to 가 게이트에서 거부된다
    await svc.execute_bcode([(2.0, 0.0, 10.0)], 0, 0.5)
    await svc._bcode_task
    assert svc._bcode["error"], "E-STOP 이 error 로 기록되지 않았다"


async def test_status_reports_running_and_progress():
    bench = _SlowBench()
    svc = _svc(bench)
    bench.gate.clear()
    await svc.execute_bcode([(2.0, 0.0, 0.0)] * 2, 0, 0.5)
    await asyncio.sleep(0.02)
    st = await svc.get_status()
    assert int(st.state) == 2               # RUNNING — /api/bending 폴링 규약
    assert st.total_steps == 2
    bench.gate.set()
    await svc._bcode_task
    st = await svc.get_status()
    assert int(st.state) == 0 and st.current_step == 2


async def test_double_execute_rejected():
    bench = _SlowBench()
    svc = _svc(bench)
    bench.gate.clear()
    await svc.execute_bcode([(1.0, 0.0, 0.0)], 0, 0.5)
    with pytest.raises(RuntimeError):
        await svc.execute_bcode([(1.0, 0.0, 0.0)], 0, 0.5)
    bench.gate.set()
    await svc._bcode_task
