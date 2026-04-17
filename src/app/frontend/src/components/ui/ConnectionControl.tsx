import { useState } from 'react';
import { cn } from '../../lib/cn';
import { Button } from './Button';
import { StatusBadge } from './StatusBadge';
import { ConfirmModal } from './ConfirmModal';

interface DisconnectConfirm {
  title: string;
  description: string;
  confirmLabel?: string;
}

interface ConnectionControlProps {
  label: string;
  connected: boolean;
  busy?: boolean;
  disabled?: boolean;
  onConnect: () => Promise<unknown> | void;
  onDisconnect: () => Promise<unknown> | void;
  disconnectConfirm?: DisconnectConfirm;
  connectedLabel?: string;
  disconnectedLabel?: string;
  detail?: string;
  className?: string;
}

export function ConnectionControl({
  label, connected, busy = false, disabled = false,
  onConnect, onDisconnect, disconnectConfirm,
  connectedLabel = 'Connected', disconnectedLabel = 'Disconnected',
  detail, className,
}: ConnectionControlProps) {
  const [pending, setPending] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isBusy = pending || busy;

  const run = async (fn: () => Promise<unknown> | void) => {
    setPending(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  };

  const handleConnect = () => run(onConnect);

  const handleDisconnectClick = () => {
    if (disconnectConfirm) {
      setConfirmOpen(true);
    } else {
      run(onDisconnect);
    }
  };

  const handleConfirmDisconnect = () => {
    setConfirmOpen(false);
    run(onDisconnect);
  };

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <div className="flex items-center justify-between py-2">
        <div className="flex items-center gap-3">
          <div className={cn(
            'w-2 h-2 rounded-full',
            connected ? 'bg-success' : isBusy ? 'bg-warning animate-pulse' : 'bg-danger',
          )} />
          <div>
            <div className="text-[13px] text-text-primary font-medium">{label}</div>
            {detail && <div className="text-[11px] text-text-tertiary">{detail}</div>}
            <StatusBadge
              variant={connected ? 'success' : 'neutral'}
              label={connected ? connectedLabel : disconnectedLabel}
              className="mt-0.5"
            />
          </div>
        </div>
        <Button
          variant={connected ? 'ghost' : 'primary'}
          size="sm"
          loading={isBusy}
          disabled={disabled || isBusy}
          onClick={connected ? handleDisconnectClick : handleConnect}
        >
          {isBusy ? '...' : connected ? 'Disconnect' : 'Connect'}
        </Button>
      </div>

      {error && (
        <p className="text-[11px] text-danger pl-5">{error}</p>
      )}

      {confirmOpen && disconnectConfirm && (
        <ConfirmModal
          title={disconnectConfirm.title}
          description={disconnectConfirm.description}
          confirmLabel={disconnectConfirm.confirmLabel ?? 'Disconnect'}
          confirmVariant="danger"
          onConfirm={handleConfirmDisconnect}
          onCancel={() => setConfirmOpen(false)}
        />
      )}
    </div>
  );
}
