/**
 * AxisStatusRow.tsx — Single axis status row used in the Dashboard motor card.
 * Shows axis color indicator, name, position, velocity, and driver status badge.
 */

import { cn } from '../../lib/cn';
import { StatusBadge } from '../ui/StatusBadge';

const CHANNEL_BG_CLASSES = [
  'bg-ch-feed',
  'bg-ch-bend',
  'bg-ch-rotate',
  'bg-ch-lift',
] as const;

const CHANNEL_TEXT_CLASSES = [
  'text-ch-feed',
  'text-ch-bend',
  'text-ch-rotate',
  'text-ch-lift',
] as const;

const AXIS_NAMES = ['FEED', 'BEND', 'ROTATE', 'LIFT'] as const;
const AXIS_UNITS = ['mm', '°', '°', '°'] as const;

interface AxisStatusRowProps {
  axis: number;
  position?: number;
  velocity?: number;
  drvStatus?: number;
  connected: boolean;
}

export function AxisStatusRow({ axis, position, velocity, drvStatus, connected }: AxisStatusRowProps) {
  return (
    <div className={cn('flex items-center gap-2', !connected && 'opacity-50')}>
      <div className={cn('w-[3px] h-4 rounded-sm flex-shrink-0', CHANNEL_BG_CLASSES[axis])} />
      <span className={cn('text-[12px] font-semibold w-14 flex-shrink-0', CHANNEL_TEXT_CLASSES[axis])}>
        {AXIS_NAMES[axis]}
      </span>
      <span className="font-mono text-[12px] text-text-primary flex-1">
        {connected && position != null
          ? `${position.toFixed(3)} ${AXIS_UNITS[axis]}`
          : `— ${AXIS_UNITS[axis]}`}
      </span>
      <span className="font-mono text-[12px] text-text-primary w-16 text-right flex-shrink-0">
        {connected && velocity != null ? velocity.toFixed(2) : '—'}
      </span>
      <div className="w-20 text-right flex-shrink-0">
        {connected
          ? <StatusBadge variant={drvStatus === 0 ? 'success' : 'error'} label={drvStatus === 0 ? 'Normal' : 'Fault'} />
          : <StatusBadge variant="neutral" label="No Driver" />
        }
      </div>
    </div>
  );
}
