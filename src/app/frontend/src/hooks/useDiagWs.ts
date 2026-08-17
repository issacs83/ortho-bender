/**
 * useDiagWs.ts — live per-chip driver status from /ws/motor/diag.
 *
 * The backend has broadcast the real fault flags all along; nothing
 * subscribed to them, so a faulted bench looked healthy on screen.
 */

import { useEffect, useState } from 'react';
import { wsApi, type DiagEvent } from '../api/client';

/** Driver id -> bench axis. cs 0/1/2 are LIFT/BEND/FEED. */
export const DRIVER_AXIS: Record<string, number> = {
  tmc260c_0: 3,   // LIFT
  tmc260c_1: 1,   // BEND
  tmc260c_2: 0,   // FEED
};

export type DriverFlags = DiagEvent['drivers'][string];

export function useDiagWs() {
  const [diag, setDiag] = useState<DiagEvent | null>(null);

  useEffect(() => {
    const ws = wsApi.motorDiag(setDiag);
    return () => ws.close();
  }, []);

  return diag;
}

/**
 * Three boards share one supply rail, so a dead rail makes all of them
 * report the same fault while none reports standstill. Real per-axis
 * faults never agree to the bit.
 */
export function railSuspect(diag: DiagEvent | null): boolean {
  if (!diag) return false;
  const chips = Object.entries(diag.drivers)
    .filter(([id, v]) => v && id in DRIVER_AXIS)
    .map(([, v]) => v as DriverFlags);
  if (chips.length < 2) return false;
  const key = (c: DriverFlags) =>
    `${c.ot}${c.otpw}${c.s2ga}${c.s2gb}${c.ola}${c.olb}${c.stst}${c.sg_result}`;
  if (new Set(chips.map(key)).size !== 1) return false;
  const c = chips[0];
  return (c.s2ga || c.s2gb || c.ola || c.olb) && !c.stst;
}

export function hasFault(c: DriverFlags | undefined): boolean {
  return !!c && (c.ot || c.s2ga || c.s2gb || c.ola || c.olb);
}
