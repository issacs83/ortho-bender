/**
 * MotorPage.tsx — Motor control with 4 sub-tabs: Position, Driver Config, StallGuard, Diagnostics.
 */

import { useEffect, useRef, useState } from 'react';
import { motorApi, diagApi, type MotorStatus, type AxisStatus, type DriverProbeResult } from '../api/client';
import { ConfirmModal } from '../components/ui/ConfirmModal';
import { SliderInput } from '../components/ui/SliderInput';
import { StatusBadge } from '../components/ui/StatusBadge';
import { Button } from '../components/ui/Button';
import { Card, CardTitle } from '../components/ui/Card';
import { EmptyState } from '../components/ui/EmptyState';
import { useMotorWs } from '../hooks/useMotorWs';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { AXIS_COLORS, AXIS_NAMES, AXIS_UNITS, BG_PANEL, BORDER, TEXT_PRIMARY, TEXT_MUTED, HISTORY_LEN } from '../constants';
import { cn } from '../lib/cn';

type MotorSubTab = 'position' | 'driver' | 'stallguard' | 'diagnostics';

const SUB_TABS: { id: MotorSubTab; label: string }[] = [
  { id: 'position',    label: 'Position Control' },
  { id: 'driver',      label: 'Driver Config' },
  { id: 'stallguard',  label: 'StallGuard' },
  { id: 'diagnostics', label: 'Diagnostics' },
];

// Axis channel color classes
const AXIS_TEXT_CLASSES = [
  'text-ch-feed',
  'text-ch-bend',
  'text-ch-rotate',
  'text-ch-lift',
];

