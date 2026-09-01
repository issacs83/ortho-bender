"""
motion_profiles.py — 보드에 영속되는 축별 모션 설정.

각 축은 자기만의 조그 기본값과 가감속 프로파일을 가진다. GRBL의
$-settings / Klipper의 printer.cfg 와 같은 성격이다:

  jog_speed   units/s   기본 조그 속도 (FEED/LIFT는 mm/s, BEND/ROTATE는 deg/s)
  max_speed   units/s   머신 속도 상한 — 이보다 큰 명령은 클램프된다
                        (GRBL $110-112 / LinuxCNC MAX_VELOCITY 대응)
  step_size   units     증분 조그 1회 이동 거리
  start_hz    Hz        램프 시작 주파수 — 최초로 내보내는 STEP 주파수
  accel       units/s²  가속도 (GRBL $120-122 / LinuxCNC
                        MAX_ACCELERATION 대응)
  decel       units/s²  정지/종료 시 감속 램프에 쓰는 감속도
  shape       str       "linear"(사다리꼴 속도) | "scurve"
                        (저크 제한 smoothstep — 가속도가 C1 연속)

accel/decel은 물리 단위(mm/s² 또는 deg/s²)라서 마이크로스텝이나
캘리브레이션이 바뀌어도 의미가 그대로 유지된다. MotorService가 속도에
쓰는 것과 동일한 축별 steps_per_unit 로 이 값을 램프 엔진이 소비하는
STEP 주파수 기울기(Hz/s)로 변환한다.

S-curve는 smoothstep 주파수 스케줄 f(τ)=S+(F−S)(3τ²−2τ³) 이며 그 최대
기울기가 설정된 accel 과 같아지도록 T를 잡는다. 즉 `shape` 를 바꿔도
설정한 최대 가속도는 변하지 않고 부드러움만 달라진다.

상태 파일: /var/lib/ortho-bender/motion_profiles.json
IEC 62304 SW Class: B
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile

log = logging.getLogger(__name__)

_STATE_FILE = "/var/lib/ortho-bender/motion_profiles.json"

PROFILE_SHAPES = ("linear", "scurve")

# ---------------------------------------------------------------------------
# 튜닝 가이드 — 아래 7개 키가 이 벤치의 모션 튜닝 창구 전부다.
# 모두 축별이며 다음 API 로 실시간 변경할 수 있고
#   PUT /api/motor/profiles/{axis}   (axis: 0=FEED 1=BEND 2=ROTATE 3=LIFT)
# _STATE_FILE 에 영속되므로 재시작해도 튜닝값이 살아 있다.
#
# 튜닝 순서 (각 단계는 앞 단계가 확정되었다고 가정한다):
#   0. steps_per_unit  — services/calibration_service.py. 여기 있는 값은
#      전부 물리 단위이므로 캘리브레이션이 틀리면 속도와 가속도가 함께
#      틀어진다. 캘리브레이션부터 맞추고 그다음에 튜닝한다.
#   1. max_speed  — 축이 스톨/스텝 유실을 낼 때까지 올린 뒤 30 % 정도 후퇴.
#      하드웨어 천장은 8000 Hz / steps_per_unit (speed_limit()) 이고 명령은
#      둘 다에 클램프되므로, 여기에 360 을 넣는다고 STEP 경로가 낼 수 있는
#      것보다 빨라지지는 않는다.
#   2. accel/decel — 가속 자체가 스톨을 유발할 때까지 올린 뒤 후퇴한다
#      (최고 속도에서 나는 스톨 = max_speed 과다, 이동 시작 직후의 스톨 =
#      accel 과다).
#   3. start_hz   — 램프는 0 Hz 에서 출발하지 않는다. 너무 낮으면 어차피
#      토크가 충분한 200 Hz 미만 구간에서 시간을 낭비하고, 너무 높으면 첫
#      펄스에서 스텝을 잃는다. 200~600 Hz 가 실용 구간이다.
#   4. shape      — 기구가 울리거나 와이어가 출렁이면 "scurve".
#      최대 가속도를 낮춰 주지는 않고(위 smoothstep 설명 참조) 저크 계단만
#      없애며, 램프가 약 50 % 길어지는 비용이 있다.
#   5. jog_speed / step_size — 운전자 편의값일 뿐 물리적 의미는 없다.
# ---------------------------------------------------------------------------
DEFAULT_PROFILE: dict = {
    # 조그 버튼 / 증분 조그의 기본 속도. UI 초기값일 뿐이며 아래
    # _validate() 에서 max_speed 로 클램프된다.
    "jog_speed": 10.0,
    # 머신 속도 상한(GRBL $110-112). MotorService._max_speed_for() 가 모든
    # jog/move/move_to 를 여기에 클램프하므로 API 를 직접 호출해도 넘길 수
    # 없다. 캘리브레이션의 speed_limit()(= 8000 Hz / steps_per_unit)에도
    # 다시 클램프되며 — 둘 중 더 낮은 쪽이 이긴다.
    "max_speed": 40.0,
    # 증분 조그 버튼 1회 이동량(축 단위).
    "step_size": 1.0,
    # 램프 바닥값: 최초로 내보내는 STEP 주파수이자 감속 램프가 되돌아오는
    # 주파수. 200 Hz 미만은 이 벤치의 PWM 경로에서 검증된 적이 없다
    # (pulse_step 이 어차피 [200, 8000] Hz 로 클램프한다).
    "start_hz": 200,
    # 가속도(물리 단위, mm/s² 또는 deg/s²). 램프 엔진이 소비하는 STEP 주파수
    # 기울기로 MotorService._profile_for() 가 변환한다 —
    # accel_hz_s = accel × steps_per_unit, 다시 [200, 40000] Hz/s 로 클램프.
    # 알아 둘 만한 결과가 둘 있다:
    #   • 축을 재캘리브레이션해도 물리적인 체감은 그대로 유지된다.
    #   • 거친 축(BEND, 23 steps/deg)은 40000 Hz/s 클램프에 닿지 못하고,
    #     고운 축(LIFT, 200 steps/mm)은 accel > 200 mm/s² 면 바로 닿는다 —
    #     _BOUNDS 가 200 에서 멈추는 이유다.
    "accel": 40.0,   # units/s² — 기본값 200 steps/unit 에서 8000 Hz/s
    # 정지 / 이동 종료 램프의 감속도. 중력축(LIFT)은 가속보다 더 강하게
    # 제동해야 할 수 있어서 accel 과 분리해 두었다.
    # pulse_step 은 추가로, 필요하면 감속률을 높여서라도 정지가
    # _RAMP_DOWN_MAX_S(1 s) 를 넘지 않도록 보장한다.
    "decel": 40.0,
    # "linear"  = 사다리꼴 속도(가속도 일정, 모서리에서 저크 계단) —
    #             가장 빠르며 기본값이다.
    # "scurve"  = smoothstep 주파수 스케줄, 가속도가 C1 연속.
    #             최대 가속도는 동일하고 램프가 약 1.5 배 길어지는 대신
    #             기구 울림이 크게 준다. accel 을 낮추기 전에 먼저 시도할 것.
    "shape": "linear",
}

# 축별 "최적" 기본값 — 초기화 버튼이 되돌아가는 지점. 이 벤치의 실측
# (2026-08~09 캠페인)에서 고른 값이며 DEFAULT_PROFILE 위에 겹쳐진다:
#   FEED — 미세이송이 존재 이유인 축. 이송 실사용 10 mm/s, 상한 40.
#   BEND — 토크 축. 가감속 80 (기존 운용값), 벤딩 속도 20, 상한 90
#          (실측 스톨 여유는 347 이지만 벤딩 품질 여유로 후퇴).
#   LIFT — 중력 축. 보수적 속도(5/25)에 제동(decel)을 가속의 2배로 —
#          내려갈 때 관성+중력을 이겨야 한다.
AXIS_OPTIMAL: dict[int, dict] = {
    0: {"jog_speed": 10.0, "max_speed": 40.0, "accel": 40.0, "decel": 40.0},
    1: {"jog_speed": 20.0, "max_speed": 90.0, "accel": 80.0, "decel": 80.0},
    2: {},                                        # ROTATE 미장착 — 기본값
    3: {"jog_speed": 5.0,  "max_speed": 25.0, "accel": 40.0, "decel": 80.0},
}

# 물리 단위 도입 이전의 상태 파일을 마이그레이션할 때 쓰는 기본 캘리브레이션
# 가정값(accel_hz_s → accel). CalibrationService 의 기본값과 같다.
_LEGACY_STEPS_PER_UNIT = 200.0

# 하드 바운드 — 프로파일을 이 벤치 PWM 경로가 검증된 범위 안에 묶어 둔다.
# 속도는 추가로 calibration_service 의 축별 SPEED_LIMIT 에도 걸린다.
# 이건 튜닝 목표가 아니라 봉투(envelope) 다: 범위 안의 값은 그대로 받아들여진
# 뒤 조용히 클램프되고(400 을 내지 않는다), 명령 시점에 축 캘리브레이션으로
# 한 번 더 클램프된다. 그래서 "max_speed 를 360 으로 올렸는데 축이 안 빨라진다"
# 는 정상이다 — 먼저 그 축의 speed_limit() 을 확인할 것.
_BOUNDS = {
    "jog_speed":  (0.1, 360.0),
    "max_speed":  (0.1, 360.0),
    "step_size":  (0.01, 360.0),
    "start_hz":   (50, 2000),     # pulse_step 이 [200, 8000] Hz 로 재클램프
    "accel":      (1.0, 200.0),   # units/s² (200 steps/unit 기준 200~40000 Hz/s)
    "decel":      (1.0, 200.0),
}

AXES = (0, 1, 2, 3)  # FEED, BEND, ROTATE, LIFT


class MotionProfileService:
    """축별 모션 프로파일 보관 + 즉시 기록(write-through) 영속화."""

    def __init__(self, state_file: str = _STATE_FILE) -> None:
        self._state_file = state_file
        self._profiles: dict[int, dict] = {a: dict(DEFAULT_PROFILE) for a in AXES}
        self._load()

    # ------------------------------------------------------------- 저장소
    def _load(self) -> None:
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for k, v in raw.items():
                try:
                    axis = int(k)
                except ValueError:
                    continue
                if axis in self._profiles and isinstance(v, dict):
                    # 손으로 고쳤거나 깨진 항목은 "그 축만" 기본값으로
                    # 떨어뜨려야 하며 절대 기동을 중단시키면 안 된다
                    # (이 서비스는 lifespan 경로에 있어서 여기서 죽으면
                    # SDK 전체가 내려간다).
                    try:
                        # 예전 상태 파일은 accel 을 Hz/s 로 저장했다.
                        # 기본 캘리브레이션으로 물리 단위로 변환한다.
                        for old, new in (("accel_hz_s", "accel"),
                                         ("decel_hz_s", "decel")):
                            if old in v and new not in v:
                                v[new] = float(v[old]) / _LEGACY_STEPS_PER_UNIT
                        merged = dict(DEFAULT_PROFILE)
                        merged.update({kk: vv for kk, vv in v.items()
                                       if kk in DEFAULT_PROFILE})
                        self._profiles[axis] = self._validate(merged)
                    except (ValueError, TypeError) as exc:
                        log.warning("Motion profile axis=%d invalid (%s) — "
                                    "using defaults", axis, exc)
                        self._profiles[axis] = dict(DEFAULT_PROFILE)
            log.info("MotionProfileService: loaded %s", self._state_file)
        except FileNotFoundError:
            log.info("MotionProfileService: no state file — using defaults")
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("MotionProfileService: load failed (%s) — defaults", exc)

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self._state_file),
                                   prefix=".motion.", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({str(k): v for k, v in self._profiles.items()}, f, indent=1)
            os.replace(tmp, self._state_file)
        except OSError as exc:
            log.error("MotionProfileService: save failed: %s", exc)
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # ------------------------------------------------------------ 공개 API
    @staticmethod
    def _validate(p: dict) -> dict:
        out = dict(p)
        for key, (lo, hi) in _BOUNDS.items():
            val = float(out[key])
            if not math.isfinite(val):
                # NaN/inf 는 상한으로 클램프되어 버린다(NaN 이 섞인 max/min 은
                # 인자 순서에 따라 결과가 달라진다) — 안전한 기본값으로 되돌린다.
                val = float(DEFAULT_PROFILE[key])
            out[key] = max(lo, min(hi, val))
        # 조그 기본값은 축의 머신 상한을 절대 넘을 수 없다
        out["jog_speed"] = min(out["jog_speed"], out["max_speed"])
        out["start_hz"] = int(out["start_hz"])
        if out.get("shape") not in PROFILE_SHAPES:
            out["shape"] = "linear"
        return out

    def get(self, axis: int) -> dict:
        return dict(self._profiles.get(int(axis), DEFAULT_PROFILE))

    def all(self) -> dict[int, dict]:
        return {a: dict(p) for a, p in self._profiles.items()}

    def reset(self, speed_ceilings: dict[int, float] | None = None) -> dict:
        """전 축을 출고 기본값(DEFAULT_PROFILE)으로 되돌린다.

        speed_ceilings 가 주어지면(축별 8000/steps_per_unit) jog/max 를
        그 상한으로 함께 클램프한다 — 기본 max(40)가 현재 분주비의 상한보다
        클 수 있기 때문이다(예: 1/256 이면 상한 7.9).
        """
        for axis in list(self._profiles.keys()):
            prof = dict(DEFAULT_PROFILE)
            prof.update(AXIS_OPTIMAL.get(int(axis), {}))
            ceil = (speed_ceilings or {}).get(int(axis))
            if ceil:
                prof["jog_speed"] = min(prof["jog_speed"], round(ceil, 3))
                prof["max_speed"] = min(prof["max_speed"], round(ceil, 3))
            self._profiles[axis] = self._validate(prof)
        self._save()
        log.info("Motion profiles reset to defaults%s",
                 " (ceiling-clamped)" if speed_ceilings else "")
        return self.all()

    def update(self, axis: int, patch: dict) -> dict:
        axis = int(axis)
        if axis not in self._profiles:
            raise ValueError(f"Unknown axis {axis}")
        merged = dict(self._profiles[axis])
        merged.update({k: v for k, v in patch.items()
                       if k in DEFAULT_PROFILE and v is not None})
        self._profiles[axis] = self._validate(merged)
        self._save()
        log.info("Motion profile axis=%d updated: %s", axis, self._profiles[axis])
        return dict(self._profiles[axis])
