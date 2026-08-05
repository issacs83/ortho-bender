/**
 * useBoardRebootDetector.ts — Detects when the board has rebooted between
 * polls of /api/system/status and exposes a one-shot prompt that asks the
 * operator to run homing before any motion command.
 *
 * Detection logic
 * ---------------
 * Board uptime is monotonically increasing while the board is running.
 * If a freshly-fetched uptime_s is *less* than the previously-stored one,
 * the board has rebooted. We also clear the prompt after the operator
 * acknowledges or runs Home, and we reset the saved uptime baseline so
 * the next genuine reboot is caught again.
 *
 * After detection we wipe `motor.*` localStorage entries that cache motor
 * targets/positions — those values are no longer trustworthy because the
 * board's motor-state.json may itself have been overwritten or is now
 * inconsistent with the physical machine until homing completes.
 */

import { useEffect, useState } from 'react';
import { systemApi } from '../api/client';

const BASELINE_KEY = 'system.lastUptimeS';
const ACK_KEY      = 'system.rebootAckAt';

/** Drop every motor-related localStorage entry so the UI restarts clean. */
function clearMotorCache() {
  const prefix = 'ortho-bender:motor.';
  Object.keys(localStorage)
    .filter((k) => k.startsWith(prefix))
    .forEach((k) => localStorage.removeItem(k));
}

export function useBoardRebootDetector(pollMs = 4000) {
  const [rebootDetected, setRebootDetected] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function tick() {
      try {
        const s = await systemApi.status();
        if (cancelled) return;
        const prev = Number(localStorage.getItem(BASELINE_KEY) ?? '0');
        const now  = s.uptime_s ?? 0;
        // 5-second slack avoids false positives from minor clock drift.
        if (prev > 0 && now > 0 && now + 5 < prev) {
          clearMotorCache();
          setRebootDetected(true);
        }
        localStorage.setItem(BASELINE_KEY, String(now));
      } catch {
        // network blips are not reboots — keep last baseline
      }
    }

    tick();
    const id = setInterval(tick, pollMs);
    return () => { cancelled = true; clearInterval(id); };
  }, [pollMs]);

  function dismiss() {
    localStorage.setItem(ACK_KEY, new Date().toISOString());
    setRebootDetected(false);
  }

  return { rebootDetected, dismiss };
}
