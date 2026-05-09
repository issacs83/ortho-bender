/**
 * useAxisCalibration.ts — fetches GET /api/motor/calibration and exposes
 * a setter that POSTs back. Cached in memory; falls back to localStorage
 * + 200-step defaults if the backend is unreachable.
 *
 * AXIS_NAMES indexing matches the wire (idx 0..3 = FEED/BEND/ROTATE/LIFT).
 * Each axis carries its native unit:
 *   FEED   → mm
 *   BEND   → deg
 *   ROTATE → deg
 *   LIFT   → mm
 */

import { useEffect, useRef, useState } from 'react';
import { usePersistentState } from './usePersistentState';

const CACHE_KEY = 'settings.axisCalibration';

// idx-aligned with AXIS_NAMES = [FEED, BEND, ROTATE, LIFT]
export const AXIS_PHYSICAL_UNIT = ['mm', 'deg', 'deg', 'mm'] as const;
export const DEFAULT_STEPS_PER_UNIT = [200, 200, 200, 200] as const;
export const DEFAULT_DISTANCE_LIMIT = [100, 360, 360, 100] as const;
export const DEFAULT_SPEED_LIMIT    = [20, 20, 20, 20] as const;

export interface AxisCalibration {
  steps_per_unit: number[];   // idx-aligned 0..3
  distance_limit: number[];
  speed_limit:    number[];
}

const DEFAULT_CAL: AxisCalibration = {
  steps_per_unit: [...DEFAULT_STEPS_PER_UNIT],
  distance_limit: [...DEFAULT_DISTANCE_LIMIT],
  speed_limit:    [...DEFAULT_SPEED_LIMIT],
};

function dictToArr(d: Record<string, number> | undefined, fallback: readonly number[]): number[] {
  const out = [...fallback];
  if (!d) return out;
  for (const k of Object.keys(d)) {
    const i = Number(k);
    if (Number.isInteger(i) && i >= 0 && i < out.length) out[i] = Number(d[k]);
  }
  return out;
}

export function useAxisCalibration() {
  const [cached, setCached] = usePersistentState<AxisCalibration>(CACHE_KEY, DEFAULT_CAL);
  const [cal, setCal] = useState<AxisCalibration>(cached);
  const lastPushed = useRef<string>('');

  useEffect(() => {
    let cancelled = false;
    fetch('/api/motor/calibration')
      .then((r) => r.json())
      .then((j) => {
        if (cancelled || !j?.success) return;
        const d = j.data;
        const fresh: AxisCalibration = {
          steps_per_unit: dictToArr(d.steps_per_unit, DEFAULT_STEPS_PER_UNIT),
          distance_limit: dictToArr(d.distance_limit, DEFAULT_DISTANCE_LIMIT),
          speed_limit:    dictToArr(d.speed_limit,    DEFAULT_SPEED_LIMIT),
        };
        setCal(fresh);
        setCached(fresh);
        lastPushed.current = JSON.stringify(fresh.steps_per_unit);
      })
      .catch(() => {
        // offline — keep localStorage cached value
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function setStepsPerUnit(axisIdx: number, value: number) {
    if (!Number.isFinite(value) || value <= 0) return;
    const next = { ...cal, steps_per_unit: [...cal.steps_per_unit] };
    next.steps_per_unit[axisIdx] = value;
    setCal(next);
    setCached(next);
    try {
      await fetch('/api/motor/calibration', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ axis: axisIdx, steps_per_unit: value }),
      });
    } catch {
      // backend unreachable — local cache still in effect
    }
  }

  return { cal, setStepsPerUnit };
}
