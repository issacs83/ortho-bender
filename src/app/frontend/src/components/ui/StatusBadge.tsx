import { cn } from '../../lib/cn';

export type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral';

interface StatusBadgeProps {
  variant: BadgeVariant;
  label: string;
  className?: string;
}

const variantClasses: Record<BadgeVariant, string> = {
  success: 'bg-success-soft text-success',
  warning: 'bg-warning-soft text-warning',
  error:   'bg-danger-soft text-danger',
  info:    'bg-info-soft text-info',
  neutral: 'bg-surface-2 text-text-tertiary border border-border',
};

export function StatusBadge({ variant, label, className }: StatusBadgeProps) {
  return (
    <span className={cn(
      'inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] font-semibold tracking-wide',
      variantClasses[variant],
      className,
    )}>
      {label}
    </span>
  );
}
