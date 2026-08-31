"""
calibration_service.py — 디스크에 영속되는 축별 스텝/단위 캘리브레이션.

각 축은 `steps_per_unit` 값을 하나씩 가진다:
  FEED   step/mm   — 롤러는 회전하지만 단위는 **뽑혀 나온 와이어 mm** 다
  BEND   step/deg  — 벤딩 다이 기어비 × 360 / steps_per_rev
  ROTATE step/deg  — 와이어 회전 기어비 × 360 / steps_per_rev
  LIFT   step/mm   — 리프트 리드스크류 mm/rev / steps_per_rev

모든 축이 자리표시자였던 시절의 설명이 오래 남아 있었다. 지금 상태는
축마다 다르다:
  FEED   63.662  — 산식은 맞으나 롤러 직경이 미실측이라 **잠정값**
  BEND   23.0167 — 리밋 디스크 대비 실측. 5.18:1 유성기어 확정
  ROTATE 200.0   — 벤치 미장착. 자리표시자 그대로
  LIFT   200.0   — 실측. T8 리드스크류 8 mm/rev 에 정확히 맞는 값

드라이버 설정(DRVCTRL 1/16 마이크로스텝 + DEDGE)에서 모터축 계산은
이렇다: 1 회전 = 3200 마이크로스텝 = 1600 PWM 사이클이고, 백엔드가
세는 "스텝"은 PWM 사이클이다. BEND 실측값이 1600 × 5.18 = 8288 과
0.02% 안에서 일치하므로 이 1600 은 가정이 아니라 확인된 수치다.

상태 파일: /var/lib/ortho-bender/axis_calibration.json
기본값은 보수적으로 잡혀 있다 — speed=10 "units/s" 가 이전 동작
(2000 Hz 스텝 레이트, 벤치에서는 충분히 빠름)과 같아지는 값이다.

IEC 62304 SW Class: B
"""

from __future__ import annotations

import json
import logging
import os
import tempfile

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 튜닝 노브 0 — steps_per_unit. motion_profiles.py 의 어떤 값보다 먼저
# 맞춰야 한다: "사용자 단위" 와 STEP 펄스 사이의 환율이라서 거리·속도·
# 가속도를 한꺼번에 스케일하기 때문이다.
#
#   명령 스텝 수   = distance x steps_per_unit
#   STEP 주파수    = speed    x steps_per_unit      (8000 Hz 로 클램프)
#   램프 기울기    = accel    x steps_per_unit      (40000 Hz/s 로 클램프)
#
# 계산하지 말고 측정할 것: 거리를 명령하고, 기계가 실제로 간 거리를 재고,
# 비례로 보정한다 —
#
#   new = old x (명령값 / 실측값)
#   POST /api/motor/calibration {"axis": 0, "steps_per_unit": <new>}
#
# tools/calibrate-feed.py 가 FEED 에 대해 이 절차를 그대로 수행한다. 값은
# _STATE_FILE 에 저장되어 재시작 후에도 남지만 git 에는 없다 — 보드를 다시
# 플래시하면 아래 기본값으로 되돌아온다.
# ---------------------------------------------------------------------------
# 벤치 기본값 — /api/motor/calibration 으로 변경 가능.
DEFAULT_STEPS_PER_UNIT: dict[int, float] = {
    # FEED 는 와이어를 밀어내므로 단위가 롤러 각도가 아니라 와이어 mm 다.
    #
    #   모터 1 회전당 1600 PWM 사이클(1.8 deg = 200 풀스텝, 1/16 마이크로스텝,
    #   DEDGE 가 사이클마다 마이크로스텝 2 개를 넣는다)
    #   x 모터→롤러 2.5:1 감속
    #   = 롤러 1 회전당 4000 사이클
    #   / (pi x 롤러 직경) = 와이어 mm 당 스텝 수
    #
    # 이 상수의 첫 버전에는 2.5:1 이 빠져 있었고, 그래서 정확히 그 배수만큼
    # 적게 이송했다. 10 mm 를 명령하면 약 4 mm 가 나갔지만 아무 오류도
    # 보고되지 않았다 — 개루프 축은 알 방법이 없다. 같은 산식이 BEND 에서
    # 검증된다: 리밋 디스크에 대고 실측한 23.0167 steps/deg 는 5:1 로 팔리는
    # 기어박스가 실제로는 5.179:1 임을 뜻하고, 유성기어가 실제로 도는
    # 5.18:1 과 0.02% 안에서 일치한다.
    #
    # 여전히 잠정치: 롤러 직경은 한 번도 실측하지 않았다. 20 mm 는
    # 자리표시자이며 남은 유일한 미지수다. 한 번의 측정으로 확정된다 —
    # 길이를 명령해서 뽑고, 나온 와이어를 재면 된다:
    #
    #     python3 tools/calibrate-feed.py --base http://<ip>:8000 --mm 100
    #
    0: 63.662,   # FEED (와이어 mm) — 1600 x 2.5 / (pi * 20 mm)
    1: 200.0,   # BEND   (deg)
    2: 200.0,   # ROTATE (deg)
    3: 200.0,   # LIFT   (mm)
}

