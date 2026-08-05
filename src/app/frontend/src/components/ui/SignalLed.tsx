/**
 * SignalLed.tsx — small coloured dot used as the 12V/EN/SG/DIR/STEP
 * indicator on each Axis Jog row. Same visual vocabulary as physical
 * driver-board LEDs:
 *
 *   12V  green when VMot is up
 *   EN   green when the chopper is ON for this axis (idle = grey)
 *   SG   red  when StallGuard reports a stall (grey when masked by EN=off,
 *        because a silenced chip always reads SG=1 and that is not a real stall)
 *   DIR  blue ▶ for +1, pink ◀ for -1, grey when never driven
 *   STEP amber pulse while this axis is the active PWM target
 */

import type { CSSProperties } from 'react';
import { TEXT_MUTED } from '../../constants';

type LedTone = 'off' | 'green' | 'red' | 'amber' | 'blue' | 'pink';

interface SignalLedProps {
  label: string;
  tone: LedTone;
  /** When true, the LED gently pulses to draw the eye (used for STEP). */
  blink?: boolean;
  /** Optional override text inside the dot (e.g. ▶ / ◀ for DIR). */
  glyph?: string;
  title?: string;
}

const TONE_BG: Record<LedTone, string> = {
  off:   '#1e293b',
  green: '#22c55e',
  red:   '#ef4444',
  amber: '#f59e0b',
  blue:  '#3b82f6',
  pink:  '#ec4899',
};

const TONE_GLOW: Record<LedTone, string> = {
  off:   'transparent',
  green: 'rgba(34,197,94,0.55)',
  red:   'rgba(239,68,68,0.55)',
  amber: 'rgba(245,158,11,0.55)',
  blue:  'rgba(59,130,246,0.55)',
  pink:  'rgba(236,72,153,0.55)',
};

export function SignalLed({ label, tone, blink, glyph, title }: SignalLedProps) {
  const bg = TONE_BG[tone];
  const glow = TONE_GLOW[tone];
  const dotStyle: CSSProperties = {
    width: 12,
    height: 12,
    borderRadius: '50%',
    background: bg,
    boxShadow: tone === 'off' ? 'inset 0 0 0 1px #334155' : `0 0 5px ${glow}`,
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 9,
    color: '#0f172a',
    fontWeight: 700,
    animation: blink && tone !== 'off' ? 'led-blink 0.6s ease-in-out infinite' : undefined,
    flexShrink: 0,
  };
  return (
    <span
      title={title ?? label}
      style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}
    >
      <span style={dotStyle}>{glyph ?? ''}</span>
      <span style={{ fontSize: 9, color: tone === 'off' ? TEXT_MUTED : '#cbd5e1', letterSpacing: 0.4 }}>
        {label}
      </span>
    </span>
  );
}

/* Inject the blink keyframes once. Cheaper than a styled-component, fine
   for the small number of LEDs we render. */
if (typeof document !== 'undefined' && !document.getElementById('led-blink-style')) {
  const tag = document.createElement('style');
  tag.id = 'led-blink-style';
  tag.textContent = `@keyframes led-blink { 0%,100% { opacity: 1 } 50% { opacity: 0.35 } }`;
  document.head.appendChild(tag);
}
