/**
 * Header.tsx — Fixed 56px top bar with motion state, connection status, and E-STOP.
 */

import { Menu } from 'lucide-react';
import { MotionStatePill } from '../ui/MotionStatePill';
import { ConnectionIcon, type ConnStatus } from '../ui/ConnectionIcon';
import { EStopButton } from '../ui/EStopButton';
import { BORDER, BG_PANEL, TEXT_PRIMARY, TEXT_MUTED } from '../../constants';

interface HeaderProps {
  onToggleSidebar: () => void;
  motionStateNum: number;
  bdStatus: ConnStatus;
  ipcStatus: ConnStatus;
  m7Status: ConnStatus;
  camStatus: ConnStatus;
  onEstopAction?: () => void;
}

export function Header({
  onToggleSidebar,
  motionStateNum,
  bdStatus,
  ipcStatus,
  m7Status,
  camStatus,
  onEstopAction,
}: HeaderProps) {
  return (
    <header style={{
      height: 56,
      background: BG_PANEL,
      borderBottom: `1px solid ${BORDER}`,
      display: 'flex',
      alignItems: 'center',
      padding: '0 16px',
      gap: 16,
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      zIndex: 200,
      flexShrink: 0,
    }}>
      {/* Left: hamburger + title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0, width: 200 }}>
        <button
          onClick={onToggleSidebar}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: TEXT_MUTED, padding: 4, display: 'flex' }}
        >
          <Menu size={20} />
        </button>
        <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_PRIMARY, letterSpacing: 0.5 }}>
          Ortho-Bender
        </span>
      </div>

      {/* Center: motion state + connection icons */}
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 20 }}>
        <MotionStatePill stateNum={motionStateNum} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <ConnectionIcon label="BD"  status={bdStatus} />
          <ConnectionIcon label="IPC" status={ipcStatus} />
          <ConnectionIcon label="M7"  status={m7Status} />
          <ConnectionIcon label="CAM" status={camStatus} />
        </div>
      </div>

      {/* Right: E-STOP */}
      <div style={{ flexShrink: 0 }}>
        <EStopButton stateNum={motionStateNum} onAction={onEstopAction} />
      </div>
    </header>
  );
}
