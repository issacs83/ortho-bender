/**
 * KpiStrip.tsx — Horizontal KPI summary strip for the Dashboard.
 * Shows CPU temp, uptime, bend cycles, and last run at a glance.
 */

import { Card } from '../ui/Card';
import { formatUptime } from '../../lib/format';

interface KpiStripProps {
  cpuTemp: number | null;
  uptimeS: number;
  bendCycles: number;
  lastRun: string | null;
}

export function KpiStrip({ cpuTemp, uptimeS, bendCycles, lastRun }: KpiStripProps) {
  const items = [
    { label: 'CPU TEMP',    value: cpuTemp != null ? cpuTemp.toFixed(1) : 'N/A', unit: cpuTemp != null ? '°C' : null },
    { label: 'UPTIME',      value: formatUptime(uptimeS),                         unit: null },
    { label: 'BEND CYCLES', value: String(bendCycles),                            unit: null },
    { label: 'LAST RUN',    value: lastRun ?? '—',                                unit: null },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {items.map((item) => (
        <Card key={item.label} className="px-4 py-3">
          <div className="text-[10px] text-text-tertiary uppercase tracking-widest mb-1">{item.label}</div>
          <div className="font-mono text-2xl font-bold text-text-primary">
            {item.value}
            {item.unit && <span className="text-[12px] text-text-tertiary ml-1">{item.unit}</span>}
          </div>
        </Card>
      ))}
    </div>
  );
}
