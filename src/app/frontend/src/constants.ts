/**
 * DEPRECATED — Use CSS Variables from styles/tokens.css instead.
 * This file exists only as a migration shim. Remove after all pages are rewritten.
 */

export const BG_PRIMARY = '#0B0E13';
export const BG_PANEL = '#131821';
export const BG_SIDEBAR = '#131821';
export const BORDER = 'rgba(255,255,255,0.10)';
export const TEXT_PRIMARY = '#ECEFF4';
export const TEXT_SECONDARY = '#B4BCCC';
export const TEXT_MUTED = '#7A8499';
export const COLOR_SUCCESS = '#4ECB8B';
export const COLOR_SUCCESS_BG = 'rgba(78,203,139,0.12)';
export const COLOR_WARNING = '#F2B441';
export const COLOR_WARNING_BG = 'rgba(242,180,65,0.12)';
export const COLOR_ERROR = '#EF5B5B';
export const COLOR_ERROR_BG = 'rgba(239,91,91,0.12)';
export const COLOR_INFO = '#5DCFE0';
export const COLOR_INFO_BG = 'rgba(93,207,224,0.12)';

export const AXIS_COLORS = ['#5B8DEF', '#F2B441', '#C780E8', '#4ECB8B'] as const;
export const AXIS_NAMES = ['FEED', 'BEND', 'ROTATE', 'LIFT'] as const;
export const AXIS_UNITS = ['mm', '°', '°', '°'] as const;

export const MOTION_STATE_LABELS: Record<number, string> = {
  0: 'IDLE', 1: 'HOMING', 2: 'RUNNING', 3: 'JOGGING', 4: 'STOPPING', 5: 'FAULT', 6: 'ESTOP',
};

export interface WireMaterial {
  id: number; name: string; springback: string; heating: string; speed: string; maxAngle: number;
}
export const WIRE_MATERIALS: WireMaterial[] = [
  { id: 0, name: 'NiTi', springback: 'High (superelastic)', heating: 'Required (Af temp)', speed: '5 mm/s', maxAngle: 90 },
  { id: 1, name: 'SS304', springback: 'Moderate', heating: 'None', speed: '10 mm/s', maxAngle: 90 },
  { id: 2, name: 'Beta-Ti', springback: 'Low-moderate', heating: 'None', speed: '8 mm/s', maxAngle: 90 },
  { id: 3, name: 'CuNiTi', springback: 'High (temp-dep)', heating: 'Thermally activated', speed: '5 mm/s', maxAngle: 85 },
];
export const WIRE_DIAMETERS = [0.356, 0.406, 0.457, 0.508] as const;
export const HISTORY_LEN = 60;
