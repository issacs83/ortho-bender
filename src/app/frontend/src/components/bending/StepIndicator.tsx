/**
 * StepIndicator.tsx — 4-step progress indicator for the bending wizard.
 */

import { Check } from 'lucide-react';

const COLOR_INFO    = 'var(--info)';
const TEXT_PRIMARY  = 'var(--text-primary)';
const TEXT_MUTED    = 'var(--text-tertiary)';

const STEPS = ['Material & Wire', 'B-code Editor', 'Execute & Monitor', 'Result & Inspect'];

interface StepIndicatorProps {
  currentStep: number;
}

export function StepIndicator({ currentStep }: StepIndicatorProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', marginBottom: 24 }}>
      {STEPS.map((label, i) => {
        const isDone = i < currentStep;
        const isActive = i === currentStep;
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center', flex: i < STEPS.length - 1 ? 1 : undefined }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
              <div style={{
                width: 32,
                height: 32,
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: isDone ? COLOR_INFO : isActive ? '#1e3a5f' : '#1e293b',
                border: `2px solid ${isDone ? COLOR_INFO : isActive ? COLOR_INFO : '#334155'}`,
                color: isDone || isActive ? '#fff' : TEXT_MUTED,
                fontSize: 12,
                fontWeight: 700,
                flexShrink: 0,
              }}>
                {isDone ? <Check size={14} /> : i + 1}
              </div>
              <span style={{ fontSize: 11, color: isActive ? TEXT_PRIMARY : TEXT_MUTED, whiteSpace: 'nowrap', fontWeight: isActive ? 600 : 400 }}>
                {label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div style={{ flex: 1, height: 2, background: i < currentStep ? COLOR_INFO : '#334155', margin: '0 8px', marginBottom: 20 }} />
            )}
          </div>
        );
      })}
    </div>
  );
}
