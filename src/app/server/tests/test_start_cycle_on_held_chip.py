"""
test_start_cycle_on_held_chip.py — 통전 중이던 칩은 침묵→init 으로 시작한다.

벤치 실측(2026-09-02): 유지(hold)로 계속 통전된 칩에 새 STEP 스트림을
붙이면 기동하지 못하는 경우가 있다 — hold CS14 의 LIFT 기동 불가, 전 축
hold 에서 같은 축 방향 반전 불가. 침묵을 거친 시작은 항상 성공했으므로,
pulse_step/home 은 활성 칩을 먼저 침묵시켜 시작 조건을 단일화한다.
와이어 레벨로 고정한다: 첫 프레임들이 초퍼 off(0x80000)·전류 0(0xD3F00)
데이터그램이어야 한다.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest

from server.services.spi_backend import SpidevMotorBackend

CS = 2   # FEED — 리밋 없음


class _Rec(SpidevMotorBackend):
    def __init__(self):
        super().__init__()
        self.frames: list[int] = []

    async def spi_transfer(self, cs, data):
        self.frames.append((data[0] << 16) | (data[1] << 8) | data[2])
        return b"\x00\x00\x01"   # 폴트 비트 없는 유효 응답

    async def spi_transfer_batch(self, cs, frames):
        return [await self.spi_transfer(cs, f) for f in frames]

    async def _pwm_ensure_exported(self): pass
    async def _pwm_set_hz(self, hz):
        self._pwm_last_period_ns = int(1e9 / hz); self._pwm_active = True
    async def _pwm_disable(self, kill=False): self._pwm_active = False
    def _set_dir(self, a, d): pass
    def _save_state_soon(self): pass


CHOP_OFF = 0x80000            # encode(0x04, 0x80000) — TOFF=0
SGCS_OFF = 0xD3F00            # encode(0x06, ...) — CS=0


async def test_active_chip_gets_silenced_before_start():
    b = _Rec()
    b._initialized[CS] = True
    b._chip_active[CS] = True          # 유지로 통전 중이던 칩
    await b.pulse_step(CS, 4, 200, +1)
    assert b.frames[:2] == [CHOP_OFF, SGCS_OFF], (
        f"침묵 사이클이 먼저 나가지 않았다: {[hex(f) for f in b.frames[:4]]}")


async def test_idle_chip_starts_without_extra_cycle():
    b = _Rec()
    b._initialized[CS] = True
    b._chip_active[CS] = False         # 이미 침묵 상태
    await b.pulse_step(CS, 4, 200, +1)
    assert CHOP_OFF not in b.frames[:2], "불필요한 이중 침묵"
