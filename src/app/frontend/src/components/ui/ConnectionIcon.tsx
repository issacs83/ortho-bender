/**
 * ConnectionIcon.tsx — Connection status icon with label and hover tooltip.
 */

import { useState, type CSSProperties } from 'react';
import { Wifi, WifiOff, Loader, type LucideIcon } from 'lucide-react';
import { COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING, TEXT_MUTED } from '../../constants';

export type ConnStatus = 'connected' | 'connecting' | 'disconnected';

interface ConnectionIconProps {
  label: string;
  status: ConnStatus;
  style?: CSSProperties;
}

export function ConnectionIcon({ label, status, style }: ConnectionIconProps) {
  const [hovered, setHovered] = useState(false);

  const color =
    status === 'connected'    ? COLOR_SUCCESS :
    status === 'connecting'   ? COLOR_WARNING :
    COLOR_ERROR;

  const Icon: LucideIcon =
    status === 'connected'    ? Wifi :
    status === 'connecting'   ? Loader :
    WifiOff;

  return (
    <div
      style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', gap: 4, cursor: 'default', ...style }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <Icon
        size={16}
        color={color}
        style={{ animation: status === 'connecting' ? 'spin 1s linear infinite' : undefined }}
      />
      <span style={{ fontSize: 11, color, fontWeight: 600 }}>{label}</span>

      {hovered && (
        <div style={{
          position: 'absolute',
          bottom: '100%',
          left: '50%',
          transform: 'translateX(-50%)',
          marginBottom: 6,
          background: '#0f172a',
          border: '1px solid #334155',
          borderRadius: 4,
          padding: '4px 8px',
          fontSize: 11,
          color: '#f1f5f9',
          whiteSpace: 'nowrap',
          zIndex: 100,
          pointerEvents: 'none',
        }}>
          {label}: {status}
        </div>
      )}
    </div>
  );
}
