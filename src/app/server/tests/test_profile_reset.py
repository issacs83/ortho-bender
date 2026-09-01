"""
test_profile_reset.py — 프로파일 초기화는 기본값 + 현재 분주비 상한 클램프.

UI 초기화 버튼의 백엔드(POST /api/motor/profiles/reset)를 고정한다:
전 축이 DEFAULT_PROFILE 로 돌아가되, jog/max 는 축별 속도 상한
(8000 / steps_per_unit)을 넘지 않는다 — 기본 max(40)가 1/256 상한(7.9)
보다 클 수 있기 때문이다.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import pytest

from server.services.motion_profiles import MotionProfileService as MotionProfiles, DEFAULT_PROFILE


@pytest.fixture
def mp(tmp_path):
    return MotionProfiles(state_file=str(tmp_path / "profiles.json"))


def test_reset_restores_axis_optimal(mp):
    """초기화는 전역 기본이 아니라 축별 최적값(AXIS_OPTIMAL)으로 간다."""
    mp.update(0, {"jog_speed": 3.3, "max_speed": 5.5, "accel": 7.0,
                  "shape": "scurve"})
    out = mp.reset()
    assert out[0]["max_speed"] == 40.0 and out[0]["decel"] == 40.0
    assert out[1]["max_speed"] == 90.0 and out[1]["accel"] == 80.0   # BEND 토크축
    assert out[3]["max_speed"] == 25.0 and out[3]["decel"] == 80.0   # LIFT 중력 제동 2배
    for prof in out.values():
        assert prof["shape"] == "linear"


def test_reset_clamps_to_speed_ceiling(mp):
    """1/256 급 상한(7.9)이면 기본 jog 10 / max 40 이 7.9 로 잘린다."""
    out = mp.reset({0: 7.9, 1: 347.6, 2: 40.0, 3: 40.0})
    assert out[0]["jog_speed"] == 7.9 and out[0]["max_speed"] == 7.9
    assert out[1]["max_speed"] == 90.0   # 상한(347.6)이 넓으면 축별 최적값 유지


def test_reset_persists(mp, tmp_path):
    mp.update(0, {"max_speed": 5.0})
    mp.reset()
    fresh = MotionProfiles(state_file=str(tmp_path / "profiles.json"))
    assert fresh.get(0)["max_speed"] == 40.0
