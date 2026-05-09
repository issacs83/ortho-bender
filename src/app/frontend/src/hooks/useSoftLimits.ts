/**
 * useSoftLimits.ts — Per-axis soft travel limits used by the position
 * progress bar and any client-side range checks. Values are stored in
 * localStorage so each browser/tablet keeps its own preference, and
 * cross-tab updates are picked up via the StorageEvent listener inside
 * usePersistentState.
 *
 * Index order matches AXIS_NAMES: [FEED, BEND, ROTATE, LIFT].
 */

import { AXIS_SOFT_LIMITS } from '../constants';
import { usePersistentState } from './usePersistentState';

export type SoftLimits = [number, number, number, number];

const STORAGE_KEY = 'settings.softLimits';

export function softLimitsDefault(): SoftLimits {
  return [...AXIS_SOFT_LIMITS] as SoftLimits;
}

export function useSoftLimits() {
  return usePersistentState<SoftLimits>(STORAGE_KEY, softLimitsDefault());
}
