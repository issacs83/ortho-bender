import { cn } from '../../lib/cn';
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

export function SliderInput({ label, value, min, max, step = 1, unit, onChange, disabled, className, style }: SliderInputProps) {
  return (
    <div className={cn('flex flex-col gap-1', className)} style={style}>
      <div className="flex justify-between items-baseline">
        <label className="text-[11px] text-text-tertiary">{label}</label>
        <span className="numeric text-[13px] text-text-primary">
          {value}{unit && <span className="text-[11px] text-text-tertiary ml-1">{unit}</span>}
        </span>
      </div>
      <input
        type="range"
        min={min} max={max} step={step} value={value}
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
