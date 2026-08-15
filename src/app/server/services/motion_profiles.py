"""
motion_profiles.py — Per-axis motion settings persisted on the board.

Each axis carries its own jog defaults and acceleration profile, in the
spirit of GRBL's $-settings / Klipper's printer.cfg:

  jog_speed   units/s   default jog rate (mm/s for FEED/LIFT, deg/s BEND/ROTATE)
  max_speed   units/s   machine velocity limit — commands above it are clamped
                        (GRBL $110-112 / LinuxCNC MAX_VELOCITY analog)
  step_size   units     incremental-jog distance
  start_hz    Hz        ramp floor — first commanded step frequency
  accel       units/s²  acceleration (GRBL $120-122 / LinuxCNC
                        MAX_ACCELERATION analog)
  decel       units/s²  deceleration used for ramp-down on stop/finish
  shape       str       "linear" (trapezoidal velocity) | "scurve"
                        (jerk-limited smoothstep — C1-continuous accel)

accel/decel are physical (mm/s² or deg/s²) so their meaning survives
microstep/calibration changes; MotorService converts them to the STEP
frequency slew (Hz/s) the ramp engine consumes, via the same per-axis
steps_per_unit calibration used for speed.

The S-curve is a smoothstep frequency schedule f(τ)=S+(F−S)(3τ²−2τ³)
whose peak slope equals the configured accel, so `shape` changes
smoothness without changing the configured peak acceleration.

State file: /var/lib/ortho-bender/motion_profiles.json
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

DEFAULT_PROFILE: dict = {
    "jog_speed": 10.0,
    "max_speed": 40.0,
    "step_size": 1.0,
    "start_hz": 200,
    "accel": 40.0,   # units/s² — 8000 Hz/s at the default 200 steps/unit
    "decel": 40.0,
    "shape": "linear",
}

# Default calibration assumption for migrating pre-physical-unit state
# files (accel_hz_s → accel). Matches CalibrationService's default.
_LEGACY_STEPS_PER_UNIT = 200.0

# Hard bounds — keep profiles inside what the bench PWM path was
# validated for. Speed itself is additionally capped by the per-axis
# SPEED_LIMIT in calibration_service.
_BOUNDS = {
    "jog_speed":  (0.1, 360.0),
    "max_speed":  (0.1, 360.0),
    "step_size":  (0.01, 360.0),
    "start_hz":   (50, 2000),
    "accel":      (1.0, 200.0),   # units/s² (200–40000 Hz/s at 200 steps/unit)
    "decel":      (1.0, 200.0),
}

AXES = (0, 1, 2, 3)  # FEED, BEND, ROTATE, LIFT


class MotionProfileService:
    """Holds per-axis motion profiles + write-through persistence."""

    def __init__(self, state_file: str = _STATE_FILE) -> None:
        self._state_file = state_file
        self._profiles: dict[int, dict] = {a: dict(DEFAULT_PROFILE) for a in AXES}
        self._load()

    # ------------------------------------------------------------- store
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
                    # A hand-edited/corrupt entry must degrade THIS axis to
                    # defaults, never abort startup (this service is in the
                    # lifespan path — a crash here takes the whole SDK down).
                    try:
                        # Legacy state files stored accel in Hz/s; convert
                        # to physical units with the default calibration.
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

    # ------------------------------------------------------------ public
    @staticmethod
    def _validate(p: dict) -> dict:
        out = dict(p)
        for key, (lo, hi) in _BOUNDS.items():
            val = float(out[key])
            if not math.isfinite(val):
                # NaN/inf would clamp to the UPPER bound (max/min with NaN
                # is order-dependent) — fall back to the safe default.
                val = float(DEFAULT_PROFILE[key])
            out[key] = max(lo, min(hi, val))
        # jog default can never exceed the axis machine limit
        out["jog_speed"] = min(out["jog_speed"], out["max_speed"])
        out["start_hz"] = int(out["start_hz"])
        if out.get("shape") not in PROFILE_SHAPES:
            out["shape"] = "linear"
        return out

    def get(self, axis: int) -> dict:
        return dict(self._profiles.get(int(axis), DEFAULT_PROFILE))

    def all(self) -> dict[int, dict]:
        return {a: dict(p) for a, p in self._profiles.items()}

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
