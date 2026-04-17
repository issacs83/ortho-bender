import { cn } from '../../lib/cn';
import type { HTMLAttributes } from 'react';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  noPadding?: boolean;
}

export function Card({ className, noPadding, children, ...props }: CardProps) {
  return (
    <div
      className={cn(
        'bg-surface-1 border border-border rounded-lg inset-highlight',
        !noPadding && 'p-4',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardTitle({ className, children, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3 className={cn('text-[13px] font-semibold text-text-primary', className)} {...props}>
      {children}
    </h3>
  );
}
