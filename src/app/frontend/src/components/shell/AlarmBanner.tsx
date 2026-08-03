import { AlertTriangle } from 'lucide-react';
import type { SystemEvent } from '../../hooks/useSystemWs';

interface AlarmBannerProps {
  activeAlarms: number;
  events: SystemEvent[];
}

export function AlarmBanner({ activeAlarms, events }: AlarmBannerProps) {
  if (activeAlarms === 0 && events.length === 0) return null;

  const latestError = events.find((e) => e.type.includes('error') || e.type.includes('fault'));
  if (!latestError && activeAlarms === 0) return null;

  return (
    <div className="bg-danger-soft border-b border-danger/20 px-4 py-2 flex items-center gap-2">
      <AlertTriangle size={14} className="text-danger shrink-0" />
      <span className="text-[12px] text-danger font-medium truncate">
        {latestError?.message ?? `${activeAlarms} active alarm${activeAlarms > 1 ? 's' : ''}`}
      </span>
    </div>
  );
}
