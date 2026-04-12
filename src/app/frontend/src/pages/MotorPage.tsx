/**
 * MotorPage.tsx — Motor control with 4 sub-tabs: Position, Driver Config, StallGuard, Diagnostics.
 */

import { useEffect, useRef, useState } from 'react';
import { motorApi, type MotorStatus, type AxisStatus } from '../api/client';
import { ConfirmModal } from '../components/ui/ConfirmModal';
import { ConnectionControl } from '../components/ui/ConnectionControl';
import { SliderInput } from '../components/ui/SliderInput';
import { StatusBadge } from '../components/ui/StatusBadge';
import { useMotorWs } from '../hooks/useMotorWs';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { AXIS_COLORS, AXIS_NAMES, AXIS_UNITS, BG_PANEL, BG_PRIMARY, BORDER, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, HISTORY_LEN } from '../constants';

type MotorSubTab = 'position' | 'driver' | 'stallguard' | 'diagnostics';

const SUB_TABS: { id: MotorSubTab; label: string }[] = [
  { id: 'position',    label: 'Position Control' },
  { id: 'driver',      label: 'Driver Config' },
  { id: 'stallguard',  label: 'StallGuard' },
  { id: 'diagnostics', label: 'Diagnostics' },
];

interface ChartPoint { t: number; [k: string]: number; }

// ---------------------------------------------------------------------------
// DRV_STATUS bit definitions
// ---------------------------------------------------------------------------
const DRV_BITS = [
  { bit: 0,  name: 'OT',   desc: 'Overtemp' },
  { bit: 1,  name: 'OTPW', desc: 'Overtemp prewarning' },
  { bit: 2,  name: 'S2GA', desc: 'Short to GND A' },
  { bit: 3,  name: 'S2GB', desc: 'Short to GND B' },
  { bit: 4,  name: 'OLA',  desc: 'Open load A' },
  { bit: 5,  name: 'OLB',  desc: 'Open load B' },
  { bit: 14, name: 'STST', desc: 'Standstill' },
  { bit: 24, name: 'SG',   desc: 'StallGuard' },
];

// ---------------------------------------------------------------------------
// Sub-tab helpers
// ---------------------------------------------------------------------------

