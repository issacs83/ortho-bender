/**
 * ConnectionControl.tsx — Reusable connect/disconnect widget.
 *
 * Combines a StatusBadge with a single action button that flips between
 * Connect and Disconnect. Shown next to any feature that has a connection
 * lifecycle (Camera SDK, Motor DRV_ENN, WiFi, ...).
 *
 * Usage::
 *
 *   <ConnectionControl
 *     label="Camera"
 *     connected={status.power_state === 'on'}
 *     onConnect={() => cameraApi.connect()}
 *     onDisconnect={() => cameraApi.disconnect()}
 *     disconnectConfirm={{
 *       title: 'Disconnect camera?',
 *       description: 'Vimba X SDK will close and frame capture will stop.',
 *     }}
 *   />
 */

import { useState } from 'react';
import { BORDER, TEXT_SECONDARY } from '../../constants';
import { ConfirmModal } from './ConfirmModal';
import { StatusBadge } from './StatusBadge';

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
}

export function ConnectionControl({
  label,
  connected,
  busy = false,
  disabled = false,
  onConnect,
  onDisconnect,
  disconnectConfirm,
  connectedLabel = 'Connected',
  disconnectedLabel = 'Disconnected',
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
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 13, color: TEXT_SECONDARY, minWidth: 72 }}>{label}</span>
        <StatusBadge
          variant={connected ? 'success' : 'neutral'}
          label={connected ? connectedLabel : disconnectedLabel}
        />
        <button
          onClick={connected ? handleDisconnectClick : handleConnect}
          disabled={disabled || isBusy}
          style={{
            marginLeft: 'auto',
            padding: '6px 14px',
            background: connected ? '#dc2626' : '#3b82f6',
            border: `1px solid ${BORDER}`,
            color: '#fff',
            borderRadius: 6,
            fontSize: 12,
            fontWeight: 600,
            cursor: (disabled || isBusy) ? 'not-allowed' : 'pointer',
            opacity: (disabled || isBusy) ? 0.6 : 1,
            minWidth: 110,
          }}
        >
          {isBusy ? '...' : connected ? 'Disconnect' : 'Connect'}
        </button>
      </div>

      {error && (
        <div style={{ fontSize: 11, color: '#f87171', paddingLeft: 82 }}>
          {error}
        </div>
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
