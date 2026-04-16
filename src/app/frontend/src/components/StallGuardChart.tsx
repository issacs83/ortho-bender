/**
 * StallGuardChart.tsx — Real-time StallGuard2 line chart.
 *
 * Displays SG values for all connected TMC drivers overlaid on a
 * Recharts LineChart. Fed by /ws/motor/diag at 200 Hz, downsampled
 * to display resolution (~20 fps).
 */

import { useEffect, useRef, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ReferenceLine } from 'recharts';
import { wsApi, type DiagEvent } from '../api/client';

interface SgDataPoint {
  time: number;
  tmc260c_0?: number;
  tmc260c_1?: number;
  tmc5072_m0?: number;
  tmc5072_m1?: number;
}

interface StallGuardChartProps {
  threshold?: number;
  width?: number;
  height?: number;
}

const MAX_POINTS = 200;
const COLORS: Record<string, string> = {
  tmc260c_0: '#3b82f6',
  tmc260c_1: '#10b981',
  tmc5072_m0: '#f59e0b',
  tmc5072_m1: '#a78bfa',
};

export function StallGuardChart({ threshold, width = 600, height = 250 }: StallGuardChartProps) {
  const [data, setData] = useState<SgDataPoint[]>([]);
  const [live, setLive] = useState<Record<string, number>>({});
  const wsRef = useRef<WebSocket | null>(null);
  const startRef = useRef(Date.now());

  useEffect(() => {
    startRef.current = Date.now();
    let frameCount = 0;

    const ws = wsApi.motorDiag((evt: DiagEvent) => {
      frameCount++;
      // Downsample to ~20 fps (every 10th frame at 200 Hz)
      if (frameCount % 10 !== 0) return;

      const elapsed = (Date.now() - startRef.current) / 1000;
      const point: SgDataPoint = { time: Math.round(elapsed * 10) / 10 };
      const liveVals: Record<string, number> = {};

      for (const [drvId, info] of Object.entries(evt.drivers)) {
        (point as any)[drvId] = info.sg_result;
        liveVals[drvId] = info.sg_result;
      }

      setData(prev => {
        const next = [...prev, point];
        return next.length > MAX_POINTS ? next.slice(-MAX_POINTS) : next;
      });
      setLive(liveVals);
    });

    wsRef.current = ws;
    return () => ws.close();
  }, []);

  return (
    <div>
      <LineChart width={width} height={height} data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          dataKey="time"
          stroke="#94a3b8"
          label={{ value: 'Time (s)', position: 'insideBottom', offset: -5, fill: '#94a3b8' }}
        />
        <YAxis domain={[0, 1023]} stroke="#94a3b8" />
        <Tooltip
          contentStyle={{ background: '#1e293b', border: '1px solid #334155', color: '#f1f5f9' }}
        />
        <Legend />
        {threshold !== undefined && (
          <ReferenceLine y={threshold} stroke="#ef4444" strokeDasharray="5 5" label="Threshold" />
        )}
        <Line type="monotone" dataKey="tmc260c_0" stroke={COLORS.tmc260c_0} dot={false} strokeWidth={2} name="TMC260C #0 (FEED)" />
        <Line type="monotone" dataKey="tmc260c_1" stroke={COLORS.tmc260c_1} dot={false} strokeWidth={2} name="TMC260C #1 (BEND)" />
        <Line type="monotone" dataKey="tmc5072_m0" stroke={COLORS.tmc5072_m0} dot={false} strokeWidth={2} name="TMC5072 M0 (ROTATE)" />
        <Line type="monotone" dataKey="tmc5072_m1" stroke={COLORS.tmc5072_m1} dot={false} strokeWidth={2} name="TMC5072 M1 (LIFT)" />
      </LineChart>
      <div style={{ display: 'flex', gap: 16, fontSize: 12, color: '#94a3b8', marginTop: 4 }}>
        {Object.entries(live).map(([id, val]) => (
          <span key={id} style={{ color: COLORS[id as keyof typeof COLORS] || '#94a3b8' }}>
            {id}: {val}
          </span>
        ))}
        {threshold !== undefined && (
          <span style={{ color: '#ef4444' }}>Threshold: {threshold}</span>
        )}
      </div>
    </div>
  );
}
