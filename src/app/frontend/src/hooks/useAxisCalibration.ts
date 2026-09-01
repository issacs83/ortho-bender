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
// 실측/현행 기본값 (2026-09-02): FEED 1/32 마이크로스텝 127.324 steps/mm,
// BEND 리밋 디스크 실측 23.0167 steps/deg. 오프라인 폴백일 뿐, 항상 서버가
// 진실이다. (예전 25.4648 은 #48 이전의 2.5:1 감속 누락 값이었다.)
export const DEFAULT_STEPS_PER_UNIT = [127.324, 23.0167, 200, 200] as const;
export const DEFAULT_DISTANCE_LIMIT = [200, 360, 360, 240] as const;
export const DEFAULT_SPEED_LIMIT    = [62.8, 347.6, 40, 40] as const;

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

  // 서버에서 현재 캘리브레이션을 다시 읽는다. 분주비 변경처럼
  // steps_per_unit/speed_limit 이 런타임에 바뀌는 조작 뒤에 반드시 불러야
  // 한다 — 안 부르면 입력칸의 최대값(axisMaxSpeed)이 페이지 로드 시점
  // 값으로 박제되어, 상한이 넓어졌는데도 UI 가 낮은 값 이상을 거부한다
  // (실사례: 1/256 에서 로드 → 1/16 전환 후에도 Speed 입력이 ~7.9 에 갇힘).
  async function refresh(): Promise<void> {
    try {
      const j = await (await fetch('/api/motor/calibration')).json();
      if (!j?.success) return;
      const d = j.data;
      const fresh: AxisCalibration = {
        steps_per_unit: dictToArr(d.steps_per_unit, DEFAULT_STEPS_PER_UNIT),
        distance_limit: dictToArr(d.distance_limit, DEFAULT_DISTANCE_LIMIT),
        speed_limit:    dictToArr(d.speed_limit,    DEFAULT_SPEED_LIMIT),
      };
      setCal(fresh);
      setCached(fresh);
      lastPushed.current = JSON.stringify(fresh.steps_per_unit);
    } catch {
      // offline — localStorage 캐시 유지
    }
  }

  useEffect(() => {
    refresh();
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

  return { cal, setStepsPerUnit, refresh };
}
