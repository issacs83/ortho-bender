/**
 * AlarmBanner.tsx — Alarm notification banner shown below the header.
 */

import { X } from 'lucide-react';
import { useState } from 'react';
import { COLOR_ERROR_BG, COLOR_WARNING_BG, COLOR_INFO_BG, COLOR_ERROR, COLOR_WARNING, COLOR_INFO } from '../../constants';
import type { SystemEvent } from '../../hooks/useSystemWs';

interface AlarmBannerProps {
  activeAlarms: number;
  events: SystemEvent[];
}

type Severity = 'ERROR' | 'WARNING' | 'INFO';

function getSeverity(type: string): Severity {
  if (type.includes('error') || type.includes('fault') || type.includes('estop')) return 'ERROR';
  if (type.includes('warn')) return 'WARNING';
  return 'INFO';
}

const SEVERITY_COLORS: Record<Severity, { bg: string; color: string }> = {
  ERROR:   { bg: COLOR_ERROR_BG,   color: COLOR_ERROR },
  WARNING: { bg: COLOR_WARNING_BG, color: COLOR_WARNING },
  INFO:    { bg: COLOR_INFO_BG,    color: COLOR_INFO },
};

export function AlarmBanner({ activeAlarms, events }: AlarmBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  if (activeAlarms === 0 || dismissed) return null;

  const latest = events[0];
  const severity: Severity = latest ? getSeverity(latest.type) : 'WARNING';
  const colors = SEVERITY_COLORS[severity];

  const isCritical = severity === 'ERROR';
  const extraText = activeAlarms > 1 ? ` (+${activeAlarms - 1} more)` : '';

  return (
    <>
      {isCritical && (
        <style>{`
          @keyframes alarm-blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
          }
        `}</style>
      )}
      <div style={{
        height: 40,
        background: colors.bg,
        borderBottom: `1px solid ${colors.color}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 16px',
        animation: isCritical ? 'alarm-blink 1s ease-in-out infinite' : undefined,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: colors.color }}>
          <span style={{ fontWeight: 700 }}>[{severity}]</span>
          <span>{latest?.message ?? 'Active alarm'}{extraText}</span>
        </div>
        <button
          onClick={() => setDismissed(true)}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: colors.color, padding: 4 }}
        >
          <X size={16} />
        </button>
      </div>
    </>
  );
}
