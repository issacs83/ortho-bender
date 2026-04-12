/**
 * MotionStatePill.tsx — Motion state indicator with blink for ESTOP.
 *
 * State mapping:
 *   0=IDLE 1=HOMING 2=RUNNING 3=JOGGING 4=STOPPING 5=FAULT 6=ESTOP
 */

import { type CSSProperties } from 'react';
import { MOTION_STATE_LABELS } from '../../constants';

interface MotionStatePillProps {
  stateNum: number;
  style?: CSSProperties;
}

type PillStyle = { bg: string; color: string; blink?: boolean };

const STATE_STYLES: Record<number, PillStyle> = {
  0: { bg: '#065f46', color: '#6ee7b7' },       // IDLE — green
  1: { bg: '#1e3a5f', color: '#93c5fd' },       // HOMING — blue
  2: { bg: '#1e3a5f', color: '#3b82f6' },       // RUNNING — bright blue
  3: { bg: '#78350f', color: '#fcd34d' },       // JOGGING — amber
  4: { bg: '#78350f', color: '#f59e0b' },       // STOPPING — amber
  5: { bg: '#7f1d1d', color: '#fca5a5' },       // FAULT — red
  6: { bg: '#7f1d1d', color: '#ef4444', blink: true }, // ESTOP — red blink
};

export function MotionStatePill({ stateNum, style }: MotionStatePillProps) {
  const s = STATE_STYLES[stateNum] ?? { bg: '#1e293b', color: '#94a3b8' };
  const label = MOTION_STATE_LABELS[stateNum] ?? 'UNKNOWN';

  return (
    <>
      {s.blink && (
        <style>{`
          @keyframes estop-blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
          }
        `}</style>
      )}
      <span style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '4px 12px',
        borderRadius: 20,
        fontSize: 12,
        fontWeight: 700,
        letterSpacing: 1,
        background: s.bg,
        color: s.color,
        animation: s.blink ? 'estop-blink 0.8s ease-in-out infinite' : undefined,
        ...style,
      }}>
        <span style={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          background: s.color,
          display: 'inline-block',
          flexShrink: 0,
        }} />
        {label}
      </span>
    </>
  );
}
