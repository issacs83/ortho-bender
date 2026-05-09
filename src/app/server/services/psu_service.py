"""
psu_service.py — Power-supply preset selection persisted on the board.

Background
----------
The frontend lets the operator pick a PSU rating so the IRUN/IHOLD slider
caps shrink to fit. That UI cap is necessary but not sufficient: a caller
that talks directly to /api/motor/diag/register/... or to a non-default
client could still ask the driver for CS=19 on a 2 A brick. So the same
selection is mirrored on the server and the diagnostic register-write
path consults this service before applying any SGCSCONF write.

The presets MUST match the frontend list in
src/app/frontend/src/constants.ts (PSU_PRESETS) — same id, same csCap.

State file: /var/lib/ortho-bender/psu.json — written atomically and
loaded at service start. Default = "12v2.9a" (the bench PSU).

IEC 62304 SW Class: B
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PsuPreset:
    id: str
    label: str
    volts: float
    amps: float
    cs_cap: int


# Keep this list in lock-step with frontend PSU_PRESETS.
PSU_PRESETS: tuple[PsuPreset, ...] = (
    PsuPreset("12v2.0a", "12 V / 2.0 A (24 W)", 12.0, 2.0, 12),
    PsuPreset("12v2.9a", "12 V / 2.9 A (35 W)", 12.0, 2.9, 14),
    PsuPreset("12v5.0a", "12 V / 5.0 A (60 W)", 12.0, 5.0, 17),
    PsuPreset("12v8.0a", "12 V / 8.0 A (96 W)", 12.0, 8.0, 19),
    PsuPreset("24v3.0a", "24 V / 3.0 A (72 W)", 24.0, 3.0, 19),
)
PSU_DEFAULT_ID = "12v2.9a"
_BY_ID: dict[str, PsuPreset] = {p.id: p for p in PSU_PRESETS}

# Older builds wrote different ids — translate them on load instead of
# falling back to the default and silently losing the operator's choice.
_LEGACY_ID_MAP: dict[str, str] = {
    "12v2a":  "12v2.0a",
    "12v35w": "12v2.9a",
    "12v5a":  "12v5.0a",
    "12v8a":  "12v8.0a",
    "24v3a":  "24v3.0a",
}

_STATE_FILE = "/var/lib/ortho-bender/psu.json"


class PsuService:
    """Persist + serve the active PSU preset."""

    def __init__(self, state_file: str = _STATE_FILE) -> None:
        self._state_file = state_file
        self._psu_id: str = PSU_DEFAULT_ID
        self._load()

    # -------------------------------------------------------------- Persistence
    def _load(self) -> None:
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                raw = json.load(f).get("psu_id", PSU_DEFAULT_ID)
            psu_id = _LEGACY_ID_MAP.get(raw, raw)
            if psu_id in _BY_ID:
                self._psu_id = psu_id
                log.info("PsuService: loaded psu_id=%s from %s", psu_id, self._state_file)
            else:
                log.warning(
                    "PsuService: unknown psu_id=%r in %s, falling back to %s",
                    raw, self._state_file, PSU_DEFAULT_ID,
                )
        except FileNotFoundError:
            log.info("PsuService: no state file, using default %s", PSU_DEFAULT_ID)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("PsuService: load failed (%s) — using default", exc)

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
        # Atomic write so a crash mid-save doesn't leave a 0-byte file
        # that would silently downgrade the bench to the default PSU.
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self._state_file), prefix=".psu.", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"psu_id": self._psu_id}, f)
            os.replace(tmp, self._state_file)
        except OSError as exc:
            log.error("PsuService: save failed: %s", exc)
            try: os.unlink(tmp)
            except OSError: pass

    # ----------------------------------------------------------------- Public
    @property
    def psu(self) -> PsuPreset:
        return _BY_ID[self._psu_id]

    @property
    def psu_id(self) -> str:
        return self._psu_id

    @property
    def cs_cap(self) -> int:
        """Effective per-axis CS cap from the active PSU preset."""
        return self.psu.cs_cap

    def set_psu(self, psu_id: str) -> PsuPreset:
        psu_id = _LEGACY_ID_MAP.get(psu_id, psu_id)
        if psu_id not in _BY_ID:
            raise ValueError(
                f"Unknown PSU id {psu_id!r}. Allowed: {[p.id for p in PSU_PRESETS]}"
            )
        if psu_id != self._psu_id:
            log.info("PsuService: psu_id %s -> %s", self._psu_id, psu_id)
            self._psu_id = psu_id
            self._save()
        return self.psu
