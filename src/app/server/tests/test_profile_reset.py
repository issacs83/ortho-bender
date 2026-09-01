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


def test_reset_restores_defaults(mp):
    mp.update(0, {"jog_speed": 3.3, "max_speed": 5.5, "accel": 7.0,
                  "shape": "scurve"})
    out = mp.reset()
    for axis, prof in out.items():
        assert prof["max_speed"] == DEFAULT_PROFILE["max_speed"]
        assert prof["jog_speed"] == DEFAULT_PROFILE["jog_speed"]
        assert prof["shape"] == "linear"


def test_reset_clamps_to_speed_ceiling(mp):
    """1/256 급 상한(7.9)이면 기본 jog 10 / max 40 이 7.9 로 잘린다."""
    out = mp.reset({0: 7.9, 1: 347.6, 2: 40.0, 3: 40.0})
    assert out[0]["jog_speed"] == 7.9 and out[0]["max_speed"] == 7.9
    assert out[1]["max_speed"] == DEFAULT_PROFILE["max_speed"]   # 상한이 넓으면 기본값 유지


def test_reset_persists(mp, tmp_path):
    mp.update(0, {"max_speed": 5.0})
    mp.reset()
    fresh = MotionProfiles(state_file=str(tmp_path / "profiles.json"))
    assert fresh.get(0)["max_speed"] == DEFAULT_PROFILE["max_speed"]
