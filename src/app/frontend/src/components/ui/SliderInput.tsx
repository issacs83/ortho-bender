/**
 * SliderInput.tsx — Bidirectional slider + number input component.
 */

import type { CSSProperties } from 'react';
import { BORDER, BG_PRIMARY, TEXT_PRIMARY, TEXT_SECONDARY } from '../../constants';

interface SliderInputProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  /** Hover help text shown next to the label as ⓘ. Use plain text. */
  help?: string;
  onChange: (value: number) => void;
  style?: CSSProperties;
}

export function SliderInput({ label, value, min, max, step = 1, unit, help, onChange, style }: SliderInputProps) {
  return (
    <div style={{ ...style }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <label style={{ fontSize: 12, color: TEXT_SECONDARY, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          {label}
          {help && (
            <span
              title={help}
              aria-label={help}
              style={{
                cursor: 'help', fontSize: 10, color: TEXT_SECONDARY,
                border: `1px solid ${BORDER}`, borderRadius: '50%',
                width: 13, height: 13, display: 'inline-flex',
                alignItems: 'center', justifyContent: 'center', lineHeight: 1,
              }}
            >ⓘ</span>
          )}
        </label>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <input
            type="number"
            value={value}
            min={min}
            max={max}
            step={step}
            onChange={(e) => {
              const v = parseFloat(e.target.value);
              if (!isNaN(v)) onChange(Math.min(max, Math.max(min, v)));
            }}
            style={{
              width: 64,
              background: BG_PRIMARY,
              border: `1px solid ${BORDER}`,
              borderRadius: 4,
              color: TEXT_PRIMARY,
              padding: '2px 6px',
              fontSize: 12,
              textAlign: 'right',
            }}
          />
          {unit && <span style={{ fontSize: 11, color: TEXT_SECONDARY }}>{unit}</span>}
        </div>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ width: '100%', accentColor: '#3b82f6', cursor: 'pointer' }}
      />
    </div>
  );
}
