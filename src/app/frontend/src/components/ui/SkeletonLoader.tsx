/**
 * SkeletonLoader.tsx — Shimmer animation placeholder for loading states.
 */

import type { CSSProperties } from 'react';

interface SkeletonLoaderProps {
  lines?: number;
  height?: number;
  style?: CSSProperties;
}

export function SkeletonLoader({ lines = 4, height = 18, style }: SkeletonLoaderProps) {
  return (
    <>
      <style>{`
        @keyframes shimmer {
          0% { background-position: -400px 0; }
          100% { background-position: 400px 0; }
        }
      `}</style>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, ...style }}>
        {Array.from({ length: lines }).map((_, i) => (
          <div
            key={i}
            style={{
              height,
              borderRadius: 4,
              background: 'linear-gradient(90deg, #1e293b 25%, #263548 50%, #1e293b 75%)',
              backgroundSize: '800px 100%',
              animation: 'shimmer 1.5s infinite',
              width: i === lines - 1 ? '60%' : '100%',
            }}
          />
        ))}
      </div>
    </>
  );
}
