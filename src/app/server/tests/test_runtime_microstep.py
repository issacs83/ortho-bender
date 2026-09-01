"""
test_runtime_microstep.py — 분주비 런타임 변경은 세 가지가 한 몸으로 움직인다.

분주비(DRVCTRL.MRES)를 바꾸면 (1) 다음 풀 초기화가 새 값을 칩에 쓰고,
(2) 위치 카운터가 같은 배율로 스케일되어 물리 위치가 보존되며,
(3) steps_per_unit 캘리브레이션이 같은 배율로 따라간다. 하나라도 빠지면
표시 위치·homed datum·속도 상한이 조용히 어긋난다 — 여기서 고정한다.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest

from server.services.motor_service import MotorService
from server.services.motor_backend import MockMotorBackend
from server.services.spi_backend import SpidevMotorBackend
from server.services.tmc260c_driver import DRVCTRL_DEFAULT

FEED_AXIS, FEED_CS = 0, 2


class _Bench(SpidevMotorBackend):
    def __init__(self):
        super().__init__()
        self.frames: list[int] = []

    async def spi_transfer(self, cs, data):
        self.frames.append((data[0] << 16) | (data[1] << 8) | data[2])
        return b"\x12\x34\x56"

    async def spi_transfer_batch(self, cs, frames):
        return [await self.spi_transfer(cs, f) for f in frames]

    def _save_state_soon(self):
        pass


class _Cal:
    def __init__(self):
        self.spu = {0: 127.324, 1: 23.0167, 3: 200.0}
    def steps_per_unit(self, axis): return self.spu.get(int(axis), 200.0)
    def distance_limit(self, axis): return 200.0
    def speed_limit(self, axis): return 8000.0 / self.steps_per_unit(axis)
    def update(self, axis, v): self.spu[int(axis)] = float(v)


@pytest.fixture
def svc():
    b = _Bench()
    b.mres_map = {FEED_CS: 3}          # 1/32 (main.py 기본과 동일)
    s = MotorService(ipc=None, spidev_backend=b)
    s.set_calibration(_Cal())
    return s


async def test_change_scales_counter_and_calibration(svc):
    b = svc._spi_backend
    b.positions[FEED_CS] = 1000        # 물리 위치 1000/127.324 = 7.854 unit
    out = await svc.set_microstep(FEED_AXIS, 64)
    assert b.positions[FEED_CS] == 2000, "카운터가 배율만큼 안 커졌다"
    assert svc._calibration.steps_per_unit(FEED_AXIS) == pytest.approx(254.648)
    assert out["0"]["microsteps"] == 64
    assert out["0"]["speed_limit"] == pytest.approx(8000 / 254.648)
    # 물리 위치 불변: 새 단위로 환산해도 같은 자리
    assert b.positions[FEED_CS] / 254.648 == pytest.approx(1000 / 127.324)


async def test_next_init_writes_new_drvctrl(svc):
    b = svc._spi_backend
    await b._init_chip(FEED_CS)        # 1/32 로 한 번 초기화
    await svc.set_microstep(FEED_AXIS, 64)
    assert b._initialized[FEED_CS] is False, "재초기화 예약이 안 됐다"
    b.frames.clear()
    await b._init_chip(FEED_CS)
    drvctrl = [w for w in b.frames if (w >> 17) == 0]
    want = (DRVCTRL_DEFAULT & ~0x0F) | 2          # MRES=2 → 1/64
    assert drvctrl and all(w == want for w in drvctrl)


async def test_same_value_is_noop(svc):
    b = svc._spi_backend
    b.positions[FEED_CS] = 777
    await svc.set_microstep(FEED_AXIS, 32)
    assert b.positions[FEED_CS] == 777
    assert svc._calibration.steps_per_unit(FEED_AXIS) == pytest.approx(127.324)


async def test_invalid_value_rejected(svc):
    with pytest.raises(ValueError):
        await svc.set_microstep(FEED_AXIS, 24)


async def test_persists_in_state_snapshot(svc):
    await svc.set_microstep(FEED_AXIS, 64)
    snap = svc._spi_backend._state_snapshot()
    assert snap["mres"] == {"2": 2}

    fresh = _Bench()
    import json, tempfile, os
    import server.services.spi_backend as sb
    with tempfile.TemporaryDirectory() as td:
        f = os.path.join(td, "state.json")
        json.dump(snap, open(f, "w"))
        old = sb._STATE_FILE
        sb._STATE_FILE = f
        try:
            fresh._load_state()
        finally:
            sb._STATE_FILE = old
    assert fresh.mres_map == {2: 2}
    assert fresh.usteps_for(2) == 64
