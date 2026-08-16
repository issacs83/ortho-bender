"""
calibration_service.py — Per-axis step/unit calibration persisted on disk.

Each axis has a `steps_per_unit` value:
  FEED   step/mm   — wire feed roller radius × 2π / steps_per_rev
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
    0: 100.0,   # FEED  ≤ 100 mm / command
    1: 360.0,   # BEND  ≤ 360 deg
    2: 360.0,   # ROTATE ≤ 360 deg
    # LIFT stroke measured 2026-08-16: top limit switch -> bottom =
    # 230 mm (46,065 steps at 200 steps/mm; T8 lead screw, 8 mm/rev,
    # 1600 steps/rev — the 200 default is exactly right for it).
    3: 240.0,   # LIFT  ≤ 240 mm (full stroke + margin)
}

# Axis-specific maximum target rate (in user units / sec). Combined with
# steps_per_unit this gives the freq cap. Default keeps backward-compat
# with the prior 4000 Hz hard cap when steps_per_unit = 200.
SPEED_LIMIT: dict[int, float] = {
    0: 40.0,    # FEED  (with 200 step/mm  -> 8000 Hz, ~2400 RPM)
    # BEND calibrated in true degrees 2026-08-16. Sensor-referenced
    # measurement (home slot crossed twice at 253 Hz, inside the motor's
    # self-start region so counted steps == physical steps):
    # 1 rev = 8286 steps -> 23.0167 steps/deg, repeatable to 0.06 %.
    # An earlier eyeballed mark test read 8000 and was 3.6 % low, which
    # is why a commanded 360 deg physically turned ~372 deg.
    # Per-speed check against the slot after this fix: 60/120/300 deg/s
    # land exactly on the slot, 180 deg/s within 0.6 %.
    # The pulse path's [200, 8000] Hz clamp stays the real safety bound
    # (360 deg/s would ask for 8286 Hz and is clamped).
    1: 360.0,   # BEND  (deg/s)
    2: 40.0,    # ROTATE
    3: 40.0,    # LIFT
}

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
        return SPEED_LIMIT.get(int(axis), 20.0)

    def all(self) -> dict:
        return {
            "steps_per_unit": dict(self._steps),
            "distance_limit": dict(DISTANCE_LIMIT),
            "speed_limit":    dict(SPEED_LIMIT),
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
