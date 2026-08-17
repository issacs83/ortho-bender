"""
calibration_service.py — Per-axis step/unit calibration persisted on disk.

Each axis has a `steps_per_unit` value:
  FEED   step/deg  — wire feed roller (rotary), degrees of roller travel
  BEND   step/deg  — bend die gear ratio × 360 / steps_per_rev
  ROTATE step/deg  — wire rotation gear ratio × 360 / steps_per_rev
  LIFT   step/mm   — lift mechanism lead screw mm/rev / steps_per_rev

Until the wire-bender mechanicals are connected the bench default is a
legacy placeholder of 200 steps/unit. Note the true motor-shaft math at
the current driver programming (DRVCTRL 1/16 microstep + DEDGE): one
revolution = 3200 microsteps = 1600 PWM cycles, and the "steps" counted
by the backend are PWM cycles. So with the 200 default, 1 unit ≈ 1/8
revolution — calibrate per-axis from the Settings page once mechanicals
are attached; do NOT trust the default for real distances.

State file: /var/lib/ortho-bender/axis_calibration.json
Defaults are conservative — they make speed=10 "units/s" equivalent to
the previous behaviour (2000 Hz step rate, fast enough on bench).

IEC 62304 SW Class: B
"""

from __future__ import annotations

import json
import logging
import os
import tempfile

log = logging.getLogger(__name__)

# Bench defaults — configurable via /api/motor/calibration.
DEFAULT_STEPS_PER_UNIT: dict[int, float] = {
    0: 200.0,   # FEED   (mm)
    1: 200.0,   # BEND   (deg)
    2: 200.0,   # ROTATE (deg)
    3: 200.0,   # LIFT   (mm)
}

# Axis-specific safety caps for `distance` in jog/move (in user units).
# Keep these conservative — exceeding them would push step counts into
# multi-second runs that are easy to start by accident.
DISTANCE_LIMIT: dict[int, float] = {
    0: 360.0,   # FEED  ≤ 360 deg (rotary feed roller)
    1: 360.0,   # BEND  ≤ 360 deg
    2: 360.0,   # ROTATE ≤ 360 deg
    # LIFT stroke measured 2026-08-16: top limit switch -> bottom =
    # 230 mm (46,065 steps at 200 steps/mm; T8 lead screw, 8 mm/rev,
    # 1600 steps/rev — the 200 default is exactly right for it).
    3: 240.0,   # LIFT  ≤ 240 mm (full stroke + margin)
}

# The pulse path clamps STEP output to [200, 8000] Hz, so the real speed
# ceiling of an axis is 8000 / steps_per_unit — a different number in
# user units for every axis. Hard-coding it went stale the moment BEND
# was recalibrated (200 -> 23.0167 steps/deg turned a 40 deg/s cap into
# 920 Hz, a fifth of what the hardware can do), so it is derived now.
#   FEED  200 steps/deg -> 40 deg/s
#   BEND  23.0167       -> 347.6 deg/s
#   LIFT  200 steps/mm  -> 40 mm/s
MAX_STEP_HZ = 8000.0

# Floor for axes whose calibration is implausibly large (protects against
# a mis-typed steps_per_unit locking the axis at a crawl).
MIN_SPEED_LIMIT = 1.0

_STATE_FILE = "/var/lib/ortho-bender/axis_calibration.json"


class CalibrationService:
    """Holds the four steps_per_unit values + write-through to disk."""

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

    # -- accessors ----------------------------------------------------------
    def steps_per_unit(self, axis: int) -> float:
        return self._steps.get(int(axis), DEFAULT_STEPS_PER_UNIT.get(int(axis), 200.0))

    def distance_limit(self, axis: int) -> float:
        return DISTANCE_LIMIT.get(int(axis), 50.0)

    def speed_limit(self, axis: int) -> float:
        """Max commandable speed in this axis' own units.

        Derived from the hardware STEP ceiling and the axis calibration,
        so it stays correct when steps_per_unit changes.
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
