"""
test_hold_persistence.py — 정지토크(hold) 설정은 재시작을 살아남는다.

UI 로 켠 정지토크가 상태파일에 저장되지 않아, 서비스 재시작마다 config
기본값으로 되돌아가고 기동 재유지(main.py)도 config 만 봤다 — "축별 EN
분리를 해뒀는데 회귀했다"(2026-09-02 보고)로 나타난 원인. 스냅샷 왕복과
set_protection 의 영속 예약을 고정한다.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import json

import pytest

import server.services.spi_backend as sb
from server.services.spi_backend import SpidevMotorBackend
from server.services.motor_service import MotorService
from server.services.motor_backend import MockMotorBackend


def test_hold_axes_snapshot_roundtrip(tmp_path):
    b = SpidevMotorBackend()
    b.hold_axes = {0, 2}
    snap = b._state_snapshot()
    assert snap["hold_axes"] == [0, 2]

    fresh = SpidevMotorBackend()
    f = tmp_path / "state.json"
    f.write_text(json.dumps(snap))
    old = sb._STATE_FILE
    sb._STATE_FILE = str(f)
    try:
        fresh._load_state()
    finally:
        sb._STATE_FILE = old
    assert fresh.hold_axes == {0, 2}
    assert getattr(fresh, "_hold_loaded", False) is True


class _Bench(MockMotorBackend):
    def __init__(self):
        super().__init__()
        self.hold_axes = set()
        self.hold_cs_map = {}
        self.run_cs_map = {}
        self.saves = 0
        self.held = []

    def _save_state_soon(self):
        self.saves += 1

    async def _hold_chip(self, cs):
        self.held.append(cs)

    async def _silence_chip(self, cs):
        pass

    def run_cs_for(self, cs): return 14
    def effective_cs(self, cs=None): return 14
    def hold_cs_for(self, cs): return 8


async def test_set_protection_persists_and_applies():
    svc = MotorService(ipc=None, spidev_backend=_Bench())
    b = svc._spi_backend
    await svc.set_protection(axes={0: {"hold_enabled": True}})   # FEED
    assert b.hold_axes == {2}                                    # cs 로 변환
    assert b.saves >= 1, "정지토크 변경이 영속화되지 않았다"
    assert getattr(b, "_hold_loaded", False) is True
    assert 2 in b.held, "유휴 즉시 반영(_hold_chip)이 안 불렸다"
