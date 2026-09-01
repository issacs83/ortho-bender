"""
test_per_axis_microstep.py — DRVCTRL(MRES)이 축별로 갈라진다.

FEED 는 분해능이 속도보다 귀해 1/32(MRES=3)로 올라갔고, BEND/LIFT 는
1/16(모듈 기본값)을 유지한다. 초기화 시퀀스가 축마다 올바른 DRVCTRL 을
쓰는지, 그리고 DEDGE/INTPOL 비트가 보존되는지를 고정한다 — DEDGE 를
지우면 실효 스텝 레이트가 조용히 반토막 난다(과거 사고).

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest

from server.services.spi_backend import SpidevMotorBackend
from server.services.tmc260c_driver import DRVCTRL_DEFAULT

FEED_CS, BEND_CS, LIFT_CS = 2, 1, 0


class _SpiRecorder(SpidevMotorBackend):
    """spi 전송을 기록만 하는 백엔드 — 풀 초기화가 실제로 쓰는 값을 본다."""

    def __init__(self):
        super().__init__()
        self.frames: dict[int, list[int]] = {0: [], 1: [], 2: []}

    async def spi_transfer(self, cs, data):
        word = (data[0] << 16) | (data[1] << 8) | data[2]
        self.frames[cs].append(word)
        return b"\x12\x34\x56"          # 유효 응답 → 조기 종료 경로

    async def spi_transfer_batch(self, cs, frames):
        return [await self.spi_transfer(cs, f) for f in frames]

    def _save_state_soon(self):
        pass


def _drvctrl_writes(backend, cs):
    # DRVCTRL 데이터그램은 상위 3비트(tag)가 0 — 20비트 값 그대로다
    return [w for w in backend.frames[cs] if (w >> 17) == 0]


async def test_feed_gets_1_32_others_keep_default():
    b = _SpiRecorder()
    b.mres_map = {FEED_CS: 3}           # main.py 와 같은 배선
    for cs in (LIFT_CS, BEND_CS, FEED_CS):
        await b._init_chip(cs)

    feed = _drvctrl_writes(b, FEED_CS)
    assert feed and all(w == ((DRVCTRL_DEFAULT & ~0x0F) | 3) for w in feed)
    for cs in (LIFT_CS, BEND_CS):
        ws = _drvctrl_writes(b, cs)
        assert ws and all(w == DRVCTRL_DEFAULT for w in ws)


async def test_dedge_intpol_preserved():
    b = _SpiRecorder()
    b.mres_map = {FEED_CS: 3}
    await b._init_chip(FEED_CS)
    for w in _drvctrl_writes(b, FEED_CS):
        assert (w >> 8) & 1, "DEDGE 가 지워졌다 — 실효 스텝 레이트 반토막"
        assert (w >> 9) & 1, "INTPOL 이 지워졌다"


def test_calibration_default_matches_mres():
    """MRES=3(1/32)과 캘리브레이션 기본값은 짝이다: 3200 x 2.5 / (pi x 20)."""
    import math
    from server.services.calibration_service import DEFAULT_STEPS_PER_UNIT
    expect = 3200 * 2.5 / (math.pi * 20)
    assert DEFAULT_STEPS_PER_UNIT[0] == pytest.approx(expect, abs=0.001)
    assert DEFAULT_STEPS_PER_UNIT[0] == 127.324
