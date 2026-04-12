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
