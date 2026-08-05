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
import { useToast } from '../components/ui/ToastSystem';
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
  const toast = useToast();
  const [psuId, setPsuIdRaw] = usePersistentState(PSU_KEY, PSU_DEFAULT_ID);
  const [override, setOverrideRaw] = usePersistentState(CS_OVERRIDE_KEY, 0);
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
    const prev = psu;
    const nextPsu = PSU_PRESETS.find((p) => p.id === next);
    setPsuIdRaw(next);
    if (next === lastPushedRef.current) return;
    lastPushedRef.current = next;
    if (nextPsu && nextPsu.id !== prev.id) {
      const newCap = computeEffectiveCsMax(nextPsu, override);
      const oldCap = computeEffectiveCsMax(prev, override);
      if (newCap < oldCap) {
        toast.warn(
          `PSU set to ${nextPsu.label}.\n` +
          `IRUN/IHOLD cap reduced ${oldCap} → ${newCap}. ` +
          `Existing driver settings above ${newCap} are auto-clamped.`,
          7000,
        );
      } else if (newCap > oldCap) {
        toast.info(`PSU set to ${nextPsu.label}. CS cap raised ${oldCap} → ${newCap}.`, 5000);
      }
    }
    systemApi.setPsu(next).catch(() => {
      toast.error(
        'Failed to sync PSU selection to backend. Local UI cap still applies, ' +
        'but the diagnostic register-write guard may use the previous value.'
      );
    });
  }

  function setOverride(next: number) {
    let val = Math.round(next);
    if (!Number.isFinite(val) || val < 0) val = 0;
    if (val > SAFETY_CS_MAX) {
      toast.warn(
        `Manual CS override ${val} clamped to hardware safety max ${SAFETY_CS_MAX}. ` +
        `Boards burned 2026-05-08 with CS=31.`
      );
      val = SAFETY_CS_MAX;
    }
    if (val !== override && val > 0 && val < psu.csCap) {
      toast.info(`Manual CS override ${val} is below PSU cap ${psu.csCap} — using ${val}.`);
    }
    setOverrideRaw(val);
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
