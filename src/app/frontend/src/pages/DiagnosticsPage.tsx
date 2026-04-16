/**
 * DiagnosticsPage.tsx — Motor driver test bench diagnostic UI.
 *
 * Sections: SPI Test, Register Inspector, StallGuard2 Chart,
 * Motor Jog, Register Dump.
 */

import { useState, useEffect } from 'react';
import { diagApi, motorApi, type SpiTestResultItem, type DiagDumpResult } from '../api/client';
import { RegisterInspector } from '../components/RegisterInspector';
import { StallGuardChart } from '../components/StallGuardChart';

const CARD: React.CSSProperties = {
  background: '#1e293b',
  borderRadius: 8,
  padding: 16,
  border: '1px solid #334155',
};

const BTN: React.CSSProperties = {
  padding: '8px 16px',
  borderRadius: 6,
  border: 'none',
  cursor: 'pointer',
  fontWeight: 600,
  fontSize: 13,
};

const DRIVERS = ['tmc260c_0', 'tmc260c_1', 'tmc5072'] as const;

export function DiagnosticsPage() {
  // SPI Test state
  const [spiResults, setSpiResults] = useState<SpiTestResultItem[] | null>(null);
  const [spiLoading, setSpiLoading] = useState(false);

  // Backend info
  const [backendInfo, setBackendInfo] = useState<string>('--');

  // Dump state
  const [dumpResult, setDumpResult] = useState<DiagDumpResult | null>(null);
  const [dumpLoading, setDumpLoading] = useState(false);

  // Jog state
  const [jogAxis, setJogAxis] = useState(0);
  const [jogSpeed, setJogSpeed] = useState(10);
  const [jogStatus, setJogStatus] = useState('IDLE');

  // SG threshold
  const [sgThreshold, setSgThreshold] = useState<number | undefined>(undefined);

  // Fetch backend info on mount
  useEffect(() => {
    diagApi.backend().then(info => {
      setBackendInfo(`${info.backend} | ${info.spi_speed_hz ? (info.spi_speed_hz / 1e6).toFixed(0) + ' MHz' : 'N/A'}`);
    }).catch(() => setBackendInfo('error'));
  }, []);

  async function handleSpiTest() {
    setSpiLoading(true);
    try {
      const r = await diagApi.spiTest();
      setSpiResults(r.results);
    } catch { setSpiResults(null); }
    finally { setSpiLoading(false); }
  }

  async function handleDump(driver: string) {
    setDumpLoading(true);
    try {
      const r = await diagApi.dump(driver);
      setDumpResult(r);
    } catch { setDumpResult(null); }
    finally { setDumpLoading(false); }
  }

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

  return (
    <div style={{ padding: 20, maxWidth: 900 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 20, color: '#f1f5f9' }}>Diagnostics</h2>
        <span style={{ fontSize: 12, color: '#64748b' }}>Backend: {backendInfo}</span>
      </div>

      {/* Row 1: SPI Test + Register Inspector */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 12, marginBottom: 12 }}>
        {/* SPI Test */}
        <div style={CARD}>
          <h3 style={{ margin: '0 0 8px', fontSize: 14, color: '#94a3b8' }}>SPI Test</h3>
          <button onClick={handleSpiTest} disabled={spiLoading} style={{ ...BTN, background: '#3b82f6', color: '#fff' }}>
            {spiLoading ? 'Testing...' : 'Run SPI Test'}
          </button>
          {spiResults && (
            <div style={{ marginTop: 8, fontSize: 12 }}>
              {spiResults.map(r => (
                <div key={r.driver} style={{ color: r.ok ? '#10b981' : '#ef4444' }}>
                  {r.driver}: {r.ok ? 'OK' : `FAIL (${r.error})`}
                  {r.latency_us && ` — ${r.latency_us.toFixed(0)} us`}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Register Inspector */}
        <div style={CARD}>
          <h3 style={{ margin: '0 0 8px', fontSize: 14, color: '#94a3b8' }}>Register Inspector</h3>
          <RegisterInspector />
        </div>
      </div>

      {/* Row 2: StallGuard2 Chart */}
      <div style={{ ...CARD, marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <h3 style={{ margin: 0, fontSize: 14, color: '#94a3b8' }}>StallGuard2 Live</h3>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <label style={{ fontSize: 12, color: '#64748b' }}>Threshold:</label>
            <input
              type="number"
              min={0}
              max={1023}
              value={sgThreshold ?? ''}
              onChange={e => setSgThreshold(e.target.value ? Number(e.target.value) : undefined)}
              placeholder="--"
              style={{ width: 60, background: '#0f172a', color: '#f1f5f9', border: '1px solid #334155', borderRadius: 4, padding: '2px 6px', fontFamily: 'monospace', fontSize: 12 }}
            />
          </div>
        </div>
        <StallGuardChart threshold={sgThreshold} width={840} height={220} />
      </div>

      {/* Row 3: Motor Jog */}
      <div style={{ ...CARD, marginBottom: 12 }}>
        <h3 style={{ margin: '0 0 8px', fontSize: 14, color: '#94a3b8' }}>Motor Jog</h3>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <select
            value={jogAxis}
            onChange={e => setJogAxis(Number(e.target.value))}
            style={{ background: '#0f172a', color: '#f1f5f9', border: '1px solid #334155', borderRadius: 4, padding: '4px 8px' }}
          >
            <option value={0}>FEED</option>
            <option value={1}>BEND</option>
          </select>
          <input
            type="number"
            value={jogSpeed}
            onChange={e => setJogSpeed(Number(e.target.value))}
            style={{ width: 60, background: '#0f172a', color: '#f1f5f9', border: '1px solid #334155', borderRadius: 4, padding: '4px 8px', fontFamily: 'monospace' }}
          />
          <span style={{ fontSize: 12, color: '#64748b' }}>mm/s</span>
          <button onClick={() => handleJog(-1)} style={{ ...BTN, background: '#475569', color: '#fff' }}>&laquo; REV</button>
          <button onClick={handleJogStop} style={{ ...BTN, background: '#ef4444', color: '#fff' }}>STOP</button>
          <button onClick={() => handleJog(1)} style={{ ...BTN, background: '#475569', color: '#fff' }}>FWD &raquo;</button>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>Status: {jogStatus}</span>
        </div>
      </div>

      {/* Row 4: Register Dump */}
      <div style={CARD}>
        <h3 style={{ margin: '0 0 8px', fontSize: 14, color: '#94a3b8' }}>Register Dump</h3>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          {DRIVERS.map(d => (
            <button
              key={d}
              onClick={() => handleDump(d)}
              disabled={dumpLoading}
              style={{ ...BTN, background: '#334155', color: '#f1f5f9', fontSize: 12 }}
            >
              Dump {d}
            </button>
          ))}
        </div>
        {dumpResult && (
          <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#94a3b8' }}>
            <div style={{ marginBottom: 4, color: '#f1f5f9' }}>{dumpResult.driver}:</div>
            {Object.entries(dumpResult.registers).map(([name, val]) => (
              <div key={name} style={{ display: 'inline-block', marginRight: 16 }}>
                {name} = {val}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
