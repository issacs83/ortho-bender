/**
 * Oscilloscope.tsx — uPlot-based oscilloscope chart for StallGuard diagnostics.
 *
 * Renders continuously from an OscilloscopeBuffer via requestAnimationFrame.
 * Zero-copy: uses Float64Array subarray views from the buffer.
 */

import { useEffect, useRef } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import type { OscilloscopeBuffer } from './OscilloscopeBuffer';

interface OscilloscopeProps {
  buffer: OscilloscopeBuffer;
  windowSpan: number;
  yMin?: number;
  yMax?: number;
  yAuto?: boolean;
  channels: { label: string; color: string; visible: boolean }[];
  threshold?: number;
  paused?: boolean;
  height?: number;
}

export function Oscilloscope({
  buffer, windowSpan, yMin = 0, yMax = 1023, yAuto = false,
  channels, threshold, paused = false, height = 480,
}: OscilloscopeProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const uplotRef = useRef<uPlot | null>(null);
  const rafRef = useRef<number>();
  const pausedRef = useRef(paused);

  pausedRef.current = paused;

  useEffect(() => {
    if (!containerRef.current) return;

    const series: uPlot.Series[] = [
      { label: 'Time' },
      ...channels.map((ch) => ({
        label: ch.label,
        stroke: ch.color,
        width: 1.5,
        points: { show: false },
        show: ch.visible,
      })),
    ];

    const opts: uPlot.Options = {
      width: containerRef.current.clientWidth,
      height,
      pxAlign: false,
      cursor: { drag: { x: false, y: false } },
      scales: {
        x: {
          time: false,
          range: () => {
            const now = performance.now() / 1000;
            return [now - windowSpan, now];
          },
        },
        y: yAuto ? {} : { range: [yMin, yMax] },
      },
      axes: [
        {
          stroke: '#7A8499',
          grid: { stroke: 'rgba(255,255,255,0.06)', width: 1 },
          ticks: { stroke: 'rgba(255,255,255,0.06)', width: 1 },
          font: '11px system-ui',
          values: (_, ticks) => ticks.map((t) => {
            const rel = t - performance.now() / 1000;
            return `${rel.toFixed(0)}s`;
          }),
        },
        {
          stroke: '#7A8499',
          grid: { stroke: 'rgba(255,255,255,0.06)', width: 1 },
          ticks: { stroke: 'rgba(255,255,255,0.06)', width: 1 },
          font: '11px system-ui',
        },
      ],
      series,
      plugins: threshold != null ? [thresholdPlugin(threshold)] : [],
    };

    const initData = buffer.fillWindow(performance.now() / 1000, windowSpan);
    uplotRef.current = new uPlot(opts, initData as uPlot.AlignedData, containerRef.current);

    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && uplotRef.current) uplotRef.current.setSize({ width: w, height });
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      uplotRef.current?.destroy();
      uplotRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  // Update channel visibility
  useEffect(() => {
    if (!uplotRef.current) return;
    channels.forEach((ch, i) => {
      uplotRef.current!.setSeries(i + 1, { show: ch.visible });
    });
  }, [channels]);

  // Animation loop
  useEffect(() => {
    const tick = () => {
      if (!pausedRef.current && uplotRef.current) {
        const now = performance.now() / 1000;
        const data = buffer.fillWindow(now, windowSpan);
        uplotRef.current.setData(data as uPlot.AlignedData, false);
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [windowSpan, buffer]);

  return <div ref={containerRef} className="w-full" />;
}

function thresholdPlugin(threshold: number): uPlot.Plugin {
  return {
    hooks: {
      draw: [(u: uPlot) => {
        const ctx = u.ctx;
        const y = u.valToPos(threshold, 'y', true);
        ctx.save();
        ctx.strokeStyle = 'var(--danger, #ef4444)';
        ctx.lineWidth = 1;
        ctx.setLineDash([5, 5]);
        ctx.beginPath();
        ctx.moveTo(u.bbox.left, y);
        ctx.lineTo(u.bbox.left + u.bbox.width, y);
        ctx.stroke();
        ctx.restore();
      }],
    },
  };
}
