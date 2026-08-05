/**
 * EStopButton.tsx — Emergency stop button. Always enabled.
 *
 * - Normal state: "E-STOP" → calls motorApi.estop()
 * - ESTOP state (stateNum === 6): "RESET E-STOP" → ConfirmModal then motorApi.reset()
 */

import { useState } from 'react';
import { motorApi } from '../../api/client';
import { ConfirmModal } from './ConfirmModal';

interface EStopButtonProps {
  stateNum: number;
  onAction?: () => void;
}

export function EStopButton({ stateNum, onAction }: EStopButtonProps) {
  const [showResetModal, setShowResetModal] = useState(false);
  const isEstop = stateNum === 6;

  async function handleEstop() {
    try {
      await motorApi.estop();
      onAction?.();
    } catch {
      // fire-and-forget
    }
  }

  async function handleReset() {
    try {
      await motorApi.reset();
      onAction?.();
    } catch {
      // fire-and-forget
    }
  }

  return (
    <>
      <button
        disabled={false}
        onClick={isEstop ? () => setShowResetModal(true) : handleEstop}
        style={{
          minWidth: 80,
          height: 40,
          background: isEstop ? '#991b1b' : '#dc2626',
          color: '#fff',
          border: isEstop ? '2px solid #fca5a5' : '2px solid #ef4444',
          borderRadius: 6,
          fontWeight: 700,
          fontSize: 12,
          letterSpacing: 1,
          cursor: 'pointer',
          padding: '0 14px',
        }}
      >
        {isEstop ? 'RESET E-STOP' : 'E-STOP'}
      </button>

      {showResetModal && (
        <ConfirmModal
          title="Reset E-Stop"
          description="Are you sure the machine is safe to resume? This will reset the emergency stop condition."
          confirmLabel="Reset"
          confirmVariant="danger"
          onConfirm={() => { setShowResetModal(false); handleReset(); }}
          onCancel={() => setShowResetModal(false)}
        />
      )}
    </>
  );
}
