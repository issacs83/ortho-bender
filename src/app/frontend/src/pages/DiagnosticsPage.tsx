/**
 * DiagnosticsPage.tsx — Motor driver test bench diagnostic UI.
 *
 * Sections: Driver Connection, SPI Test, Register Inspector (slide-out),
 * uPlot Oscilloscope (replaces Recharts StallGuardChart), Motor Jog,
 * Register Dump.
 *
 * IEC 62304 SW Class B — Diagnostics interface, no safety-critical logic here.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { diagApi, motorApi, wsApi, type SpiTestResultItem, type DiagDumpResult, type DriverProbeResult } from '../api/client';
import { RegisterInspector } from '../components/RegisterInspector';
import { Oscilloscope } from '../components/charts/Oscilloscope';
import { OscilloscopeBuffer } from '../components/charts/OscilloscopeBuffer';
import { OscilloscopeControls } from '../components/charts/OscilloscopeControls';
import { ChannelLegend } from '../components/domain/ChannelLegend';
import { useDiagWs } from '../hooks/useDiagWs';
import { Card, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { StatusBadge } from '../components/ui/StatusBadge';
import { RefreshCw } from 'lucide-react';

// --- Channel configuration -------------------------------------------------
const CHANNEL_KEYS = ['tmc260c_0', 'tmc260c_1', 'tmc5072_m0', 'tmc5072_m1'] as const;
const CHANNEL_LABELS = ['FEED', 'BEND', 'ROTATE', 'LIFT'];
const CHANNEL_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#a78bfa'];

interface ChannelState {
  label: string;
  color: string;
  visible: boolean;
  value?: number;
}

const DRIVERS = ['tmc260c_0', 'tmc260c_1', 'tmc5072'] as const;

// --- Component -------------------------------------------------------------

export function DiagnosticsPage() {
  // -- Oscilloscope state ---------------------------------------------------
  const bufferRef = useRef(new OscilloscopeBuffer(3600, CHANNEL_KEYS.length));
  const [windowSpan, setWindowSpan] = useState(10);
  const [yMode, setYMode] = useState<'auto' | 'manual'>('manual');
  const [paused, setPaused] = useState(false);
  const [liveValues, setLiveValues] = useState<Record<string, number>>({});
  const [channels, setChannels] = useState<ChannelState[]>(
    CHANNEL_KEYS.map((_, i) => ({
      label: CHANNEL_LABELS[i],
      color: CHANNEL_COLORS[i],
      visible: true,
    })),
  );

  const handleToggleChannel = useCallback((idx: number) => {
    setChannels(prev =>
      prev.map((ch, i) => (i === idx ? { ...ch, visible: !ch.visible } : ch)),
    );
  }, []);

  const handleClear = useCallback(() => {
    bufferRef.current.clear();
  }, []);

  const handleExportCsv = useCallback(() => {
    const now = performance.now() / 1000;
    const window = bufferRef.current.fillWindow(now, windowSpan);
    const xs = window[0];
    const header = ['time_s', ...CHANNEL_LABELS].join(',');
    const rows = Array.from(xs).map((t, i) =>
      [t, ...CHANNEL_KEYS.map((_, c) => window[c + 1][i])].join(','),
    );
    const csv = [header, ...rows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `stallguard_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [windowSpan]);

  // SG threshold
  const [sgThreshold, setSgThreshold] = useState<number | undefined>(undefined);

  // -- WebSocket feed -------------------------------------------------------
  useDiagWs({
    buffer: bufferRef.current,
    channelKeys: [...CHANNEL_KEYS],
    enabled: !paused,
  });

  // Track live values separately — a lightweight display-rate listener
  // decoupled from the buffer write path in useDiagWs.
  useEffect(() => {
    let active = true;
    let frameCount = 0;
    const ws = wsApi.motorDiag((evt) => {
      frameCount++;
      if (frameCount % 10 !== 0) return; // ~20 fps display
      if (!active) return;
      const vals: Record<string, number> = {};
      for (const [k, info] of Object.entries(evt.drivers)) {
        vals[k] = info.sg_result;
      }
      setLiveValues(vals);
      setChannels(prev =>
        prev.map((ch, i) => ({
          ...ch,
          value: vals[CHANNEL_KEYS[i]] ?? ch.value,
        })),
      );
    });
    return () => {
      active = false;
      ws.close();
    };
  }, []);

  // -- Backend info ---------------------------------------------------------
  const [backendInfo, setBackendInfo] = useState<string>('--');

  // -- Driver probe ---------------------------------------------------------
  const [probeResults, setProbeResults] = useState<DriverProbeResult[]>([]);
  const [probing, setProbing] = useState(false);

  useEffect(() => {
    diagApi.backend().then(info => {
      setBackendInfo(
        `${info.backend} | ${info.spi_speed_hz ? (info.spi_speed_hz / 1e6).toFixed(0) + ' MHz' : 'N/A'}`,
      );
    }).catch(() => setBackendInfo('error'));
    diagApi.probe().then(r => setProbeResults(r.drivers)).catch(() => {});
  }, []);

  async function handleProbe() {
    setProbing(true);
    try {
      const r = await diagApi.probe();
      setProbeResults(r.drivers);
    } catch { /* ignore */ }
    finally { setProbing(false); }
  }

  // -- SPI Test -------------------------------------------------------------
  const [spiResults, setSpiResults] = useState<SpiTestResultItem[] | null>(null);
  const [spiLoading, setSpiLoading] = useState(false);

  async function handleSpiTest() {
    setSpiLoading(true);
    try {
      const r = await diagApi.spiTest();
      setSpiResults(r.results);
    } catch { setSpiResults(null); }
    finally { setSpiLoading(false); }
  }

  // -- Register Dump --------------------------------------------------------
  const [dumpResult, setDumpResult] = useState<DiagDumpResult | null>(null);
  const [dumpLoading, setDumpLoading] = useState(false);

  async function handleDump(driver: string) {
    setDumpLoading(true);
    try {
      const r = await diagApi.dump(driver);
      setDumpResult(r);
    } catch { setDumpResult(null); }
    finally { setDumpLoading(false); }
  }

  // -- Register Inspector slide-out -----------------------------------------
  const [inspectorOpen, setInspectorOpen] = useState(false);

  // -- Motor Jog ------------------------------------------------------------
  const [jogAxis, setJogAxis] = useState(0);
  const [jogSpeed, setJogSpeed] = useState(10);
  const [jogStatus, setJogStatus] = useState('IDLE');

  async function handleJog(direction: 1 | -1) {
    try {
      const r = await motorApi.jog(jogAxis, direction, jogSpeed, 100);
      setJogStatus(r.state === 3 ? 'JOGGING' : 'IDLE');
    } catch { setJogStatus('ERROR'); }
  }

  async function handleJogStop() {
    try {
      await motorApi.stop();
      setJogStatus('IDLE');
    } catch { setJogStatus('ERROR'); }
  }

  // -- Stats (current / avg / peak) per channel -----------------------------
  const statsRef = useRef<{ sum: number; count: number; peak: number }[]>(
    CHANNEL_KEYS.map(() => ({ sum: 0, count: 0, peak: 0 })),
  );

  // Accumulate stats from liveValues
  useEffect(() => {
    CHANNEL_KEYS.forEach((key, i) => {
      const v = liveValues[key];
      if (v === undefined) return;
      const s = statsRef.current[i];
      s.sum += v;
      s.count++;
      if (v > s.peak) s.peak = v;
    });
  }, [liveValues]);

  const [statsSnapshot, setStatsSnapshot] = useState<{ avg: number; peak: number }[]>(
    CHANNEL_KEYS.map(() => ({ avg: 0, peak: 0 })),
  );

  // Refresh stats display at ~2 Hz
  useEffect(() => {
    const id = setInterval(() => {
      setStatsSnapshot(
        statsRef.current.map(s => ({
          avg: s.count > 0 ? Math.round(s.sum / s.count) : 0,
          peak: s.peak,
        })),
      );
    }, 500);
    return () => clearInterval(id);
  }, []);

  // -------------------------------------------------------------------------

  return (
    <div className="relative flex flex-col gap-3 p-3 max-w-[1100px] w-full box-border">
      {/* ── Top toolbar ─────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <h2 className="text-[18px] font-semibold text-text-primary m-0">Diagnostics</h2>
          <span className="text-[11px] text-text-tertiary">{backendInfo}</span>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Button variant="secondary" size="sm" onClick={handleSpiTest} loading={spiLoading}>
            Run SPI Test
          </Button>
          <Button
            variant={inspectorOpen ? 'primary' : 'secondary'}
            size="sm"
            onClick={() => setInspectorOpen(v => !v)}
          >
            Register Inspector
          </Button>
          {DRIVERS.map(d => (
            <Button key={d} variant="ghost" size="sm" onClick={() => handleDump(d)} disabled={dumpLoading}>
              Dump {d}
            </Button>
          ))}
        </div>
      </div>

      {/* ── SPI Test results (inline, compact) ──────────────────────────── */}
      {spiResults && (
        <Card className="py-2 px-3">
          <div className="flex items-center gap-4 flex-wrap">
            <span className="text-[11px] text-text-tertiary font-semibold uppercase tracking-wide">SPI Test</span>
            {spiResults.map(r => (
              <div key={r.driver} className="flex items-center gap-1.5">
                <StatusBadge variant={r.ok ? 'success' : 'error'} label={r.ok ? 'OK' : 'FAIL'} />
                <span className="text-[12px] text-text-secondary font-mono">{r.driver}</span>
                {r.latency_us && (
                  <span className="text-[11px] text-text-tertiary">{r.latency_us.toFixed(0)} µs</span>
                )}
                {!r.ok && r.error && (
                  <span className="text-[11px] text-danger">{r.error}</span>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* ── Driver Connection ────────────────────────────────────────────── */}
      <Card>
        <div className="flex items-center justify-between mb-2">
          <CardTitle>Driver Connection</CardTitle>
          <Button variant="ghost" size="sm" onClick={handleProbe} loading={probing}>
            <RefreshCw size={13} /> Re-Probe
          </Button>
        </div>
        <div className="flex gap-2 flex-wrap">
          {probeResults.length === 0 ? (
            <span className="text-[12px] text-text-tertiary">Probing drivers…</span>
          ) : probeResults.map(p => (
            <div
              key={p.driver}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-[12px]"
              style={{
                background: p.connected ? '#064e3b' : '#450a0a',
                borderColor: p.connected ? '#10b981' : '#ef4444',
              }}
            >
              <span
                className="w-2 h-2 rounded-full"
                style={{ background: p.connected ? '#10b981' : '#ef4444' }}
              />
              <span className="font-semibold text-text-primary">{p.driver}</span>
              <span style={{ color: p.connected ? '#6ee7b7' : '#fca5a5' }}>
                {p.connected ? p.chip : 'NOT FOUND'}
              </span>
            </div>
          ))}
        </div>
      </Card>

      {/* ── StallGuard2 Oscilloscope ─────────────────────────────────────── */}
      <Card noPadding>
        <div className="flex items-center justify-between px-4 pt-3 pb-2 border-b border-border">
          <CardTitle>StallGuard2 Live</CardTitle>
          <div className="flex items-center gap-2">
            <label className="text-[11px] text-text-tertiary">Threshold:</label>
            <input
              type="number"
              min={0}
              max={1023}
              value={sgThreshold ?? ''}
              onChange={e => setSgThreshold(e.target.value ? Number(e.target.value) : undefined)}
              placeholder="--"
              className="w-16 bg-surface-0 text-text-primary border border-border rounded px-2 py-1 font-mono text-[12px] focus:outline-none focus:border-accent"
            />
          </div>
        </div>

        {/* Chart */}
        <div className="px-2 pt-2">
          <Oscilloscope
            buffer={bufferRef.current}
            windowSpan={windowSpan}
            yMin={0}
            yMax={1023}
            yAuto={yMode === 'auto'}
            channels={channels}
            threshold={sgThreshold}
            paused={paused}
            height={480}
          />
        </div>

        {/* Controls bar */}
        <div className="px-4 py-2 border-t border-border">
          <OscilloscopeControls
            windowSpan={windowSpan}
            onWindowSpanChange={setWindowSpan}
            yMode={yMode}
            onYModeChange={setYMode}
            paused={paused}
            onTogglePause={() => setPaused(v => !v)}
            onClear={handleClear}
            onExportCsv={handleExportCsv}
          />
        </div>

        {/* Channel legend */}
        <div className="px-4 pb-3">
          <ChannelLegend channels={channels} onToggle={handleToggleChannel} />
        </div>
      </Card>

      {/* ── Stats Panel ──────────────────────────────────────────────────── */}
      <Card>
        <CardTitle className="mb-2">Channel Stats</CardTitle>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {channels.map((ch, i) => {
            const live = liveValues[CHANNEL_KEYS[i]];
            const { avg, peak } = statsSnapshot[i];
            return (
              <div key={ch.label} className="flex flex-col gap-1 p-2 bg-surface-0 rounded-md border border-border">
                <div className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-sm" style={{ background: ch.color }} />
                  <span className="text-[11px] font-semibold text-text-secondary">{ch.label}</span>
                </div>
                <div className="text-[20px] font-semibold numeric text-text-primary leading-tight">
                  {live ?? '—'}
                </div>
                <div className="flex gap-2 text-[10px] text-text-tertiary">
                  <span>avg {avg}</span>
                  <span>pk {peak}</span>
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      {/* ── Motor Jog ────────────────────────────────────────────────────── */}
      <Card>
        <div className="flex items-center justify-between mb-2">
          <CardTitle>Motor Jog</CardTitle>
          <StatusBadge
            variant={jogStatus === 'JOGGING' ? 'success' : jogStatus === 'ERROR' ? 'error' : 'neutral'}
            label={jogStatus}
          />
        </div>
        <div className="flex items-center gap-2 flex-wrap mb-3">
          <select
            value={jogAxis}
            onChange={e => setJogAxis(Number(e.target.value))}
            className="bg-surface-0 text-text-primary border border-border rounded px-2 py-1.5 text-[13px] focus:outline-none focus:border-accent"
          >
            <option value={0}>FEED</option>
            <option value={1}>BEND</option>
            <option value={2}>ROTATE</option>
            <option value={3}>LIFT</option>
          </select>
          <input
            type="number"
            value={jogSpeed}
            onChange={e => setJogSpeed(Number(e.target.value))}
            className="w-16 bg-surface-0 text-text-primary border border-border rounded px-2 py-1.5 font-mono text-[13px] focus:outline-none focus:border-accent"
          />
          <span className="text-[12px] text-text-tertiary">mm/s</span>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="md" className="flex-1" onClick={() => handleJog(-1)}>
            «  REV
          </Button>
          <Button variant="danger" size="md" className="flex-1" onClick={handleJogStop}>
            STOP
          </Button>
          <Button variant="secondary" size="md" className="flex-1" onClick={() => handleJog(1)}>
            FWD  »
          </Button>
        </div>
      </Card>

      {/* ── Register Dump ────────────────────────────────────────────────── */}
      {dumpResult && (
        <Card>
          <CardTitle className="mb-2">Register Dump — {dumpResult.driver}</CardTitle>
          <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-text-secondary">
            {Object.entries(dumpResult.registers).map(([name, val]) => (
              <span key={name}>
                <span className="text-text-tertiary">{name}</span>
                {' = '}
                <span className="text-text-primary">{val}</span>
              </span>
            ))}
          </div>
        </Card>
      )}

      {/* ── Slide-out Register Inspector ─────────────────────────────────── */}
      {/* Overlay */}
      {inspectorOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40"
          onClick={() => setInspectorOpen(false)}
        />
      )}
      {/* Panel */}
      <div
        className={[
          'fixed top-0 right-0 z-40 h-full w-[340px] bg-surface-1 border-l border-border shadow-xl',
          'transition-transform duration-200',
          inspectorOpen ? 'translate-x-0' : 'translate-x-full',
        ].join(' ')}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <span className="text-[14px] font-semibold text-text-primary">Register Inspector</span>
          <button
            onClick={() => setInspectorOpen(false)}
            className="text-text-tertiary hover:text-text-secondary text-[18px] leading-none"
          >
            ×
          </button>
        </div>
        <div className="p-4">
          <RegisterInspector />
        </div>
      </div>
    </div>
  );
}
