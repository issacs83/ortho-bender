import { cn } from '../../lib/cn';
import type { CSSProperties } from 'react';

export type ConnStatus = 'connected' | 'disconnected' | 'connecting';

interface ConnectionIconProps {
  label: string;
  status: ConnStatus;
  detail?: string;
  /** @deprecated Use className for spacing. Kept for backward compatibility. */
  style?: CSSProperties;
}

const dotClass: Record<ConnStatus, string> = {
  connected:    'bg-success',
  disconnected: 'bg-danger',
  connecting:   'bg-warning animate-pulse',
};

export function ConnectionIcon({ label, status, detail, style }: ConnectionIconProps) {
  return (
    <div className="flex items-center gap-1.5" title={detail ?? status} style={style}>
      <div className={cn('w-1.5 h-1.5 rounded-full', dotClass[status])} />
      <span className="text-[11px] text-text-secondary font-medium">{label}</span>
    </div>
  );
}
