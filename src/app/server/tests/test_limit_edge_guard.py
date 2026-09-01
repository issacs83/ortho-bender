"""
test_limit_edge_guard.py — 리밋 가드는 폴 사이에 스쳐 간 창도 잡는다.

레벨 폴링(10 ms 슬라이스)만으로는 고속 통과를 원리적으로 놓칠 수 있고,
실제로 놓친 사례가 있다(2026-09-02, 사용자 보고). make_limit_guard 는
레벨 '또는' 장전 이후의 커널 falling 에지 누적으로 판정한다 — 여기서는
"레벨은 이미 False 로 돌아왔지만 에지 카운터가 증가한" 상황(=스쳐 간
창)이 트립으로 잡히는지를 고정한다. 축별 가드 설정(guard_axes)의 API
매핑·영속화·프로파일 상한 연동도 함께 고정한다.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest

from server.services.spi_backend import SpidevMotorBackend
from server.services.motor_service import MotorService
from server.services.motor_backend import MockMotorBackend

LIFT_CS, BEND_CS = 0, 1


class _EdgeBench(SpidevMotorBackend):
    """레벨/에지를 스크립트로 흉내 내는 백엔드."""

    def __init__(self):
        super().__init__()
        self.level: bool | None = False       # limit_active 가 돌려줄 값
        self.falls = 0                        # 커널 에지 카운터 흉내

    def limit_active(self, cs):
        return self.level

    def _drain_limit_edges(self):
        pass

    def _limit_falls(self, cs):
        return self.falls

    def _save_state_soon(self):
        pass


def test_fast_pass_caught_by_edge_counter():
    """창을 '스쳐 지나감': 폴 시점 레벨은 계속 False 지만 falling 에지가
    쌓였다 — 반드시 트립."""
    b = _EdgeBench()
    b.guard_axes = {LIFT_CS}
    st, check = b.make_limit_guard(LIFT_CS)
    assert st["armed"] and not check()
    b.falls += 1                  # 폴 사이에 눌렸다 풀림 (레벨은 그대로 False)
    assert check() is True, "에지 누적이 판정에 반영되지 않았다"


def test_level_hit_still_trips():
    b = _EdgeBench()
    b.guard_axes = {LIFT_CS}
    st, check = b.make_limit_guard(LIFT_CS)
    b.level = True
    assert check() is True


def test_start_inside_window_arms_after_exit():
    """창 안에서 출발: 벗어나기 전 에지는 무시, 벗어난 뒤부터 판정."""
    b = _EdgeBench()
    b.guard_axes = {LIFT_CS}
    b.level = True
    st, check = b.make_limit_guard(LIFT_CS)
    assert not st["armed"] and not check()
    b.falls += 3                  # 창 안에서의 잡음 — 장전 전이므로 무시
    assert not check()
    b.level = False               # 창을 벗어남 → 장전 (base 갱신)
    assert not check()
    b.falls += 1                  # 재진입 스침
    assert check() is True


def test_unguarded_axis_never_trips():
    b = _EdgeBench()
    b.guard_axes = {LIFT_CS}
    st, check = b.make_limit_guard(BEND_CS)   # BEND 는 가드 밖
    b.level = True
    b.falls += 5
    assert check() is False


# ── guard_axes API 매핑 · 영속 · 프로파일 상한 연동 ────────────────────

class _Bench(MockMotorBackend):
    def __init__(self):
        super().__init__()
        self.limit_guard = True
        self.guard_axes = {0}
        self._cs_to_limit = {0: "limit_lift", 1: "limit_bend"}
        self.mres_map = {2: 3}
        self.snap_axes = set()
        self.hold_axes = set()
        self.hold_cs_map = {}
        self.run_cs_map = {}

    def usteps_for(self, cs): return 32
    def set_axis_microstep(self, cs, microsteps):
        old = 32
        self.mres_map[cs] = {64: 2, 128: 1, 256: 0, 32: 3, 16: 4}[microsteps]
        return microsteps / old
    def _save_state_soon(self): pass
    def run_cs_for(self, cs): return 14
    def effective_cs(self, cs=None): return 14
    def hold_cs_for(self, cs): return 8


class _Cal:
    def __init__(self): self.spu = {0: 127.324, 1: 23.0167, 3: 200.0}
    def steps_per_unit(self, a): return self.spu.get(int(a), 200.0)
    def distance_limit(self, a): return 200.0
    def speed_limit(self, a): return round(8000.0 / self.steps_per_unit(a), 1)
    def update(self, a, v): self.spu[int(a)] = float(v)


class _Profiles:
    def __init__(self): self.p = {0: {"jog_speed": 20.0, "max_speed": 60.0}}
    def get(self, a): return dict(self.p.get(int(a), {}))
    def update(self, a, patch): self.p.setdefault(int(a), {}).update(patch)


@pytest.fixture
def svc():
    s = MotorService(ipc=None, spidev_backend=_Bench())
    s.set_calibration(_Cal())
    s.set_motion_profiles(_Profiles())
    return s


async def test_guard_axes_api_axis_id_mapping(svc):
    out = await svc.set_protection(guard_axes=[3, 1])   # LIFT, BEND (축 id)
    assert svc._spi_backend.guard_axes == {0, 1}        # cs 로 변환됨
    assert out["guard_axes"] == [1, 3]


async def test_guard_axes_rejects_sensorless_axis(svc):
    with pytest.raises(ValueError):
        await svc.set_protection(guard_axes=[0])        # FEED — 센서 없음


async def test_microstep_change_clamps_profile_speeds(svc):
    """1/32→1/256: 상한 62.8→7.9 — 프로파일 jog/max 가 함께 내려간다."""
    await svc.set_microstep(0, microsteps=256)
    prof = svc._motion_profiles.get(0)
    ceil = svc._calibration.speed_limit(0)
    assert prof["jog_speed"] <= ceil and prof["max_speed"] <= ceil
    assert ceil == pytest.approx(7.9, abs=0.1)


async def test_microstep_widen_keeps_user_speeds(svc):
    """상한이 넓어질 때(1/32→1/16)는 사용자 프로파일을 건드리지 않는다."""
    before = svc._motion_profiles.get(0)
    await svc.set_microstep(0, microsteps=16)
    assert svc._motion_profiles.get(0) == before


class _TripOnceBench(_Bench):
    """첫 pulse 에서 가드 트립을 흉내 내는 벤치 — 이후 pulse 가 오면 안 된다."""
    def __init__(self):
        super().__init__()
        self.pulses = 0
        self.guard_tripped = False

    async def pulse_step(self, axis, count, freq_hz, direction, profile=None):
        self.pulses += 1
        if self.pulses == 1:
            # 37 스텝만 가고 트립
            self.positions[axis] = self.positions.get(axis, 0) + 37 * direction
            self.guard_tripped = True
        else:
            self.positions[axis] = self.positions.get(axis, 0) + count * direction


async def test_guard_trip_halts_whole_move(svc):
    """가드 트립 후 move_to 보정 루프가 재구동하면 안 된다 — 2026-09-02
    실사고(BEND +180° 가 트립 로그를 남기고도 완주) 회귀 고정."""
    bench = _TripOnceBench()
    s2 = MotorService(ipc=None, spidev_backend=bench)
    s2.set_calibration(_Cal())
    await s2.move_to(1, 180.0, speed=250)          # BEND, spu 23.0167
    assert bench.pulses == 1, f"트립 후 재구동됨 (pulses={bench.pulses})"
    assert bench.positions[1] == 37                # 트립 지점에서 정지