const AXIS_BG_CLASSES = [
  'bg-ch-feed',
  'bg-ch-bend',
  'bg-ch-rotate',
  'bg-ch-lift',
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
    <div className="flex border-b border-border mb-5">
      {SUB_TABS.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={cn(
            'px-[18px] py-2.5 bg-transparent border-none border-b-2 -mb-px text-[13px] cursor-pointer transition-colors',
            active === t.id
              ? 'border-accent text-text-primary font-semibold'
              : 'border-transparent text-text-tertiary font-normal hover:text-text-secondary',
          )}
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
      try { await motorApi.move(i, 0, jogSpeed); } catch { /* continue */ }
    }
  }

  const selectCls = 'bg-surface-2 border border-border text-text-primary px-2 py-1.5 rounded text-[13px] outline-none focus:border-accent';

  return (
    <div>
      {error && <div className="text-danger mb-3 text-[13px]">{error}</div>}

      {/* Jog controls */}
      <Card className="mb-4">
        <CardTitle className="mb-3">Axis Jog</CardTitle>
        {(motorStatus?.axes ?? []).map((ax: AxisStatus) => (
          <div key={ax.axis} className="flex items-center gap-3 mb-3 pb-3 border-b border-border last:border-0 last:mb-0 last:pb-0">
            <div className={cn('w-[70px] text-[13px] font-semibold', AXIS_TEXT_CLASSES[ax.axis])}>
              {AXIS_NAMES[ax.axis]}
            </div>
            <span className="w-20 text-[12px] text-text-primary text-center numeric">
              {ax.position.toFixed(3)} {AXIS_UNITS[ax.axis]}
            </span>
            <div className="flex-1 h-1.5 bg-surface-2 rounded-full overflow-hidden">
              <div
                className={cn('h-full rounded-full', AXIS_BG_CLASSES[ax.axis])}
                style={{ width: `${Math.min(100, Math.abs(ax.position) / 200 * 100)}%` }}
              />
            </div>
            <Button
              variant="secondary" size="sm"
              className="text-accent"
              onMouseDown={() => startContinuousJog(ax.axis, -1)}
              onMouseUp={stopContinuousJog}
              onMouseLeave={stopContinuousJog}
            >◀◀</Button>
            <Button variant="secondary" size="sm" onClick={() => jog(ax.axis, -1)}>◀</Button>
            <Button variant="secondary" size="sm" onClick={() => jog(ax.axis, +1)}>▶</Button>
            <Button
              variant="secondary" size="sm"
              className="text-accent"
              onMouseDown={() => startContinuousJog(ax.axis, +1)}
              onMouseUp={stopContinuousJog}
              onMouseLeave={stopContinuousJog}
            >▶▶</Button>
          </div>
        ))}
        {(!motorStatus || motorStatus.axes.length === 0) && (
          <EmptyState
            icon={<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>}
            message="Waiting for motor status..."
          />
        )}
      </Card>

      <div className="grid gap-4 mb-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
        <Card>
          <SliderInput label="Jog Speed" value={jogSpeed} min={1} max={100} unit="mm/s" onChange={setJogSpeed} style={{ marginBottom: 12 }} />
          <SliderInput label="Step Size" value={stepSize} min={0.1} max={50} step={0.1} unit="mm" onChange={setStepSize} />
        </Card>
        <Card>
          <CardTitle className="mb-3">Move To Position</CardTitle>
          <div className="flex gap-2 items-end">
            <select value={targetAxis} onChange={(e) => setTargetAxis(Number(e.target.value))} className={selectCls}>
              {AXIS_NAMES.map((n, i) => <option key={i} value={i}>{n}</option>)}
            </select>
            <input
              type="number"
              value={targetPos}
              onChange={(e) => setTargetPos(Number(e.target.value))}
              className="bg-surface-2 border border-border text-text-primary px-2 py-1.5 rounded text-[13px] w-20 outline-none focus:border-accent numeric"
            />
            <Button variant="primary" onClick={moveTo}>Move To</Button>
          </div>
        </Card>
      </div>

      {/* Actions */}
      <Card className="flex gap-2 flex-wrap mb-4">
        <Button variant="primary" onClick={() => setShowHomeModal(true)}>Home All</Button>
        {AXIS_NAMES.map((n, i) => (
          <Button key={i} variant="secondary" size="sm" onClick={() => motorApi.home(1 << i)}>Home {n}</Button>
        ))}
        <Button variant="danger" onClick={() => motorApi.stop()}>Stop</Button>
        <Button variant="secondary" onClick={() => motorApi.reset()}>Reset Fault</Button>
      </Card>

      {/* Position history chart */}
      {history.length > 1 && (
        <Card>
          <CardTitle className="mb-2">Position History</CardTitle>
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
        </Card>
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

  function irunToMa(v: number) { return Math.round((v / 31) * 1400); }

  const selectCls = 'bg-surface-2 border border-border text-text-primary px-3 py-1.5 rounded text-[13px] outline-none focus:border-accent';

  return (
    <div>
      <div className="mb-4">
        <select value={selectedAxis} onChange={(e) => setSelectedAxis(Number(e.target.value))} className={selectCls}>
          {[...AXIS_NAMES.map((n, i) => ({ label: n, value: i })), { label: 'All Axes', value: 99 }].map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
        <Card>
          <CardTitle className="mb-3">Current Settings</CardTitle>
          <SliderInput label={`IRUN (${irunToMa(irun)} mA)`} value={irun} min={0} max={31} onChange={setIrun} style={{ marginBottom: 12 }} />
          <SliderInput label={`IHOLD (${irunToMa(ihold)} mA)`} value={ihold} min={0} max={31} onChange={setIhold} style={{ marginBottom: 12 }} />
          <SliderInput label="IHOLDDELAY" value={iholdDelay} min={0} max={15} onChange={setIholdDelay} />
          <div className="flex gap-2 mt-3.5">
            <Button variant="primary" size="sm">Apply</Button>
            <Button variant="secondary" size="sm">Read Back</Button>
          </div>
        </Card>

        <Card>
          <CardTitle className="mb-3">Chopper Settings</CardTitle>
          <SliderInput label="TOFF" value={toff} min={1} max={15} onChange={setToff} style={{ marginBottom: 12 }} />
          <SliderInput label="HSTRT" value={hstrt} min={0} max={7} onChange={setHstrt} style={{ marginBottom: 12 }} />
          <SliderInput label="HEND" value={hend} min={-3} max={12} onChange={setHend} style={{ marginBottom: 12 }} />
          <div className="flex items-center gap-2.5 mb-3">
            <span className="text-[12px] text-text-tertiary">Mode:</span>
            <button
              onClick={() => setSpreadCycle(!spreadCycle)}
              className={cn(
                'text-[12px] px-2.5 py-1 rounded border cursor-pointer transition-colors',
                spreadCycle
                  ? 'bg-accent-soft border-accent text-accent'
                  : 'bg-surface-2 border-border text-text-tertiary',
              )}
            >
              {spreadCycle ? 'SpreadCycle' : 'StealthChop'}
            </button>
          </div>
          <div className="flex gap-2">
            <Button variant="primary" size="sm">Apply</Button>
            <Button variant="secondary" size="sm">Read Back</Button>
          </div>
        </Card>
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

  const selectCls = 'bg-surface-2 border border-border text-text-primary px-2 py-1.5 rounded text-[13px] outline-none focus:border-accent';

  return (
    <div>
      <Card className="mb-4">
        <CardTitle className="mb-3">StallGuard Thresholds (SGT)</CardTitle>
        <div className="grid grid-cols-2 gap-3">
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
      </Card>

      <Card className="mb-4">
        <CardTitle className="mb-1">SG_RESULT (live)</CardTitle>
        <div className="flex gap-4 mb-2">
          {AXIS_NAMES.map((name, i) => (
            <div key={i} className={cn('text-[13px]', AXIS_TEXT_CLASSES[i])}>
              {name}: <strong className="numeric">{motorStatus?.axes[i]?.sg_result ?? 0}</strong>
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
      </Card>

      <Card>
        <CardTitle className="mb-3">Auto Calibrate</CardTitle>
        <div className="flex gap-2.5 items-center">
          <select className={selectCls}>
            {AXIS_NAMES.map((n, i) => <option key={i}>{n}</option>)}
          </select>
          <Button variant="primary">Start Calibration</Button>
        </div>
      </Card>
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

  return (
    <div>
      {(motorStatus?.axes ?? []).map((ax: AxisStatus) => (
        <Card key={ax.axis} className="mb-4">
          <CardTitle className={cn('mb-3', AXIS_TEXT_CLASSES[ax.axis])}>
            {AXIS_NAMES[ax.axis]} — DRV_STATUS
          </CardTitle>
          <div className="flex gap-2 flex-wrap">
            {DRV_BITS.map(({ bit, name, desc }) => {
              const isSet = !!(ax.drv_status & (1 << bit));
              return (
                <div
                  key={name}
                  title={desc}
                  className={cn(
                    'px-2.5 py-0.5 rounded text-[12px] font-semibold cursor-default',
                    isSet
                      ? 'bg-danger-soft text-danger'
                      : 'bg-success-soft text-success',
                  )}
                >
                  {name}
                </div>
              );
            })}
          </div>
          <div className="mt-2 text-[12px] text-text-tertiary numeric">
            CS_ACTUAL: {ax.cs_actual} &nbsp;|&nbsp; SG_RESULT: {ax.sg_result}
          </div>
        </Card>
      ))}

      {(!motorStatus || motorStatus.axes.length === 0) && (
        <EmptyState
          icon={<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/></svg>}
          message="No motor data"
          className="py-6"
        />
      )}

      <div className="flex gap-2.5 mb-4">
        <Button variant="primary" onClick={readAllRegisters}>Read All Registers</Button>
      </div>

      {regJson && (
        <Card>
          <pre className="text-[11px] text-success font-mono m-0 overflow-x-auto max-h-[200px] overflow-y-auto">{regJson}</pre>
        </Card>
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
  const [probeResults, setProbeResults] = useState<DriverProbeResult[]>([]);
  const [probing, setProbing] = useState(false);
  const [showDisableModal, setShowDisableModal] = useState(false);
  const liveMotor = useMotorWs();
  const motorStatus = liveMotor ?? staticMotor;

  useEffect(() => {
    motorApi.status().then(setStaticMotor).catch(() => null);
    diagApi.probe().then(r => setProbeResults(r.drivers)).catch(() => {});
  }, []);

  const refreshMotor = () => motorApi.status().then(setStaticMotor).catch(() => null);
  const isMoving = motorStatus !== null && ![0, 5, 6].includes(motorStatus.state);

  const STATE_LABELS = ['IDLE', 'HOMING', 'RUNNING', 'JOGGING', 'STOPPING', 'FAULT', 'ESTOP'];

  async function handleProbe() {
    setProbing(true);
    try { const r = await diagApi.probe(); setProbeResults(r.drivers); }
    catch { /* ignore */ }
    finally { setProbing(false); }
  }

  return (
    <div className="px-[clamp(12px,3vw,20px)] py-[clamp(12px,3vw,20px)] max-w-[1100px] mx-auto">
      <h2 className="text-[18px] font-semibold text-text-primary mb-1">Motor Control</h2>
      <div className="text-[13px] text-text-tertiary mb-3.5">
        State: <strong className="text-text-primary">
          {motorStatus ? (STATE_LABELS[motorStatus.state] ?? '?') : '—'}
        </strong>
        &nbsp;|&nbsp; Step: <strong className="text-text-primary numeric">
          {motorStatus ? `${motorStatus.current_step} / ${motorStatus.total_steps}` : '—'}
        </strong>
      </div>

      {/* Driver Connection + Power Control */}
      <Card className="mb-[18px]">
        <div className="flex justify-between items-center mb-2.5">
          <span className="text-[13px] text-text-secondary font-semibold">Driver Connection</span>
          <div className="flex gap-2 items-center">
            <Button variant="secondary" size="sm" onClick={handleProbe} loading={probing}>
              {probing ? 'Probing...' : 'Re-Probe'}
            </Button>
            <button
              onClick={async () => {
                if (motorStatus?.driver_enabled) {
                  setShowDisableModal(true);
                } else {
                  await motorApi.enable(); await refreshMotor();
                }
              }}
              disabled={isMoving}
              className={cn(
                'text-[11px] font-semibold px-3 py-1 rounded border cursor-pointer transition-colors',
                'disabled:opacity-60 disabled:cursor-not-allowed',
                motorStatus?.driver_enabled
                  ? 'bg-success-soft text-success border-success/40'
                  : 'bg-surface-2 text-text-tertiary border-border',
              )}
            >
              {motorStatus?.driver_enabled ? 'ENERGIZED' : 'Enable Drivers'}
            </button>
          </div>
        </div>
        <div className="flex gap-2.5 flex-wrap">
          {probeResults.length === 0 ? (
            <span className="text-[12px] text-text-tertiary">Probing drivers...</span>
          ) : probeResults.map(p => (
            <div
              key={p.driver}
              className={cn(
                'flex items-center gap-1.5 px-2.5 py-[5px] rounded-md border',
                p.connected
                  ? 'bg-success-soft border-success/40'
                  : 'bg-danger-soft border-danger/40',
              )}
            >
              <span className={cn('w-[7px] h-[7px] rounded-full', p.connected ? 'bg-success' : 'bg-danger')} />
              <span className="text-[12px] text-text-primary font-semibold">{p.driver}</span>
              <span className={cn('text-[11px]', p.connected ? 'text-success' : 'text-danger')}>
                {p.connected ? p.chip : 'NOT FOUND'}
              </span>
            </div>
          ))}
        </div>
      </Card>

      {showDisableModal && (
        <ConfirmModal
          title="Disable motor drivers?"
          description="TMC260C-PA DRV_ENN will be released — stepper coils de-energize and the axes will free-wheel. VMot 12V remains present. Re-enable to resume holding torque."
          confirmLabel="Disable"
          confirmVariant="danger"
          onConfirm={async () => { setShowDisableModal(false); await motorApi.disable(); await refreshMotor(); }}
          onCancel={() => setShowDisableModal(false)}
        />
      )}

      <SubTabBar active={subTab} onChange={setSubTab} />

      {subTab === 'position'    && <PositionControl motorStatus={motorStatus} />}
      {subTab === 'driver'      && <DriverConfig />}
      {subTab === 'stallguard'  && <StallGuardTab motorStatus={motorStatus} />}
      {subTab === 'diagnostics' && <DiagnosticsTab motorStatus={motorStatus} />}
    </div>
  );
}
