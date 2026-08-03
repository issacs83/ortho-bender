import { useEffect, useRef } from 'react';
import { cn } from '../../lib/cn';
import { Button } from './Button';

interface ConfirmModalProps {
  title: string;
  description: string;
  confirmLabel?: string;
  confirmVariant?: 'primary' | 'danger';
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmModal({
  title, description, confirmLabel = 'Confirm', confirmVariant = 'primary',
  onConfirm, onCancel,
}: ConfirmModalProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    confirmRef.current?.focus();
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
      if (e.key === 'Enter') onConfirm();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onCancel, onConfirm]);

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60"
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
    >
      <div
        className="bg-surface-1 border border-border rounded-xl p-6 w-[90vw] max-w-[400px] shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-text-primary mb-2">{title}</h3>
        <p className="text-[13px] text-text-secondary mb-6 leading-relaxed">{description}</p>
        <div className="flex gap-3 justify-end">
          <Button variant="ghost" onClick={onCancel}>Cancel</Button>
          <button
            ref={confirmRef}
            onClick={onConfirm}
            className={cn(
              'inline-flex items-center justify-center gap-2 rounded-md font-semibold px-3.5 py-2 text-[13px]',
              'transition-[background,opacity] duration-fast',
              confirmVariant === 'danger'
                ? 'bg-danger text-white hover:opacity-90'
                : 'bg-accent text-white hover:opacity-90',
            )}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