# jog/move 의 `distance` 에 대한 축별 안전 상한(사용자 단위).
# 보수적으로 유지할 것 — 넘기면 실수로 시작하기 쉬운 수 초짜리 스텝 수가
# 들어가게 된다.
DISTANCE_LIMIT: dict[int, float] = {
    0: 200.0,   # FEED  ≤ 와이어 200 mm (BcodeStep 의 L_mm 최대와 동일)
    1: 360.0,   # BEND  ≤ 360 deg
    2: 360.0,   # ROTATE ≤ 360 deg
    # LIFT 스트로크 실측(2026-08-16): 상단 리밋 스위치 -> 바닥 = 230 mm
    # (200 steps/mm 에서 46,065 스텝. T8 리드스크류 8 mm/rev,
    # 1600 steps/rev — 기본값 200 이 이 축에는 정확히 맞다).
    3: 240.0,   # LIFT  ≤ 240 mm (전체 스트로크 + 여유)
}

# 펄스 경로가 STEP 출력을 [200, 8000] Hz 로 클램프하므로 축의 실제 속도
# 천장은 8000 / steps_per_unit 이고, 사용자 단위로는 축마다 값이 다르다.
# 하드코딩해 두었더니 BEND 를 재캘리브레이션하는 순간 낡은 값이 되어서
# (200 -> 23.0167 steps/deg 로 바뀌자 40 deg/s 상한이 920 Hz, 하드웨어가
# 낼 수 있는 것의 1/5 가 되어 버렸다) 지금은 유도값으로 계산한다.
#   FEED  63.662 steps/mm -> 125.7 mm/s
#   BEND  23.0167         -> 347.6 deg/s
#   LIFT  200 steps/mm    -> 40 mm/s
MAX_STEP_HZ = 8000.0

# 캘리브레이션 값이 비상식적으로 큰 축을 위한 하한(steps_per_unit 을 잘못
# 입력해서 축이 기어가는 속도로 잠기는 것을 막는다).
MIN_SPEED_LIMIT = 1.0

_STATE_FILE = "/var/lib/ortho-bender/axis_calibration.json"


class CalibrationService:
    """네 축의 steps_per_unit 보관 + 디스크 즉시 기록."""

    def __init__(self, state_file: str = _STATE_FILE) -> None:
        self._state_file = state_file
        self._steps: dict[int, float] = dict(DEFAULT_STEPS_PER_UNIT)
        self._load()

    def _load(self) -> None:
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                d = json.load(f).get("steps_per_unit", {})
            for k, v in d.items():
                axis = int(k)
                if axis in self._steps and isinstance(v, (int, float)) and v > 0:
                    self._steps[axis] = float(v)
            log.info("CalibrationService: loaded %s", self._steps)
        except FileNotFoundError:
            log.info("CalibrationService: no state file, using defaults")
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("CalibrationService load failed (%s) — defaults", exc)

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self._state_file), prefix=".cal.", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"steps_per_unit": {str(k): v for k, v in self._steps.items()}}, f)
            os.replace(tmp, self._state_file)
        except OSError as exc:
            log.error("CalibrationService save failed: %s", exc)
            try: os.unlink(tmp)
            except OSError: pass

    # -- 접근자 -------------------------------------------------------------
    def steps_per_unit(self, axis: int) -> float:
        return self._steps.get(int(axis), DEFAULT_STEPS_PER_UNIT.get(int(axis), 200.0))

    def distance_limit(self, axis: int) -> float:
        return DISTANCE_LIMIT.get(int(axis), 50.0)

    def speed_limit(self, axis: int) -> float:
        """이 축 고유 단위로 표현한 최대 명령 가능 속도.

        하드웨어 STEP 천장과 축 캘리브레이션에서 유도하므로
        steps_per_unit 이 바뀌어도 계속 올바른 값이 나온다.
        """
        spu = self.steps_per_unit(axis)
        if spu <= 0:
            return MIN_SPEED_LIMIT
        return max(MIN_SPEED_LIMIT, round(MAX_STEP_HZ / spu, 1))

    def all(self) -> dict:
        return {
            "steps_per_unit": dict(self._steps),
            "distance_limit": dict(DISTANCE_LIMIT),
            "speed_limit":    {a: self.speed_limit(a)
                               for a in DEFAULT_STEPS_PER_UNIT},
        }

    def update(self, axis: int, steps_per_unit: float) -> None:
        if steps_per_unit <= 0:
            raise ValueError("steps_per_unit must be > 0")
        if steps_per_unit > 100_000:
            raise ValueError("steps_per_unit unreasonably large (>100000)")
        axis = int(axis)
        if axis not in DEFAULT_STEPS_PER_UNIT:
            raise ValueError(f"unknown axis {axis}")
        self._steps[axis] = float(steps_per_unit)
        self._save()
