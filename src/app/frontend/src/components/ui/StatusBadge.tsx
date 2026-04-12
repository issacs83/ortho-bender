/**
 * StatusBadge.tsx — Semantic status indicator pill.
 */

import type { CSSProperties } from 'react';
import {
  COLOR_SUCCESS, COLOR_SUCCESS_BG,
  COLOR_WARNING, COLOR_WARNING_BG,
  COLOR_ERROR, COLOR_ERROR_BG,
  COLOR_INFO, COLOR_INFO_BG,
  TEXT_MUTED, BORDER,
} from '../../constants';

export type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral';

interface StatusBadgeProps {
  variant: BadgeVariant;
  label: string;
  style?: CSSProperties;
}

const VARIANT_STYLES: Record<BadgeVariant, CSSProperties> = {
  success: { background: COLOR_SUCCESS_BG, color: COLOR_SUCCESS },
  warning: { background: COLOR_WARNING_BG, color: COLOR_WARNING },
  error:   { background: COLOR_ERROR_BG,   color: COLOR_ERROR },
  info:    { background: COLOR_INFO_BG,    color: COLOR_INFO },
  neutral: { background: '#1e293b',        color: TEXT_MUTED, border: `1px solid ${BORDER}` },
};

export function StatusBadge({ variant, label, style }: StatusBadgeProps) {
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      padding: '2px 8px',
      borderRadius: 4,
      fontSize: 11,
      fontWeight: 600,
      letterSpacing: 0.5,
      ...VARIANT_STYLES[variant],
      ...style,
    }}>
      {label}
    </span>
  );
}
