import { cn } from '../../lib/cn';

interface SkeletonLoaderProps {
  lines?: number;
  className?: string;
}

// gradient shimmer — backgroundImage/backgroundSize use CSS vars; cannot be expressed as Tailwind utility
const shimmerStyle = {
  backgroundImage: 'linear-gradient(90deg, var(--bg-surface-2) 25%, var(--bg-surface-3) 50%, var(--bg-surface-2) 75%)',
  backgroundSize: '200% 100%',
} as const;

export function SkeletonLoader({ lines = 3, className }: SkeletonLoaderProps) {
  return (
    <div className={cn('flex flex-col gap-3', className)}>
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className={cn(
            'h-4 rounded bg-surface-2 animate-skeleton',
            i === lines - 1 ? 'w-3/5' : 'w-full',
          )}
          style={shimmerStyle}
        />
      ))}
    </div>
  );
}
