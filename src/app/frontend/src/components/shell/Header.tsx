import { Menu, Bell } from 'lucide-react';
import { cn } from '../../lib/cn';
import { MotionStatePill } from '../ui/MotionStatePill';
import { ConnectionIcon, type ConnStatus } from '../ui/ConnectionIcon';
import { EStopButton } from '../ui/EStopButton';

interface HeaderProps {
  onToggleSidebar: () => void;
  motionStateNum: number;
  bdStatus: ConnStatus;
  ipcStatus: ConnStatus;
  motorStatus: ConnStatus;
  motorModel: string | null;
  motorDetail: string;
  camStatus: ConnStatus;
  camModel: string | null;
  alarmCount: number;
  onEstopAction?: () => void;
}

export function Header({
  onToggleSidebar, motionStateNum,
  bdStatus, ipcStatus, motorStatus, motorModel, motorDetail,
  camStatus, camModel, alarmCount, onEstopAction,
}: HeaderProps) {
  return (
    <header className="h-14 bg-surface-1 border-b border-border fixed top-0 left-0 right-0 z-[200] flex items-center px-4 gap-3">
      {/* Left: hamburger + title */}
      <div className="flex items-center gap-2 shrink-0">
        <button onClick={onToggleSidebar} className="p-1 text-text-tertiary hover:text-text-secondary">
          <Menu size={20} />
        </button>
        <span className="text-[15px] font-bold text-text-primary tracking-wide whitespace-nowrap">
          Ortho-Bender
        </span>
      </div>

      {/* Center: 3 groups with separators */}
      <div className="flex-1 flex items-center justify-center gap-4 min-w-0 overflow-hidden">
        {/* Group 1: Motion state */}
        <MotionStatePill stateNum={motionStateNum} />

        {/* Separator */}
        <div className="w-px h-5 bg-border-subtle shrink-0" />

        {/* Group 2: Subsystems */}
        <div className="flex items-center gap-2 shrink overflow-hidden">
          <ConnectionIcon label="SYS" status={bdStatus} />
          <ConnectionIcon label="LINK" status={ipcStatus} />
          <ConnectionIcon label={motorModel ?? 'MTR'} status={motorStatus} detail={motorDetail} />
          <ConnectionIcon label="CAM" status={camStatus} detail={camModel ?? undefined} />
        </div>

        {/* Separator */}
        <div className="w-px h-5 bg-border-subtle shrink-0" />

        {/* Group 3: Alarms */}
        <div className="flex items-center gap-1.5 shrink-0">
          <Bell size={14} className="text-text-tertiary" />
          <span className={cn(
            'text-[11px] font-medium',
            alarmCount > 0 ? 'text-warning' : 'text-text-tertiary',
          )}>
            {alarmCount}
          </span>
        </div>
      </div>

      {/* Right: E-STOP */}
      <div className="shrink-0">
        <EStopButton stateNum={motionStateNum} onAction={onEstopAction} />
      </div>
    </header>
  );
}
