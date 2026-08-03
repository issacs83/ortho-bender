/**
 * domain-data.ts — Domain constants for the Ortho-Bender application.
 * Axis channel colors, names, units, wire materials, and shared chart settings.
 */

export const AXIS_COLORS = ['#5B8DEF', '#F2B441', '#C780E8', '#4ECB8B'] as const;
export const AXIS_NAMES = ['FEED', 'BEND', 'ROTATE', 'LIFT'] as const;
export const AXIS_UNITS = ['mm', '°', '°', '°'] as const;

export const HISTORY_LEN = 60;

export const MOTION_STATE_LABELS: Record<number, string> = {
  0: 'IDLE', 1: 'HOMING', 2: 'RUNNING', 3: 'JOGGING', 4: 'STOPPING', 5: 'FAULT', 6: 'ESTOP',
};

export interface WireMaterial {
  id: number; name: string; springback: string; heating: string; speed: string; maxAngle: number;
}

export const WIRE_MATERIALS: WireMaterial[] = [
  { id: 0, name: 'NiTi',    springback: 'High (superelastic)',  heating: 'Required (Af temp)',     speed: '5 mm/s',  maxAngle: 90 },
  { id: 1, name: 'SS304',   springback: 'Moderate',              heating: 'None',                   speed: '10 mm/s', maxAngle: 90 },
  { id: 2, name: 'Beta-Ti', springback: 'Low-moderate',          heating: 'None',                   speed: '8 mm/s',  maxAngle: 90 },
  { id: 3, name: 'CuNiTi',  springback: 'High (temp-dep)',       heating: 'Thermally activated',    speed: '5 mm/s',  maxAngle: 85 },
];

export const WIRE_DIAMETERS = [0.356, 0.406, 0.457, 0.508] as const;
