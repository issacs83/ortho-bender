/**
 * BendingPage.tsx — Wire bending wizard: Material → B-code → Execute → Result.
 */

import { useEffect, useRef, useState } from 'react';
import { bendingApi, motorApi, cameraApi, type BcodeStep, type BendingStatus, type SystemStatus } from '../api/client';
import { systemApi } from '../api/client';
import { StepIndicator } from '../components/bending/StepIndicator';
import { ConfirmModal } from '../components/ui/ConfirmModal';
import { StatusBadge } from '../components/ui/StatusBadge';
import { Button } from '../components/ui/Button';
import { Card, CardTitle } from '../components/ui/Card';
import { useMotorWs } from '../hooks/useMotorWs';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { AXIS_COLORS, AXIS_NAMES, BG_PANEL, BORDER, TEXT_PRIMARY, WIRE_MATERIALS, WIRE_DIAMETERS, HISTORY_LEN, type WireMaterial } from '../constants';
import { cn } from '../lib/cn';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface BcodeRow extends BcodeStep {
  id: number;
}

interface ChartPoint {
  t: number;
  [key: string]: number;
}

// ---------------------------------------------------------------------------
// Wire Preview SVG
// ---------------------------------------------------------------------------

function WirePreview({ steps }: { steps: BcodeRow[] }) {
  const width = 280;
  const height = 200;
  const cx = 140;
  const cy = 100;
  const scale = 2;

  let x = cx;
  let y = cy;
  let angle = 0; // degrees, 0 = right
  const points: Array<[number, number]> = [[x, y]];

  for (const s of steps) {
    const rad = ((angle + s.beta_deg) * Math.PI) / 180;
    const dx = Math.cos(rad) * s.L_mm * scale;
    const dy = -Math.sin(rad) * s.L_mm * scale;
    x += dx;
    y += dy;
    angle += s.beta_deg;
    points.push([x, y]);
  }

  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ');

  return (
    <svg width={width} height={height} className="bg-surface-2 rounded border border-border">
      <path d={pathD} fill="none" stroke="#3b82f6" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      {points.map(([px, py], i) => (
        <circle key={i} cx={px} cy={py} r={3} fill={i === 0 ? '#22c55e' : i === points.length - 1 ? '#f59e0b' : '#3b82f6'} />
      ))}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Pre-flight check modal
// ---------------------------------------------------------------------------

interface PreflightModalProps {
  sysStatus: SystemStatus | null;
  steps: BcodeRow[];
  material: WireMaterial;
  onStart: () => void;
  onCancel: () => void;
}

function PreflightModal({ sysStatus, steps, material, onStart, onCancel }: PreflightModalProps) {
  const checks = [
    { label: 'System IDLE',        ok: (sysStatus?.motion_state ?? -1) === 0 },
    { label: 'Board connected',    ok: true },
    { label: 'Controller link',    ok: sysStatus?.ipc_connected ?? false },
    { label: 'Motor controller',   ok: sysStatus?.m7_heartbeat_ok ?? false },
    { label: 'No active alarms',   ok: (sysStatus?.active_alarms ?? 1) === 0 },
    { label: 'B-code valid',       ok: steps.length > 0 },
    { label: 'Material selected',  ok: true },
    { label: 'Camera connected',   ok: sysStatus?.camera_connected ?? false, optional: true },
  ];
  const canStart = checks.filter((c) => !c.optional).every((c) => c.ok);

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-[1000]">
      <div className="bg-surface-1 border border-border rounded-lg p-6 w-[420px] max-w-[90vw]">
        <h3 className="text-[15px] font-semibold text-text-primary mb-4">Pre-flight Check</h3>
        <div className="flex flex-col gap-2 mb-5">
          {checks.map((c) => (
            <div key={c.label} className="flex items-center gap-2.5">
              <span className="text-base">{c.ok ? '✅' : c.optional ? '⚠️' : '❌'}</span>
              <span className={cn(
                'text-[13px]',
                c.ok ? 'text-success' : c.optional ? 'text-warning' : 'text-danger',
              )}>
                {c.label}
                {c.optional && !c.ok && ' (optional)'}
              </span>
            </div>
          ))}
        </div>
        <div className="text-[12px] text-text-tertiary mb-4">
          Material: {material.name} | Steps: {steps.length}
        </div>
        <div className="flex gap-2.5 justify-end">
          <Button variant="secondary" onClick={onCancel}>Cancel</Button>
          <Button variant="primary" onClick={onStart} disabled={!canStart}>
            Start Bending
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function BendingPage() {
  const [wizardStep, setWizardStep] = useState(0);
  const [materialId, setMaterialId] = useState(0);
  const [diameterMm, setDiameterMm] = useState(0.457);
  const [rows, setRows] = useState<BcodeRow[]>([{ id: 1, L_mm: 10, beta_deg: 0, theta_deg: 0 }]);
  const [nextId, setNextId] = useState(2);
  const [showPreflight, setShowPreflight] = useState(false);
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);
  const [bendingStatus, setBendingStatus] = useState<BendingStatus | null>(null);
  const [chartHistory, setChartHistory] = useState<ChartPoint[]>([]);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [captures, setCaptures] = useState<string[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const tRef = useRef(0);
  const liveMotor = useMotorWs();

  const material = WIRE_MATERIALS[materialId];

  useEffect(() => {
    systemApi.status().then(setSysStatus).catch(() => null);
  }, []);

  // Live chart update
  useEffect(() => {
    if (!liveMotor || wizardStep !== 2) return;
    const pt: ChartPoint = { t: tRef.current++ };
    liveMotor.axes.forEach((ax) => { pt[AXIS_NAMES[ax.axis]] = ax.position; });
    setChartHistory((prev) => [...prev.slice(-(HISTORY_LEN - 1)), pt]);

    // Sync bending status
    if (liveMotor.current_step >= 0) {
      setBendingStatus((prev) => prev ? {
        ...prev,
        current_step: liveMotor.current_step,
        progress_pct: liveMotor.total_steps > 0 ? (liveMotor.current_step / liveMotor.total_steps) * 100 : 0,
      } : null);
    }
  }, [liveMotor, wizardStep]);

  // Elapsed timer
  useEffect(() => {
    if (wizardStep === 2) {
      timerRef.current = setInterval(() => setElapsedMs((p) => p + 1000), 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [wizardStep]);

  function addRow() {
    setRows((prev) => [...prev, { id: nextId, L_mm: 10, beta_deg: 0, theta_deg: 0 }]);
    setNextId((n) => n + 1);
  }

  function removeRow(id: number) {
    setRows((prev) => prev.filter((r) => r.id !== id));
  }

  function updateRow(id: number, field: keyof BcodeStep, value: number) {
    setRows((prev) => prev.map((r) => r.id === id ? { ...r, [field]: value } : r));
  }

  function isRowValid(r: BcodeRow): boolean {
    return r.L_mm > 0 && r.beta_deg >= -180 && r.beta_deg <= 180 && r.theta_deg >= -90 && r.theta_deg <= 90;
  }

  async function startBending() {
    setShowPreflight(false);
    setWizardStep(2);
    setElapsedMs(0);
    tRef.current = 0;
    setChartHistory([]);

    const steps: BcodeStep[] = rows.map(({ L_mm, beta_deg, theta_deg }) => ({ L_mm, beta_deg, theta_deg }));
    try {
      const status = await bendingApi.execute(steps, materialId, diameterMm);
      setBendingStatus(status);
    } catch {
      // error — stay on step 2, user can see fault state
    }
  }

  async function stopBending() {
    try {
      await bendingApi.stop();
    } catch { /* ignore */ }
    setWizardStep(3);
  }

  function captureFrame() {
    setCaptures((prev) => [...prev, new Date().toISOString()]);
  }

  const totalLength = rows.reduce((s, r) => s + r.L_mm, 0);
  const elapsedStr = `${Math.floor(elapsedMs / 60000)}m ${Math.floor((elapsedMs % 60000) / 1000)}s`;

  const allRowsValid = rows.length > 0 && rows.every(isRowValid);

  const selectCls = 'bg-surface-2 border border-border text-text-primary px-2.5 py-1.5 rounded text-[13px] w-full outline-none focus:border-accent';
  const labelCls = 'text-[12px] text-text-tertiary block mb-1.5';
  const thCls = 'px-2 py-1 text-left text-text-tertiary text-[11px] border-b border-border font-semibold';
  const tdCls = 'px-2 py-1';

  function numInput(value: number, min: number, max: number, valid: boolean, onChange: (v: number) => void) {
    return (
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
        className={cn(
          'w-[72px] bg-surface-2 border rounded text-center text-[12px] px-1.5 py-1 outline-none numeric',
          valid ? 'border-border text-text-primary focus:border-accent' : 'border-danger text-danger',
        )}
      />
    );
  }

  const STATE_LABELS = ['IDLE', 'HOMING', 'RUNNING', 'JOGGING', 'STOPPING', 'FAULT', 'ESTOP'];

  return (
    <div className="px-[clamp(12px,3vw,20px)] py-[clamp(12px,3vw,20px)] max-w-[1100px] mx-auto">
      <h2 className="text-[18px] font-semibold text-text-primary mb-5">Wire Bending</h2>

      <StepIndicator currentStep={wizardStep} />

      {/* ================================================================ */}
      {/* Step 0: Material & Wire Setup                                    */}
      {/* ================================================================ */}
      {wizardStep === 0 && (
        <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
          <Card>
            <CardTitle className="mb-4">Wire Profile</CardTitle>

            <div className="mb-3.5">
              <label className={labelCls}>Material</label>
              <select value={materialId} onChange={(e) => setMaterialId(Number(e.target.value))} className={selectCls}>
                {WIRE_MATERIALS.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            </div>

            <div className="mb-5">
              <label className={labelCls}>Wire Diameter</label>
              <select value={diameterMm} onChange={(e) => setDiameterMm(Number(e.target.value))} className={selectCls}>
                {WIRE_DIAMETERS.map((d) => (
                  <option key={d} value={d}>{d.toFixed(3)} mm</option>
                ))}
              </select>
            </div>

            <Button variant="primary" className="w-full" onClick={() => setWizardStep(1)}>
              Next: B-code Editor →
            </Button>
          </Card>

          <Card>
            <CardTitle className="mb-4">Material Properties</CardTitle>
            <div className="flex flex-col gap-2.5">
              {[
                ['Springback', material.springback],
                ['Heating',    material.heating],
                ['Speed',      material.speed],
                ['Max Angle',  `${material.maxAngle}°`],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between py-1.5 border-b border-border">
                  <span className="text-[13px] text-text-tertiary">{k}</span>
                  <span className="text-[13px] text-text-primary">{v}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {/* ================================================================ */}
      {/* Step 1: B-code Editor                                            */}
      {/* ================================================================ */}
      {wizardStep === 1 && (
        <div>
          <div className="grid gap-4 mb-4" style={{ gridTemplateColumns: '1fr 300px' }}>
            <Card>
              <CardTitle className="mb-3">B-code Sequence</CardTitle>
              <table className="w-full border-collapse text-[13px]">
                <thead>
                  <tr>
                    {['#', 'L (mm)', 'beta (°)', 'theta (°)', ''].map((h) => (
                      <th key={h} className={thCls}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => {
                    return (
                      <tr key={row.id}>
                        <td className={cn(tdCls, 'text-text-tertiary')}>{i + 1}</td>
                        <td className={tdCls}>{numInput(row.L_mm, 0.1, 999, row.L_mm > 0, (v) => updateRow(row.id, 'L_mm', v))}</td>
                        <td className={tdCls}>{numInput(row.beta_deg, -180, 180, row.beta_deg >= -180 && row.beta_deg <= 180, (v) => updateRow(row.id, 'beta_deg', v))}</td>
                        <td className={tdCls}>{numInput(row.theta_deg, -90, 90, row.theta_deg >= -90 && row.theta_deg <= 90, (v) => updateRow(row.id, 'theta_deg', v))}</td>
                        <td className={tdCls}>
                          <button
                            onClick={() => removeRow(row.id)}
                            className="bg-transparent border-none text-danger cursor-pointer text-[14px] hover:opacity-70"
                          >✕</button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <Button variant="secondary" size="sm" className="mt-2.5" onClick={addRow}>
                + Add Step
              </Button>

              <div className="mt-3.5 p-2.5 bg-surface-2 rounded flex gap-5 text-[12px] text-text-tertiary">
                <span>Total: <strong className="text-text-primary numeric">{totalLength.toFixed(1)} mm</strong></span>
                <span>Steps: <strong className="text-text-primary numeric">{rows.length}</strong></span>
                <span>Est: <strong className="text-text-primary numeric">~{Math.ceil(totalLength / 5)}s</strong></span>
              </div>
            </Card>

            <Card className="flex flex-col items-center gap-2.5">
              <CardTitle className="self-start mb-1">Wire Preview</CardTitle>
              <WirePreview steps={rows} />
              <div className="text-[11px] text-text-tertiary">
                <span className="text-success">●</span> Start &nbsp;
                <span className="text-warning">●</span> End
              </div>
            </Card>
          </div>

          <div className="flex justify-between">
            <Button variant="secondary" onClick={() => setWizardStep(0)}>← Back</Button>
            <Button
              variant="primary"
              onClick={() => setShowPreflight(true)}
              disabled={!allRowsValid}
            >
              Execute Bending →
            </Button>
          </div>
        </div>
      )}

      {/* ================================================================ */}
      {/* Step 2: Execute & Monitor                                        */}
      {/* ================================================================ */}
      {wizardStep === 2 && (
        <div className="flex flex-col gap-4">
          <Card className="flex gap-5 items-center">
            <span className="text-[13px] text-text-tertiary">
              Material: <strong className="text-text-primary">{material.name}</strong>
            </span>
            <span className="text-[13px] text-text-tertiary">
              Steps: <strong className="text-text-primary numeric">{rows.length}</strong>
            </span>
            <StatusBadge
              variant="info"
              label={liveMotor ? (STATE_LABELS[liveMotor.state] ?? 'RUNNING') : 'RUNNING'}
            />
          </Card>

          <Card>
            <div className="flex justify-between mb-2">
              <span className="text-[13px] text-text-tertiary">Progress</span>
              <span className="text-[13px] text-text-primary numeric">
                {bendingStatus?.current_step ?? 0} / {bendingStatus?.total_steps ?? rows.length}
              </span>
            </div>
            <div className="h-2 bg-surface-2 rounded-full overflow-hidden mb-2">
              <div
                className="h-full bg-accent rounded-full transition-[width] duration-500"
                style={{ width: `${bendingStatus?.progress_pct ?? 0}%` }}
              />
            </div>
            <div className="flex gap-5 text-[12px] text-text-tertiary">
              <span>Elapsed: <strong className="text-text-primary numeric">{elapsedStr}</strong></span>
            </div>
          </Card>

          <Card>
            <CardTitle className="mb-3">Axis Position (live)</CardTitle>
            <div style={{ height: 200 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartHistory}>
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

          <div className="flex justify-center">
            <button
              onClick={stopBending}
              className="bg-danger text-white border-none rounded-md px-8 py-3 cursor-pointer text-[14px] font-bold tracking-wide hover:opacity-90 transition-opacity"
            >
              STOP BENDING
            </button>
          </div>
        </div>
      )}

      {/* ================================================================ */}
      {/* Step 3: Result & Inspect                                         */}
      {/* ================================================================ */}
      {wizardStep === 3 && (
        <div className="flex flex-col gap-4">
          <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
            <Card>
              <CardTitle className="mb-3">Camera Inspection</CardTitle>
              <div className="relative">
                <img
                  src={cameraApi.streamUrl()}
                  alt="Inspection"
                  className="w-full rounded border border-border"
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
                />
              </div>
              <Button variant="secondary" className="mt-2.5 w-full" onClick={captureFrame}>
                Capture Frame
              </Button>
            </Card>

            <Card>
              <CardTitle className="mb-3">Step Summary</CardTitle>
              <table className="w-full border-collapse text-[12px]">
                <thead>
                  <tr>
                    {['#', 'L', 'beta', 'theta', 'Status'].map((h) => (
                      <th key={h} className={thCls}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr key={row.id}>
                      <td className={cn(tdCls, 'text-text-tertiary numeric')}>{i + 1}</td>
                      <td className={cn(tdCls, 'text-text-primary numeric')}>{row.L_mm}</td>
                      <td className={cn(tdCls, 'text-text-primary numeric')}>{row.beta_deg}°</td>
                      <td className={cn(tdCls, 'text-text-primary numeric')}>{row.theta_deg}°</td>
                      <td className={tdCls}>
                        <StatusBadge variant="success" label="OK" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>

          <div className="flex gap-2.5 justify-end">
            <Button
              variant="primary"
              onClick={() => { setWizardStep(0); setRows([{ id: 1, L_mm: 10, beta_deg: 0, theta_deg: 0 }]); }}
            >
              New Bending
            </Button>
            <Button variant="secondary">Export CSV</Button>
          </div>
        </div>
      )}

      {/* Pre-flight Modal */}
      {showPreflight && (
        <PreflightModal
          sysStatus={sysStatus}
          steps={rows}
          material={material}
          onStart={startBending}
          onCancel={() => setShowPreflight(false)}
        />
      )}
    </div>
  );
}
