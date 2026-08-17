/**
 * DiagnosticsPage.tsx — Motor driver test bench diagnostic UI.
 *
 * Sections: SPI Test, Register Inspector, StallGuard2 Chart,
 * Motor Jog, Register Dump.
 */

import { useState, useEffect } from 'react';
import { diagApi, motorApi, type SpiTestResultItem, type DiagDumpResult, type DriverProbeResult } from '../api/client';
import { RegisterInspector } from '../components/RegisterInspector';
import { useDiagWs, railSuspect, hasFault } from '../hooks/useDiagWs';
import { AXIS_NAMES } from '../constants';
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

// cs 0/1/2 are LIFT/BEND/FEED. The old list dumped a TMC5072 that is
// not fitted on this bench and left FEED out entirely.
const DRIVERS = [
  { id: 'tmc260c_0', axis: 3 },
  { id: 'tmc260c_1', axis: 1 },
  { id: 'tmc260c_2', axis: 0 },
] as const;

const JOG_AXES = [
  { id: 0, name: 'FEED' },
  { id: 1, name: 'BEND' },
  { id: 3, name: 'LIFT' },
];

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
  const [jogDist, setJogDist] = useState(5);
  const [jogStatus, setJogStatus] = useState('IDLE');

  // SG threshold
  const [sgThreshold, setSgThreshold] = useState<number | undefined>(undefined);

  // Live chip flags
  const diag = useDiagWs();

  // Driver probe
  const [probeResults, setProbeResults] = useState<DriverProbeResult[]>([]);
  const [probing, setProbing] = useState(false);

  // Fetch backend info + driver probe on mount
  useEffect(() => {
    diagApi.backend().then(info => {
      const hz = info.spi_speed_hz;
      const speed = !hz ? 'N/A'
        : hz >= 1e6 ? `${(hz / 1e6).toFixed(1)} MHz`
        : `${(hz / 1e3).toFixed(0)} kHz`;
      setBackendInfo(`${info.backend} | ${speed}`);
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
      const r = await motorApi.jog(jogAxis, direction, jogSpeed, jogDist);
      setJogStatus(r.state === 3 ? 'JOGGING' : 'IDLE');
    } catch { setJogStatus('ERROR'); }
  }

  async function handleJogStop() {
    try {
      await motorApi.stop();
      setJogStatus('IDLE');
    } catch { setJogStatus('ERROR'); }
  }

  // LIFT is the only linear axis on this bench.
  const jogUnit = jogAxis === 3 ? 'mm' : '\u00B0';

  return (
    <div style={{ padding: 12, maxWidth: 900, width: '100%', boxSizing: 'border-box' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 20, color: '#f1f5f9' }}>Diagnostics</h2>
        <span style={{ fontSize: 12, color: '#64748b' }}>Backend: {backendInfo}</span>
      </div>

      {/* Row 0: Driver Connection Status */}
      <div style={{ ...CARD, marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <h3 style={{ margin: 0, fontSize: 14, color: '#94a3b8' }}>Driver Connection</h3>
          <button onClick={handleProbe} disabled={probing} style={{ ...BTN, background: '#334155', color: '#f1f5f9', fontSize: 11, padding: '4px 12px' }}>
            {probing ? 'Probing...' : 'Re-Probe'}
          </button>
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {probeResults.length === 0 ? (
            <span style={{ fontSize: 12, color: '#64748b' }}>Probing drivers...</span>
          ) : probeResults.map(p => (
            <div key={p.driver} style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '6px 12px', borderRadius: 6,
              background: p.connected ? '#064e3b' : '#450a0a',
              border: `1px solid ${p.connected ? '#10b981' : '#ef4444'}`,
            }}>
              <span style={{
                width: 8, height: 8, borderRadius: '50%',
                background: p.connected ? '#10b981' : '#ef4444',
              }} />
              <span style={{ fontSize: 12, color: '#f1f5f9', fontWeight: 600 }}>
                {p.driver}
              </span>
              <span style={{ fontSize: 11, color: p.connected ? '#6ee7b7' : '#fca5a5' }}>
                {p.connected ? p.chip : 'NOT FOUND'}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Live driver fault flags */}
      <div style={{ ...CARD, marginBottom: 12 }}>
        <h3 style={{ margin: '0 0 8px', fontSize: 14, color: '#94a3b8' }}>드라이버 폴트 (live)</h3>
        {railSuspect(diag) && (
          <div style={{ padding: '6px 10px', marginBottom: 8, borderRadius: 6, background: '#450a0a', border: '1px solid #ef4444', fontSize: 12, color: '#fecaca' }}>
            세 보드가 동일한 폴트 + STST 꺼짐 → 공유 12 V 레일을 먼저 측정하세요.
          </div>
        )}
        {!diag && <span style={{ fontSize: 12, color: '#64748b' }}>수신 대기…</span>}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {diag && DRIVERS.map(d => {
            const c = diag.drivers[d.id];
            if (!c) return null;
            const bad = hasFault(c);
            const flags = (['ot', 'otpw', 's2ga', 's2gb', 'ola', 'olb'] as const)
              .filter(k => c[k]).map(k => k.toUpperCase());
            return (
              <div key={d.id} style={{
                padding: '6px 12px', borderRadius: 6,
                background: bad ? '#450a0a' : '#064e3b',
                border: `1px solid ${bad ? '#ef4444' : '#10b981'}`,
                fontSize: 12, color: '#f1f5f9',
              }}>
                <b>{AXIS_NAMES[d.axis]}</b>{' '}
                <span style={{ color: bad ? '#fca5a5' : '#6ee7b7' }}>
                  {bad ? flags.join(' ') : 'OK'}
                </span>
                <span style={{ color: '#64748b', marginLeft: 8 }}>SG {c.sg_result}</span>
              </div>
            );
          })}
        </div>
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
            <label style={{ fontSize: 12, color: '#64748b' }}
                   title="차트에 기준선만 그립니다. 드라이버의 SGT 레지스터가 아닙니다 — SGT는 Motor Control → StallGuard 에서 설정하세요.">
              기준선(표시용):
            </label>
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
        <StallGuardChart threshold={sgThreshold} height={220} />
      </div>

      {/* Row 3: Motor Jog */}
      <div style={{ ...CARD, marginBottom: 12 }}>
        <h3 style={{ margin: '0 0 8px', fontSize: 14, color: '#94a3b8' }}>Motor Jog</h3>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
          <select
            value={jogAxis}
            onChange={e => setJogAxis(Number(e.target.value))}
            style={{ background: '#0f172a', color: '#f1f5f9', border: '1px solid #334155', borderRadius: 4, padding: '4px 8px' }}
          >
            {JOG_AXES.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <input
            type="number"
            value={jogSpeed}
            onChange={e => setJogSpeed(Number(e.target.value))}
            style={{ width: 60, background: '#0f172a', color: '#f1f5f9', border: '1px solid #334155', borderRadius: 4, padding: '4px 8px', fontFamily: 'monospace' }}
          />
          <span style={{ fontSize: 12, color: '#64748b' }}>{jogUnit}/s</span>
          <input
            type="number"
            value={jogDist}
            onChange={e => setJogDist(Number(e.target.value))}
            style={{ width: 60, background: '#0f172a', color: '#f1f5f9', border: '1px solid #334155', borderRadius: 4, padding: '4px 8px', fontFamily: 'monospace' }}
          />
          <span style={{ fontSize: 12, color: '#64748b' }}>{jogUnit}</span>
          <span style={{ fontSize: 12, color: '#94a3b8', marginLeft: 'auto' }}>Status: {jogStatus}</span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => handleJog(-1)} style={{ ...BTN, background: '#475569', color: '#fff', flex: 1 }}>&laquo; REV</button>
          <button onClick={handleJogStop} style={{ ...BTN, background: '#ef4444', color: '#fff', flex: 1 }}>STOP</button>
          <button onClick={() => handleJog(1)} style={{ ...BTN, background: '#475569', color: '#fff', flex: 1 }}>FWD &raquo;</button>
        </div>
      </div>

      {/* Row 4: Register Dump */}
      <div style={CARD}>
        <h3 style={{ margin: '0 0 8px', fontSize: 14, color: '#94a3b8' }}>Register Dump</h3>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          {DRIVERS.map(d => (
            <button
              key={d.id}
              onClick={() => handleDump(d.id)}
              disabled={dumpLoading}
              style={{ ...BTN, background: '#334155', color: '#f1f5f9', fontSize: 12 }}
            >
              Dump {AXIS_NAMES[d.axis]}
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
