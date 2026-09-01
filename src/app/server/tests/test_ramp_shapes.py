"""
test_ramp_shapes.py — linear/scurve 램프가 각자의 스케줄대로 간다.

모션 프로파일의 shape 는 지금까지 테스트가 하나도 없었다(2026-09-02 발견).
_ramp 의 두 형상을 고정한다:
  linear — 일정 기울기 계단 (사다리꼴 속도)
  scurve — smoothstep f(τ)=f0+Δf·(3τ²−2τ³): 작게→크게→작게 대칭 S,
           피크 기울기가 설정 accel 을 넘지 않고, 총 시간 ≈ 1.5×span/rate

실시간 sleep 기반이라 단정은 패턴·경계값 위주로 잡는다(스케줄러 지터에
견디는 굵은 판정). 보드 실측(2026-09-02): 두 형상 모두 +2 mm 착지 오차
-0.18 step 동일, scurve 소요 1.39 s vs linear 0.81 s.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import time

import pytest

from server.services.spi_backend import SpidevMotorBackend


class _Rec(SpidevMotorBackend):
    def __init__(self):
        super().__init__()
        self.w: list[tuple[float, int]] = []

    async def _pwm_set_hz(self, hz):
        self.w.append((time.monotonic(), int(hz)))
        self._pwm_last_period_ns = int(1e9 / hz)
        self._pwm_active = True


async def _run(shape):
    b = _Rec()
    est = await b._ramp(200, 8000, 20000.0, shape)
    hz = [h for _, h in b.w]
    ts = [t for t, _ in b.w]
    return hz, ts[-1] - ts[0], est


async def test_linear_constant_slope():
    hz, dur, _ = await _run("linear")
    assert hz[-1] == 8000
    inc = [b - a for a, b in zip(hz, hz[1:])]
    # 일정 기울기: 마지막 잔여 틱을 빼면 증가폭이 모두 같다
    assert len(set(inc[:-1])) == 1, f"계단이 일정하지 않다: {inc}"
    # 총 시간 ≈ span/rate = 0.39 s (지터 여유 ±40%)
    assert 0.23 < dur < 0.55, dur


async def test_scurve_is_symmetric_s():
    hz, dur, _ = await _run("scurve")
    assert hz[-1] == 8000
    inc = [b - a for a, b in zip(hz, hz[1:])]
    n = len(inc)
    peak = max(inc)
    # S 형: 양 끝은 작고 가운데가 크다
    assert inc[0] < peak * 0.5 and inc[-1] < peak * 0.5, inc
    assert max(inc[n // 2 - 1: n // 2 + 2]) == peak, "피크가 중앙에 있지 않다"
    # 대칭성: 앞/뒤 절반 합이 비슷하다
    assert abs(sum(inc[: n // 2]) - sum(inc[-(n // 2):])) < 0.2 * sum(inc)
    # 총 시간 ≈ 1.5 x span/rate = 0.585 s (지터 여유)
    assert 0.4 < dur < 0.8, dur


async def test_scurve_peak_slope_never_exceeds_rate():
    """smoothness 는 설정 가속도를 넘지 않는다 — _ramp docstring 의 약속."""
    b = _Rec()
    await b._ramp(200, 8000, 20000.0, "scurve")
    slopes = []
    for (t1, h1), (t2, h2) in zip(b.w, b.w[1:]):
        if t2 > t1:
            slopes.append((h2 - h1) / (t2 - t1))
    # 실측 피크 18.8k — 스케줄상 rate 를 넘지 않아야 한다 (지터 5% 허용)
    assert max(slopes) <= 20000.0 * 1.05, max(slopes)


async def test_both_shapes_land_on_target_frequency():
    for shape in ("linear", "scurve"):
        hz, _, est = await _run(shape)
        assert hz[-1] == 8000, shape
        assert est > 0
