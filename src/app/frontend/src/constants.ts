/**
 * constants.ts — Design tokens and shared constants for Ortho-Bender dashboard.
 */

// ---------------------------------------------------------------------------
// Background
// ---------------------------------------------------------------------------
export const BG_PRIMARY = '#0f172a';
export const BG_PANEL = '#1e293b';
export const BG_SIDEBAR = '#1e293b';
export const BORDER = '#334155';

// ---------------------------------------------------------------------------
// Text
// ---------------------------------------------------------------------------
export const TEXT_PRIMARY = '#f1f5f9';
export const TEXT_SECONDARY = '#94a3b8';
export const TEXT_MUTED = '#64748b';

// ---------------------------------------------------------------------------
// Semantic colors
// ---------------------------------------------------------------------------
export const COLOR_SUCCESS = '#22c55e';
export const COLOR_SUCCESS_BG = '#065f46';
export const COLOR_WARNING = '#f59e0b';
export const COLOR_WARNING_BG = '#78350f';
export const COLOR_ERROR = '#ef4444';
export const COLOR_ERROR_BG = '#7f1d1d';
export const COLOR_INFO = '#3b82f6';
export const COLOR_INFO_BG = '#1e3a5f';

// ---------------------------------------------------------------------------
// Axis
// ---------------------------------------------------------------------------
export const AXIS_COLORS = ['#3b82f6', '#f59e0b', '#10b981', '#a78bfa'] as const;
export const AXIS_NAMES = ['FEED', 'BEND', 'ROTATE', 'LIFT'] as const;
export const AXIS_UNITS = ['mm', '°', '°', '°'] as const;

// ---------------------------------------------------------------------------
// Motor driver hardware-safety limits (TMC260C-PA)
// ---------------------------------------------------------------------------
// HARD GATE — these mirror SAFETY_CS_MAX / SAFETY_TOFF_MAX in
// server/services/tmc260c_driver.py. Two boards burned 2026-05-08 with
// CS=31 + TOFF=15. Frontend MUST NOT permit values above these.
export const SAFETY_CS_MAX   = 19;     // SGCSCONF current scale
export const SAFETY_TOFF_MAX = 8;      // CHOPCONF off-time
export const SAFETY_TOFF_MIN = 1;      // 0 disables the chopper entirely

// CHOPCONF=0x99548 verified safe by the bench. Any direct register write
// to CHOPCONF must keep TOFF<=SAFETY_TOFF_MAX; use the helper below.
export const CHOPCONF_FROZEN_DEFAULT = 0x99548;

// ---------------------------------------------------------------------------
// Power Supply presets
// ---------------------------------------------------------------------------
// Empirically derived from TMC260C-PA at sense=0.15Ω, VSENSE=1, VMot=12V:
// CS=19 ≈ 0.93A peak coil = ~0.66A RMS = ~7-8 W per coil under load.
// With three axes active concurrently we want headroom; the default 12V/5A
// supply (60W) leaves enough margin for CS=19. Lower-rated supplies must
// reduce the cap.
export interface PsuPreset { id: string; label: string; volts: number; amps: number; csCap: number; }
export const PSU_PRESETS: PsuPreset[] = [
  { id: '12v2.0a', label: '12 V / 2.0 A (24 W)', volts: 12, amps: 2.0, csCap: 12 },
  { id: '12v2.9a', label: '12 V / 2.9 A (35 W)', volts: 12, amps: 2.9, csCap: 14 },
  { id: '12v5.0a', label: '12 V / 5.0 A (60 W)', volts: 12, amps: 5.0, csCap: 17 },
  { id: '12v8.0a', label: '12 V / 8.0 A (96 W)', volts: 12, amps: 8.0, csCap: 19 },
  { id: '24v3.0a', label: '24 V / 3.0 A (72 W)', volts: 24, amps: 3.0, csCap: 19 },
];
// 12 V / 2.9 A (35 W) brick is the bench default — matches the actual
// hardware so IRUN/IHOLD caps come up correct on first load.
export const PSU_DEFAULT_ID = '12v2.9a';

// Per-axis soft travel limits used for the position progress bar.
// FEED  : wire feed length (mechanical spool / guide range, mm)
// BEND  : bending die rotation (full revolution, deg)
// ROTATE: wire rotation about its own axis (full revolution, deg)
// LIFT  : lift/lower mechanism stroke (mm)
// Bar shows: blue/normal until 80% of limit, amber 80–100%, red over.
export const AXIS_SOFT_LIMITS = [600, 360, 360, 100] as const; // FEED, BEND, ROTATE, LIFT

// ---------------------------------------------------------------------------
// Motion state
// ---------------------------------------------------------------------------
export const MOTION_STATE_LABELS: Record<number, string> = {
  0: 'IDLE',
  1: 'HOMING',
  2: 'RUNNING',
  3: 'JOGGING',
  4: 'STOPPING',
  5: 'FAULT',
  6: 'ESTOP',
};

// ---------------------------------------------------------------------------
// Wire materials
// ---------------------------------------------------------------------------
export interface WireMaterial {
  id: number;
  name: string;
  springback: string;
  heating: string;
  speed: string;
  maxAngle: number;
}

export const WIRE_MATERIALS: WireMaterial[] = [
  { id: 0, name: 'NiTi',     springback: 'High (superelastic)', heating: 'Required (Af temp)', speed: '5 mm/s',  maxAngle: 90 },
  { id: 1, name: 'SS304',    springback: 'Moderate',            heating: 'None',                speed: '10 mm/s', maxAngle: 90 },
  { id: 2, name: 'Beta-Ti',  springback: 'Low-moderate',        heating: 'None',                speed: '8 mm/s',  maxAngle: 90 },
  { id: 3, name: 'CuNiTi',   springback: 'High (temp-dep)',     heating: 'Thermally activated', speed: '5 mm/s',  maxAngle: 85 },
];

export const WIRE_DIAMETERS = [0.356, 0.406, 0.457, 0.508] as const;

export const HISTORY_LEN = 60;
