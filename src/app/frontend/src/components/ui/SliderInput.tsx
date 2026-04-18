import { cn } from '../../lib/cn';
import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';

interface SliderInputProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onChange: (v: number) => void;
  disabled?: boolean;
  className?: string;
  /** @deprecated Use className for spacing. Kept for backward compatibility. */
  style?: CSSProperties;
}

function clamp(v: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, v));
}

function decimalsFromStep(step: number): number {
  if (!isFinite(step) || step <= 0) return 0;
  const s = String(step);
  const i = s.indexOf('.');
  return i === -1 ? 0 : s.length - i - 1;
}

export function SliderInput({
  label, value, min, max, step = 1, unit, onChange, disabled, className, style,
}: SliderInputProps) {
  const stepSafe = !isFinite(step) || step <= 0 ? 1 : step;
  const decimals = decimalsFromStep(stepSafe);

  const [draft, setDraft] = useState<string>(value.toFixed(decimals));
  useEffect(() => {
    setDraft(value.toFixed(decimals));
  }, [value, decimals]);

  const commit = (raw: string) => {
    const n = Number(raw);
    if (!isFinite(n)) {
      setDraft(value.toFixed(decimals));
      return;
    }
    const snapped = clamp(n, min, max);
    onChange(Number(snapped.toFixed(decimals)));
    setDraft(snapped.toFixed(decimals));
  };

  // Non-passive wheel handlers — bump value by step (Shift = ×10).
  const sliderRef = useRef<HTMLInputElement>(null);
  const numberRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (disabled) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      const dir = e.deltaY > 0 ? -1 : 1;
      const inc = stepSafe * (e.shiftKey ? 10 : 1) * dir;
      const next = clamp(value + inc, min, max);
      onChange(Number(next.toFixed(decimals)));
    };
    const s = sliderRef.current;
    const n = numberRef.current;
    s?.addEventListener('wheel', handler, { passive: false });
    n?.addEventListener('wheel', handler, { passive: false });
    return () => {
      s?.removeEventListener('wheel', handler);
      n?.removeEventListener('wheel', handler);
    };
  }, [value, stepSafe, min, max, disabled, decimals, onChange]);

  return (
    <div className={cn('flex flex-col gap-1', className)} style={style}>
      <div className="flex justify-between items-baseline">
        <label className="text-[11px] text-text-tertiary">{label}</label>
        <div className="flex items-baseline gap-1">
          <input
            ref={numberRef}
            type="number"
            min={min}
            max={max}
            step={stepSafe}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={(e) => commit(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                commit((e.target as HTMLInputElement).value);
                (e.target as HTMLInputElement).blur();
              } else if (e.key === 'Escape') {
                setDraft(value.toFixed(decimals));
                (e.target as HTMLInputElement).blur();
              }
            }}
            disabled={disabled}
            className="numeric text-[13px] text-text-primary bg-transparent border border-transparent rounded
                       px-1 py-0 text-right w-[88px] outline-none
                       hover:border-border focus:border-accent focus:bg-surface-3
                       disabled:opacity-50 disabled:cursor-not-allowed
                       [appearance:textfield]
                       [&::-webkit-inner-spin-button]:appearance-none
                       [&::-webkit-outer-spin-button]:appearance-none"
          />
          {unit && <span className="text-[11px] text-text-tertiary">{unit}</span>}
        </div>
      </div>
      <input
        ref={sliderRef}
        type="range"
        min={min} max={max} step={stepSafe} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        disabled={disabled}
        className="w-full h-1 bg-surface-3 rounded-full appearance-none cursor-pointer
          [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5
          [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:cursor-pointer
          disabled:opacity-50 disabled:cursor-not-allowed"
      />
    </div>
  );
}
