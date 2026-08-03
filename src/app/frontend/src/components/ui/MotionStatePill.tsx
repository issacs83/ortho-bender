import { cn } from '../../lib/cn';

const MOTION_STATES: Record<number, { label: string; className: string }> = {
  0: { label: 'IDLE',     className: 'bg-success-soft text-success' },
  1: { label: 'HOMING',   className: 'bg-info-soft text-info' },
  2: { label: 'RUNNING',  className: 'bg-accent-soft text-accent' },
  3: { label: 'JOGGING',  className: 'bg-accent-soft text-accent' },
  4: { label: 'STOPPING', className: 'bg-warning-soft text-warning' },
  5: { label: 'FAULT',    className: 'bg-danger-soft text-danger' },
  6: { label: 'E-STOP',   className: 'bg-danger-soft text-danger' },
};

interface MotionStatePillProps {
  stateNum: number;
  className?: string;
}

export function MotionStatePill({ stateNum, className }: MotionStatePillProps) {
  const state = MOTION_STATES[stateNum] ?? { label: `STATE ${stateNum}`, className: 'bg-surface-2 text-text-tertiary' };
  return (
    <span className={cn(
      'inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold tracking-wide',
      state.className,
      className,
    )}>
      {state.label}
    </span>
  );
}
