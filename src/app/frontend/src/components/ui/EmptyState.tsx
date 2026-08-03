import { cn } from '../../lib/cn';
import type { ReactNode } from 'react';

interface EmptyStateProps {
  icon: ReactNode;
  message: string;
  hint?: string;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ icon, message, hint, action, className }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center py-8 text-center', className)}>
      <div className="text-text-disabled mb-3">{icon}</div>
      <p className="text-[13px] text-text-secondary mb-1">{message}</p>
      {hint && <p className="text-[11px] text-text-tertiary">{hint}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
