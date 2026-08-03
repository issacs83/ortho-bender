import { useState } from 'react';
import { cn } from '../../lib/cn';
import { motorApi } from '../../api/client';
import { ConfirmModal } from './ConfirmModal';

interface EStopButtonProps {
  stateNum: number;
  onAction?: () => void;
}

export function EStopButton({ stateNum, onAction }: EStopButtonProps) {
  const [showResetModal, setShowResetModal] = useState(false);
  const isEstop = stateNum === 6;
  const isFault = stateNum === 5;
  const isStopping = stateNum === 4;

  async function handleEstop() {
    try { await motorApi.estop(); onAction?.(); } catch { /* fire-and-forget */ }
  }

  async function handleReset() {
    try { await motorApi.reset(); onAction?.(); } catch { /* fire-and-forget */ }
  }

  return (
    <>
      <button
        disabled={isStopping}
        onClick={isEstop || isFault ? () => setShowResetModal(true) : handleEstop}
        className={cn(
          'min-w-[80px] h-10 rounded-md font-bold text-[12px] tracking-wider px-3.5 transition-all duration-fast',
          isEstop && 'bg-danger text-white border-2 border-danger animate-pulse-glow',
          isFault && 'bg-transparent text-warning border-[1.5px] border-warning/40',
          !isEstop && !isFault && 'bg-transparent text-danger border-[1.5px] border-danger/30 hover:border-danger/60',
          isStopping && 'opacity-50 cursor-not-allowed',
        )}
      >
        {isEstop ? 'RESET E-STOP' : isFault ? 'RESET FAULT' : 'E-STOP'}
      </button>

      {showResetModal && (
        <ConfirmModal
          title={isEstop ? 'Reset E-Stop' : 'Reset Fault'}
          description={isEstop
            ? 'Are you sure the machine is safe to resume? This will reset the emergency stop condition.'
            : 'This will clear the current fault condition and return to IDLE.'}
          confirmLabel="Reset"
          confirmVariant="danger"
          onConfirm={() => { setShowResetModal(false); handleReset(); }}
          onCancel={() => setShowResetModal(false)}
        />
      )}
    </>
  );
}
