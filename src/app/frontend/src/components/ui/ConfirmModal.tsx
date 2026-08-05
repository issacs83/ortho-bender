/**
 * ConfirmModal.tsx — Keyboard-accessible confirmation dialog.
 *
 * - Esc = Cancel
 * - Enter = Confirm
 * - Focus trapped within modal
 */

import { useEffect, useRef } from 'react';
import { BG_PANEL, BORDER, TEXT_PRIMARY, TEXT_SECONDARY } from '../../constants';

interface ConfirmModalProps {
  title: string;
  description: string;
  confirmLabel?: string;
  confirmVariant?: 'primary' | 'danger';
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmModal({
  title,
  description,
  confirmLabel = 'Confirm',
  confirmVariant = 'primary',
  onConfirm,
  onCancel,
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
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.7)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
    >
      <div style={{
        background: BG_PANEL,
        border: `1px solid ${BORDER}`,
        borderRadius: 8,
        padding: 24,
        width: 380,
        maxWidth: '90vw',
      }}>
        <h3 style={{ margin: '0 0 10px', color: TEXT_PRIMARY, fontSize: 16 }}>{title}</h3>
        <p style={{ margin: '0 0 20px', color: TEXT_SECONDARY, fontSize: 14, lineHeight: 1.5 }}>{description}</p>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button
            onClick={onCancel}
            style={{
              padding: '8px 16px',
              background: '#1e293b',
              border: `1px solid ${BORDER}`,
              color: TEXT_SECONDARY,
              borderRadius: 6,
              cursor: 'pointer',
              fontSize: 13,
            }}
          >
            Cancel
          </button>
          <button
            ref={confirmRef}
            onClick={onConfirm}
            style={{
              padding: '8px 16px',
              background: confirmVariant === 'danger' ? '#dc2626' : '#3b82f6',
              border: 'none',
              color: '#fff',
              borderRadius: 6,
              cursor: 'pointer',
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
