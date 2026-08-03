/**
 * ChannelLegend.tsx — Toggle-able channel legend for the oscilloscope.
 *
 * Clicking a channel label toggles its visibility on the chart.
 */

import { cn } from '../../lib/cn';

interface Channel {
  label: string;
  color: string;
  visible: boolean;
  value?: number;
}

interface ChannelLegendProps {
  channels: Channel[];
  onToggle: (index: number) => void;
}

export function ChannelLegend({ channels, onToggle }: ChannelLegendProps) {
  return (
    <div className="flex items-center gap-3 flex-wrap">
      {channels.map((ch, i) => (
        <button
          key={ch.label}
          onClick={() => onToggle(i)}
          className={cn(
            'flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-medium transition-opacity',
            ch.visible ? 'opacity-100' : 'opacity-40',
          )}
        >
          <div className="w-2.5 h-2.5 rounded-sm" style={{ background: ch.color }} />
          <span className="text-text-secondary">{ch.label}</span>
          {ch.value != null && (
            <span className="numeric text-text-primary ml-1">{ch.value}</span>
          )}
        </button>
      ))}
    </div>
  );
}
