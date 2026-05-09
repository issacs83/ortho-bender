/**
 * usePsuConfig.ts — Power-supply selection + derived safe current cap.
 *
 * The motor drivers can mechanically accept CS=0..31, but the SAFETY_CS_MAX
 * cap (19) is mandatory regardless of PSU. The PSU preset further lowers
 * the cap when the chosen supply cannot sustain three coils at full load.
 *
 * Final effective cap = min(SAFETY_CS_MAX, psuPreset.csCap, manualOverride).
 */

import { useEffect, useRef } from 'react';
import {
  PSU_PRESETS,
  PSU_DEFAULT_ID,
  SAFETY_CS_MAX,
  type PsuPreset,
} from '../constants';
import { systemApi } from '../api/client';
import { usePersistentState } from './usePersistentState';

const PSU_KEY        = 'settings.psuId';
const CS_OVERRIDE_KEY = 'settings.csManualOverride';   // 0 = no override

/** Map legacy id strings (older builds) onto the current preset list so a
 * stale localStorage entry doesn't silently fall through to the wrong PSU. */
const LEGACY_ID_MAP: Record<string, string> = {
  '12v2a':  '12v2.0a',
  '12v35w': '12v2.9a',
  '12v5a':  '12v5.0a',
  '12v8a':  '12v8.0a',
  '24v3a':  '24v3.0a',
};

export function usePsuConfig() {
  const [psuId, setPsuIdRaw] = usePersistentState(PSU_KEY, PSU_DEFAULT_ID);
  const [override, setOverride] = usePersistentState(CS_OVERRIDE_KEY, 0);
  const resolvedId = LEGACY_ID_MAP[psuId] ?? psuId;
  const psu =
    PSU_PRESETS.find((p) => p.id === resolvedId) ??
    PSU_PRESETS.find((p) => p.id === PSU_DEFAULT_ID) ??
    PSU_PRESETS[0];
  const effectiveCsMax = computeEffectiveCsMax(psu, override);

  // Sync with backend so the diag_service register-write guard sees the
  // same PSU cap as the UI. Pull on mount, push on change. Errors are
  // swallowed because the local cap still works without the server.
  const lastPushedRef = useRef<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    systemApi.getPsu()
      .then((r) => {
        if (cancelled) return;
        const remoteId = r.active?.id;
        if (remoteId && remoteId !== psu.id) setPsuIdRaw(remoteId);
        lastPushedRef.current = remoteId ?? psu.id;
      })
      .catch(() => {
        // network blip — keep using local value
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function setPsuId(next: string) {
    setPsuIdRaw(next);
    if (next === lastPushedRef.current) return;
    lastPushedRef.current = next;
    systemApi.setPsu(next).catch(() => {
      // local cap still applies; backend will catch up on next change
    });
  }

  return { psu, psuId: psu.id, setPsuId, override, setOverride, effectiveCsMax };
}

export function computeEffectiveCsMax(psu: PsuPreset, override: number): number {
  const fromOverride = override > 0 ? override : SAFETY_CS_MAX;
  return Math.min(SAFETY_CS_MAX, psu.csCap, fromOverride);
}

/** Headless: just the cap, for components that don't need to change PSU. */
export function useEffectiveCsMax(): number {
  return usePsuConfig().effectiveCsMax;
}