function SubTabBar({ active, onChange }: { active: MotorSubTab; onChange: (t: MotorSubTab) => void }) {
  return (
    <div style={{ display: 'flex', borderBottom: `1px solid ${BORDER}`, marginBottom: 20, gap: 0 }}>
      {SUB_TABS.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          style={{
            padding: '10px 18px',
            background: 'none',
            border: 'none',
            borderBottom: active === t.id ? '2px solid #3b82f6' : '2px solid transparent',
            color: active === t.id ? TEXT_PRIMARY : TEXT_MUTED,
            cursor: 'pointer',
            fontSize: 13,
            fontWeight: active === t.id ? 600 : 400,
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Position Control sub-tab
// ---------------------------------------------------------------------------

function PositionControl({ motorStatus }: { motorStatus: MotorStatus | null }) {
  const [jogSpeed, setJogSpeed] = useState(10);
  const [stepSize, setStepSize] = useState(1);
  const [targetAxis, setTargetAxis] = useState(0);
  const [targetPos, setTargetPos] = useState(0);
  const [showHomeModal, setShowHomeModal] = useState(false);
  const [showMoveAllModal, setShowMoveAllModal] = useState(false);
  const [multiTarget, setMultiTarget] = useState([0, 0, 0, 0]);
  const [error, setError] = useState<string | null>(null);
  const jogIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [history, setHistory] = useState<ChartPoint[]>([]);
  const tRef = useRef(0);

  useEffect(() => {
    if (!motorStatus) return;
    const pt: ChartPoint = { t: tRef.current++ };
    motorStatus.axes.forEach((ax) => { pt[AXIS_NAMES[ax.axis]] = ax.position; });
    setHistory((prev) => [...prev.slice(-(HISTORY_LEN - 1)), pt]);
  }, [motorStatus]);

  async function jog(axis: number, direction: 1 | -1) {
    try { await motorApi.jog(axis, direction, jogSpeed, stepSize); } catch (e) { setError(String(e)); }
  }

  function startContinuousJog(axis: number, dir: 1 | -1) {
    jogIntervalRef.current = setInterval(() => jog(axis, dir), 150);
  }
  function stopContinuousJog() {
    if (jogIntervalRef.current) { clearInterval(jogIntervalRef.current); jogIntervalRef.current = null; }
    motorApi.stop().catch(() => null);
  }

  async function moveTo() {
    try { await motorApi.move(targetAxis, targetPos, jogSpeed); } catch (e) { setError(String(e)); }
  }
  async function moveAll() {
    setShowMoveAllModal(false);
    for (let i = 0; i < 4; i++) {
      try { await motorApi.move(i, multiTarget[i], jogSpeed); } catch { /* continue */ }
    }
  }

  const cardStyle = { background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 16, marginBottom: 16 };
  const btnBase = { padding: '6px 12px', border: `1px solid ${BORDER}`, borderRadius: 4, cursor: 'pointer', fontSize: 13, background: '#1e293b', color: TEXT_SECONDARY };

  return (
    <div>
      {error && <div style={{ color: '#ef4444', marginBottom: 12, fontSize: 13 }}>{error}</div>}

      {/* Jog controls */}
      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Axis Jog</h3>
        {(motorStatus?.axes ?? []).map((ax: AxisStatus) => (
          <div key={ax.axis} style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, padding: '8px 0', borderBottom: `1px solid ${BORDER}` }}>
            <div style={{ width: 70, fontSize: 13, color: AXIS_COLORS[ax.axis], fontWeight: 600 }}>
              {AXIS_NAMES[ax.axis]}
            </div>
            <span style={{ width: 80, fontSize: 12, color: TEXT_PRIMARY, textAlign: 'center' as const }}>
              {ax.position.toFixed(3)} {AXIS_UNITS[ax.axis]}
            </span>
            <div style={{ flex: 1, height: 6, background: BG_PRIMARY, borderRadius: 3 }}>
              <div style={{ height: '100%', width: `${Math.min(100, Math.abs(ax.position) / 200 * 100)}%`, background: AXIS_COLORS[ax.axis], borderRadius: 3 }} />
            </div>
            <button
              onMouseDown={() => startContinuousJog(ax.axis, -1)} onMouseUp={stopContinuousJog} onMouseLeave={stopContinuousJog}
              style={{ ...btnBase, color: '#93c5fd' }}
            >◀◀</button>
            <button onClick={() => jog(ax.axis, -1)} style={btnBase}>◀</button>
            <button onClick={() => jog(ax.axis, +1)} style={btnBase}>▶</button>
            <button
              onMouseDown={() => startContinuousJog(ax.axis, +1)} onMouseUp={stopContinuousJog} onMouseLeave={stopContinuousJog}
              style={{ ...btnBase, color: '#93c5fd' }}
            >▶▶</button>
          </div>
        ))}
        {(!motorStatus || motorStatus.axes.length === 0) && (
          <div style={{ fontSize: 13, color: TEXT_MUTED, textAlign: 'center', padding: 16 }}>Waiting for motor status...</div>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16, marginBottom: 16 }}>
        <div style={cardStyle}>
          <SliderInput label="Jog Speed" value={jogSpeed} min={1} max={100} unit="mm/s" onChange={setJogSpeed} style={{ marginBottom: 12 }} />
          <SliderInput label="Step Size" value={stepSize} min={0.1} max={50} step={0.1} unit="mm" onChange={setStepSize} />
        </div>
        <div style={cardStyle}>
          <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Move To Position</h3>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <select value={targetAxis} onChange={(e) => setTargetAxis(Number(e.target.value))} style={{ background: BG_PRIMARY, border: `1px solid ${BORDER}`, color: TEXT_PRIMARY, padding: '6px 8px', borderRadius: 4, fontSize: 13 }}>
              {AXIS_NAMES.map((n, i) => <option key={i} value={i}>{n}</option>)}
            </select>
            <input type="number" value={targetPos} onChange={(e) => setTargetPos(Number(e.target.value))} style={{ background: BG_PRIMARY, border: `1px solid ${BORDER}`, color: TEXT_PRIMARY, padding: '6px 8px', borderRadius: 4, fontSize: 13, width: 80 }} />
            <button onClick={moveTo} style={{ background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, padding: '6px 14px', cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>Move To</button>
          </div>
        </div>
      </div>

      {/* Actions */}
      <div style={{ ...cardStyle, display: 'flex', gap: 8, flexWrap: 'wrap' as const }}>
        <button onClick={() => setShowHomeModal(true)} style={{ background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, padding: '8px 14px', cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>Home All</button>
        {AXIS_NAMES.map((n, i) => (
          <button key={i} onClick={() => motorApi.home(1 << i)} style={{ ...btnBase, fontSize: 12 }}>Home {n}</button>
        ))}
        <button onClick={() => motorApi.stop()} style={{ ...btnBase, background: '#78350f', color: '#fcd34d' }}>Stop</button>
        <button onClick={() => motorApi.reset()} style={btnBase}>Reset Fault</button>
      </div>

      {/* Position history chart */}
      {history.length > 1 && (
        <div style={cardStyle}>
          <h3 style={{ margin: '0 0 8px', fontSize: 14, color: TEXT_PRIMARY }}>Position History</h3>
          <div style={{ height: 180 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={history}>
                <XAxis dataKey="t" hide />
                <YAxis stroke="#475569" tick={{ fill: '#64748b', fontSize: 10 }} />
                <Tooltip contentStyle={{ background: BG_PANEL, border: `1px solid ${BORDER}`, color: TEXT_PRIMARY }} />
                {AXIS_NAMES.map((name, i) => (
                  <Line key={name} type="monotone" dataKey={name} stroke={AXIS_COLORS[i]} dot={false} isAnimationActive={false} strokeWidth={1.5} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {showHomeModal && (
        <ConfirmModal title="Home All Axes" description="Move all axes to home position. Ensure no wire is loaded." confirmLabel="Home All" onConfirm={() => { motorApi.home(0); setShowHomeModal(false); }} onCancel={() => setShowHomeModal(false)} />
      )}
      {showMoveAllModal && (
        <ConfirmModal title="Move All Axes" description="Move all axes to specified target positions simultaneously." confirmLabel="Move All" onConfirm={moveAll} onCancel={() => setShowMoveAllModal(false)} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Driver Config sub-tab
// ---------------------------------------------------------------------------

function DriverConfig() {
  const [selectedAxis, setSelectedAxis] = useState(0);
  const [irun, setIrun] = useState(20);
  const [ihold, setIhold] = useState(10);
  const [iholdDelay, setIholdDelay] = useState(6);
  const [toff, setToff] = useState(5);
  const [hstrt, setHstrt] = useState(4);
  const [hend, setHend] = useState(0);
  const [spreadCycle, setSpreadCycle] = useState(true);

  const cardStyle = { background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 16, marginBottom: 16 };
  const applyBtn = { background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, padding: '6px 14px', cursor: 'pointer', fontSize: 12, fontWeight: 600 };
  const readBtn = { background: '#1e293b', border: `1px solid ${BORDER}`, color: TEXT_SECONDARY, borderRadius: 4, padding: '6px 14px', cursor: 'pointer', fontSize: 12 };

  function irunToMa(v: number) { return Math.round((v / 31) * 1400); }

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <select value={selectedAxis} onChange={(e) => setSelectedAxis(Number(e.target.value))} style={{ background: BG_PRIMARY, border: `1px solid ${BORDER}`, color: TEXT_PRIMARY, padding: '6px 12px', borderRadius: 4, fontSize: 13 }}>
          {[...AXIS_NAMES.map((n, i) => ({ label: n, value: i })), { label: 'All Axes', value: 99 }].map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
        <div style={cardStyle}>
          <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Current Settings</h3>
          <SliderInput label={`IRUN (${irunToMa(irun)} mA)`} value={irun} min={0} max={31} onChange={setIrun} style={{ marginBottom: 12 }} />
          <SliderInput label={`IHOLD (${irunToMa(ihold)} mA)`} value={ihold} min={0} max={31} onChange={setIhold} style={{ marginBottom: 12 }} />
          <SliderInput label="IHOLDDELAY" value={iholdDelay} min={0} max={15} onChange={setIholdDelay} />
          <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
            <button style={applyBtn}>Apply</button>
            <button style={readBtn}>Read Back</button>
          </div>
        </div>

        <div style={cardStyle}>
          <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Chopper Settings</h3>
          <SliderInput label="TOFF" value={toff} min={1} max={15} onChange={setToff} style={{ marginBottom: 12 }} />
          <SliderInput label="HSTRT" value={hstrt} min={0} max={7} onChange={setHstrt} style={{ marginBottom: 12 }} />
          <SliderInput label="HEND" value={hend} min={-3} max={12} onChange={setHend} style={{ marginBottom: 12 }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
            <span style={{ fontSize: 12, color: TEXT_MUTED }}>Mode:</span>
            <button
              onClick={() => setSpreadCycle(!spreadCycle)}
              style={{ background: spreadCycle ? '#1e3a5f' : '#1e293b', border: `1px solid ${spreadCycle ? '#3b82f6' : BORDER}`, color: spreadCycle ? '#93c5fd' : TEXT_MUTED, borderRadius: 4, padding: '4px 10px', cursor: 'pointer', fontSize: 12 }}
            >
              {spreadCycle ? 'SpreadCycle' : 'StealthChop'}
            </button>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button style={applyBtn}>Apply</button>
            <button style={readBtn}>Read Back</button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// StallGuard sub-tab
// ---------------------------------------------------------------------------

function StallGuardTab({ motorStatus }: { motorStatus: MotorStatus | null }) {
  const [sgThresholds, setSgThresholds] = useState([0, 0, 0, 0]);
  const [sgHistory, setSgHistory] = useState<ChartPoint[]>([]);
  const tRef = useRef(0);

  useEffect(() => {
    if (!motorStatus) return;
    const pt: ChartPoint = { t: tRef.current++ };
    motorStatus.axes.forEach((ax) => { pt[`SG${ax.axis}`] = ax.sg_result; });
    setSgHistory((prev) => [...prev.slice(-99), pt]);
  }, [motorStatus]);

  const cardStyle = { background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 16, marginBottom: 16 };

  return (
    <div>
      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>StallGuard Thresholds (SGT)</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {AXIS_NAMES.map((name, i) => (
            <SliderInput
              key={i}
              label={`${name} SGT`}
              value={sgThresholds[i]}
              min={-64}
              max={63}
              onChange={(v) => setSgThresholds((prev) => { const next = [...prev]; next[i] = v; return next; })}
            />
          ))}
        </div>
      </div>

      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 4px', fontSize: 14, color: TEXT_PRIMARY }}>SG_RESULT (live)</h3>
        <div style={{ display: 'flex', gap: 16, marginBottom: 8 }}>
          {AXIS_NAMES.map((name, i) => (
            <div key={i} style={{ fontSize: 13, color: AXIS_COLORS[i] }}>
              {name}: <strong>{motorStatus?.axes[i]?.sg_result ?? 0}</strong>
            </div>
          ))}
        </div>
        <div style={{ height: 160 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={sgHistory}>
              <XAxis dataKey="t" hide />
              <YAxis stroke="#475569" tick={{ fill: '#64748b', fontSize: 10 }} />
              <Tooltip contentStyle={{ background: BG_PANEL, border: `1px solid ${BORDER}`, color: TEXT_PRIMARY }} />
              <ReferenceLine y={0} stroke="#ef4444" strokeDasharray="4 4" />
              {AXIS_NAMES.map((_, i) => (
                <Line key={i} type="monotone" dataKey={`SG${i}`} stroke={AXIS_COLORS[i]} dot={false} isAnimationActive={false} strokeWidth={1.5} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Auto Calibrate</h3>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <select style={{ background: BG_PRIMARY, border: `1px solid ${BORDER}`, color: TEXT_PRIMARY, padding: '6px 8px', borderRadius: 4, fontSize: 13 }}>
            {AXIS_NAMES.map((n, i) => <option key={i}>{n}</option>)}
          </select>
          <button style={{ background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, padding: '6px 14px', cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>
            Start Calibration
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Diagnostics sub-tab
// ---------------------------------------------------------------------------

function DiagnosticsTab({ motorStatus }: { motorStatus: MotorStatus | null }) {
  const [regJson, setRegJson] = useState<string | null>(null);

  function readAllRegisters() {
    setRegJson(JSON.stringify(motorStatus?.axes ?? [], null, 2));
  }

  const cardStyle = { background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 16, marginBottom: 16 };

  return (
    <div>
      {(motorStatus?.axes ?? []).map((ax: AxisStatus) => (
        <div key={ax.axis} style={cardStyle}>
          <h3 style={{ margin: '0 0 12px', fontSize: 14, color: AXIS_COLORS[ax.axis] }}>
            {AXIS_NAMES[ax.axis]} — DRV_STATUS
          </h3>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' as const }}>
            {DRV_BITS.map(({ bit, name, desc }) => {
              const isSet = !!(ax.drv_status & (1 << bit));
              const isOk = name === 'STST' ? !isSet : name === 'SG' ? isSet : !isSet;
              return (
                <div
                  key={name}
                  title={desc}
                  style={{
                    padding: '3px 10px',
                    borderRadius: 4,
                    fontSize: 12,
                    fontWeight: 600,
                    background: isSet ? '#7f1d1d' : '#065f46',
                    color: isSet ? '#fca5a5' : '#6ee7b7',
                    cursor: 'default',
                  }}
                >
                  {name}
                </div>
              );
            })}
          </div>
          <div style={{ marginTop: 8, fontSize: 12, color: TEXT_MUTED }}>
            CS_ACTUAL: {ax.cs_actual} &nbsp;|&nbsp; SG_RESULT: {ax.sg_result}
          </div>
        </div>
      ))}

      {(!motorStatus || motorStatus.axes.length === 0) && (
        <div style={{ fontSize: 13, color: TEXT_MUTED, textAlign: 'center', padding: 24 }}>No motor data</div>
      )}

      <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
        <button
          onClick={readAllRegisters}
          style={{ background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, padding: '8px 14px', cursor: 'pointer', fontSize: 13, fontWeight: 600 }}
        >
          Read All Registers
        </button>
      </div>

      {regJson && (
        <div style={cardStyle}>
          <pre style={{ fontSize: 11, color: '#6ee7b7', margin: 0, overflowX: 'auto', maxHeight: 200, overflowY: 'auto' }}>{regJson}</pre>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main MotorPage
// ---------------------------------------------------------------------------

export function MotorPage() {
  const [subTab, setSubTab] = useState<MotorSubTab>('position');
  const [staticMotor, setStaticMotor] = useState<MotorStatus | null>(null);
  const liveMotor = useMotorWs();
  const motorStatus = liveMotor ?? staticMotor;

  useEffect(() => {
    motorApi.status().then(setStaticMotor).catch(() => null);
  }, []);

  const refreshMotor = () => motorApi.status().then(setStaticMotor).catch(() => null);
  const isMoving = motorStatus !== null && ![0, 5, 6].includes(motorStatus.state);

  return (
    <div style={{ padding: 'clamp(12px, 3vw, 20px)', maxWidth: 1100, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 4px', color: TEXT_PRIMARY, fontSize: 18 }}>Motor Control</h2>
      <div style={{ fontSize: 13, color: TEXT_MUTED, marginBottom: 14 }}>
        State: <strong style={{ color: TEXT_PRIMARY }}>
          {motorStatus ? (['IDLE','HOMING','RUNNING','JOGGING','STOPPING','FAULT','ESTOP'][motorStatus.state] ?? '?') : '—'}
        </strong>
        &nbsp;|&nbsp; Step: <strong style={{ color: TEXT_PRIMARY }}>
          {motorStatus ? `${motorStatus.current_step} / ${motorStatus.total_steps}` : '—'}
        </strong>
      </div>

      <div style={{
        background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 6,
        padding: 14, marginBottom: 18,
      }}>
        <ConnectionControl
          label="Drivers"
          connected={motorStatus?.driver_enabled === true}
          connectedLabel="ENERGIZED"
          disconnectedLabel="FREE-WHEEL"
          disabled={isMoving}
          onConnect={async () => { await motorApi.enable(); await refreshMotor(); }}
          onDisconnect={async () => { await motorApi.disable(); await refreshMotor(); }}
          disconnectConfirm={{
            title: 'Disable motor drivers?',
            description:
              'TMC260C-PA DRV_ENN will be released — stepper coils de-energize and the axes will free-wheel. ' +
              'VMot 12V remains present. Re-enable to resume holding torque.',
          }}
        />
      </div>

      <SubTabBar active={subTab} onChange={setSubTab} />

      {subTab === 'position'    && <PositionControl motorStatus={motorStatus} />}
      {subTab === 'driver'      && <DriverConfig />}
      {subTab === 'stallguard'  && <StallGuardTab motorStatus={motorStatus} />}
      {subTab === 'diagnostics' && <DiagnosticsTab motorStatus={motorStatus} />}
    </div>
  );
}
