import { cn } from '../../lib/cn';

interface SkeletonLoaderProps {
  lines?: number;
  className?: string;
}

export function SkeletonLoader({ lines = 3, className }: SkeletonLoaderProps) {
  return (
    <div className={cn('flex flex-col gap-3', className)}>
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className="h-4 rounded bg-surface-2 animate-skeleton"
          style={{
            width: i === lines - 1 ? '60%' : '100%',
            backgroundImage: 'linear-gradient(90deg, var(--bg-surface-2) 25%, var(--bg-surface-3) 50%, var(--bg-surface-2) 75%)',
            backgroundSize: '200% 100%',
          }}
        />
      ))}
    </div>
  );
}
