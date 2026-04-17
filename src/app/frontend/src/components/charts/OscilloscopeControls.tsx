/**
 * OscilloscopeControls.tsx — Toolbar for the oscilloscope: window span, Y-scale, pause/clear/export.
 */

import { Pause, Play, Trash2, Download } from 'lucide-react';
import { Button } from '../ui/Button';
import { cn } from '../../lib/cn';

interface OscilloscopeControlsProps {
  windowSpan: number;
  onWindowSpanChange: (s: number) => void;
  yMode: 'auto' | 'manual';
  onYModeChange: (m: 'auto' | 'manual') => void;
  paused: boolean;
  onTogglePause: () => void;
  onClear: () => void;
  onExportCsv?: () => void;
  onExportPng?: () => void;
}

const WINDOW_OPTIONS = [5, 10, 30, 60, 300];

export function OscilloscopeControls({
  windowSpan, onWindowSpanChange, yMode, onYModeChange,
  paused, onTogglePause, onClear, onExportCsv,
}: OscilloscopeControlsProps) {
  return (
    <div className="flex items-center gap-3 flex-wrap">
      {/* Window span */}
      <div className="flex items-center gap-1">
        <span className="text-[11px] text-text-tertiary mr-1">Window</span>
        {WINDOW_OPTIONS.map((s) => (
          <button
            key={s}
            onClick={() => onWindowSpanChange(s)}
            className={cn(
              'px-2 py-1 rounded text-[11px] font-medium transition-colors duration-fast',
              windowSpan === s
                ? 'bg-accent-soft text-accent'
                : 'text-text-tertiary hover:text-text-secondary hover:bg-surface-2',
            )}
          >
            {s < 60 ? `${s}s` : `${s / 60}m`}
          </button>
        ))}
      </div>

      {/* Y-scale */}
      <div className="flex items-center gap-1">
        <span className="text-[11px] text-text-tertiary mr-1">Y-Scale</span>
        {(['auto', 'manual'] as const).map((m) => (
          <button
            key={m}
            onClick={() => onYModeChange(m)}
            className={cn(
              'px-2 py-1 rounded text-[11px] font-medium capitalize transition-colors duration-fast',
              yMode === m
                ? 'bg-accent-soft text-accent'
                : 'text-text-tertiary hover:text-text-secondary hover:bg-surface-2',
            )}
          >
            {m}
          </button>
        ))}
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Actions */}
      <Button variant="ghost" size="sm" onClick={onTogglePause}>
        {paused ? <Play size={14} /> : <Pause size={14} />}
        {paused ? 'Resume' : 'Pause'}
      </Button>
      <Button variant="ghost" size="sm" onClick={onClear}>
        <Trash2 size={14} /> Clear
      </Button>
      {onExportCsv && (
        <Button variant="ghost" size="sm" onClick={onExportCsv}>
          <Download size={14} /> CSV
        </Button>
      )}
    </div>
  );
}
