/**
 * BendingPage.tsx — Wire bending wizard: Material → B-code → Execute → Result.
 */

import { useEffect, useRef, useState } from 'react';
import { bendingApi, motorApi, cameraApi, type BcodeStep, type BendingStatus, type SystemStatus } from '../api/client';
import { systemApi } from '../api/client';
import { StepIndicator } from '../components/bending/StepIndicator';
import { ConfirmModal } from '../components/ui/ConfirmModal';
import { StatusBadge } from '../components/ui/StatusBadge';
import { useMotorWs } from '../hooks/useMotorWs';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { AXIS_COLORS, AXIS_NAMES, AXIS_UNITS, BG_PANEL, BG_PRIMARY, BORDER, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, WIRE_MATERIALS, WIRE_DIAMETERS, HISTORY_LEN, type WireMaterial } from '../constants';

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
    <svg width={width} height={height} style={{ background: BG_PRIMARY, borderRadius: 6, border: `1px solid ${BORDER}` }}>
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
    { label: 'IPC connected',      ok: sysStatus?.ipc_connected ?? false },
    { label: 'M7 heartbeat OK',    ok: sysStatus?.m7_heartbeat_ok ?? false },
    { label: 'No active alarms',   ok: (sysStatus?.active_alarms ?? 1) === 0 },
    { label: 'B-code valid',       ok: steps.length > 0 },
    { label: 'Material selected',  ok: true },
    { label: 'Camera connected',   ok: sysStatus?.camera_connected ?? false, optional: true },
  ];
  const canStart = checks.filter((c) => !c.optional).every((c) => c.ok);

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
      <div style={{ background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 24, width: 420, maxWidth: '90vw' }}>
        <h3 style={{ margin: '0 0 16px', color: TEXT_PRIMARY }}>Pre-flight Check</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 20 }}>
          {checks.map((c) => (
            <div key={c.label} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 16 }}>{c.ok ? '✅' : c.optional ? '⚠️' : '❌'}</span>
              <span style={{ fontSize: 13, color: c.ok ? '#6ee7b7' : c.optional ? '#fcd34d' : '#fca5a5' }}>
                {c.label}
                {c.optional && !c.ok && ' (optional)'}
              </span>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 12, color: TEXT_MUTED, marginBottom: 16 }}>
          Material: {material.name} | Steps: {steps.length}
        </div>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onCancel} style={{ padding: '8px 16px', background: '#1e293b', border: `1px solid ${BORDER}`, color: TEXT_SECONDARY, borderRadius: 6, cursor: 'pointer', fontSize: 13 }}>Cancel</button>
          <button
            onClick={onStart}
            disabled={!canStart}
            style={{ padding: '8px 16px', background: canStart ? '#1d4ed8' : '#1e293b', border: 'none', color: canStart ? '#fff' : TEXT_MUTED, borderRadius: 6, cursor: canStart ? 'pointer' : 'not-allowed', fontSize: 13, fontWeight: 600 }}
          >
            Start Bending
          </button>
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

  const cardStyle = { background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 20 };
  const inputNum = (value: number, min: number, max: number, valid: boolean, onChange: (v: number) => void) => (
    <input
      type="number"
      value={value}
      min={min}
      max={max}
      onChange={(e) => onChange(Number(e.target.value))}
      style={{
        width: 72,
        background: BG_PRIMARY,
        border: `1px solid ${valid ? BORDER : '#ef4444'}`,
        borderRadius: 4,
        color: valid ? TEXT_PRIMARY : '#ef4444',
        padding: '4px 6px',
        fontSize: 12,
        textAlign: 'center' as const,
      }}
    />
  );

  return (
    <div style={{ padding: 'clamp(12px, 3vw, 20px)', maxWidth: 1100, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 20px', color: TEXT_PRIMARY, fontSize: 18 }}>Wire Bending</h2>

      <StepIndicator currentStep={wizardStep} />

      {/* ================================================================ */}
      {/* Step 0: Material & Wire Setup                                    */}
      {/* ================================================================ */}
      {wizardStep === 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
          <div style={cardStyle}>
            <h3 style={{ margin: '0 0 16px', fontSize: 14, color: TEXT_PRIMARY }}>Wire Profile</h3>

            <div style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 12, color: TEXT_MUTED, display: 'block', marginBottom: 6 }}>Material</label>
              <select
                value={materialId}
                onChange={(e) => setMaterialId(Number(e.target.value))}
                style={{ background: BG_PRIMARY, border: `1px solid ${BORDER}`, color: TEXT_PRIMARY, padding: '6px 10px', borderRadius: 4, fontSize: 13, width: '100%' }}
              >
                {WIRE_MATERIALS.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            </div>

            <div style={{ marginBottom: 20 }}>
              <label style={{ fontSize: 12, color: TEXT_MUTED, display: 'block', marginBottom: 6 }}>Wire Diameter</label>
              <select
                value={diameterMm}
                onChange={(e) => setDiameterMm(Number(e.target.value))}
                style={{ background: BG_PRIMARY, border: `1px solid ${BORDER}`, color: TEXT_PRIMARY, padding: '6px 10px', borderRadius: 4, fontSize: 13, width: '100%' }}
              >
                {WIRE_DIAMETERS.map((d) => (
                  <option key={d} value={d}>{d.toFixed(3)} mm</option>
                ))}
              </select>
            </div>

            <button
              onClick={() => setWizardStep(1)}
              style={{ background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 6, padding: '10px 20px', cursor: 'pointer', fontSize: 13, fontWeight: 600, width: '100%' }}
            >
              Next: B-code Editor →
            </button>
          </div>

          <div style={cardStyle}>
            <h3 style={{ margin: '0 0 16px', fontSize: 14, color: TEXT_PRIMARY }}>Material Properties</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {[
                ['Springback', material.springback],
                ['Heating',    material.heating],
                ['Speed',      material.speed],
                ['Max Angle',  `${material.maxAngle}°`],
              ].map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: `1px solid ${BORDER}` }}>
                  <span style={{ fontSize: 13, color: TEXT_MUTED }}>{k}</span>
                  <span style={{ fontSize: 13, color: TEXT_PRIMARY }}>{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ================================================================ */}
      {/* Step 1: B-code Editor                                            */}
      {/* ================================================================ */}
      {wizardStep === 1 && (
        <div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: 16, marginBottom: 16 }}>
            <div style={cardStyle}>
              <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>B-code Sequence</h3>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr>
                    {['#', 'L (mm)', 'beta (°)', 'theta (°)', ''].map((h) => (
                      <th key={h} style={{ padding: '4px 8px', textAlign: 'left', color: TEXT_MUTED, fontSize: 11, borderBottom: `1px solid ${BORDER}`, fontWeight: 600 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => {
                    const valid = isRowValid(row);
                    return (
                      <tr key={row.id}>
                        <td style={{ padding: '4px 8px', color: TEXT_MUTED }}>{i + 1}</td>
                        <td style={{ padding: '4px 8px' }}>{inputNum(row.L_mm, 0.1, 999, row.L_mm > 0, (v) => updateRow(row.id, 'L_mm', v))}</td>
                        <td style={{ padding: '4px 8px' }}>{inputNum(row.beta_deg, -180, 180, row.beta_deg >= -180 && row.beta_deg <= 180, (v) => updateRow(row.id, 'beta_deg', v))}</td>
                        <td style={{ padding: '4px 8px' }}>{inputNum(row.theta_deg, -90, 90, row.theta_deg >= -90 && row.theta_deg <= 90, (v) => updateRow(row.id, 'theta_deg', v))}</td>
                        <td style={{ padding: '4px 8px' }}>
                          <button onClick={() => removeRow(row.id)} style={{ background: 'none', border: 'none', color: '#ef4444', cursor: 'pointer', fontSize: 14 }}>✕</button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <button
                onClick={addRow}
                style={{ marginTop: 10, background: '#1e293b', border: `1px solid ${BORDER}`, color: TEXT_SECONDARY, padding: '6px 14px', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
              >
                + Add Step
              </button>

              <div style={{ marginTop: 14, padding: '10px', background: BG_PRIMARY, borderRadius: 4, display: 'flex', gap: 20, fontSize: 12, color: TEXT_MUTED }}>
                <span>Total: <strong style={{ color: TEXT_PRIMARY }}>{totalLength.toFixed(1)} mm</strong></span>
                <span>Steps: <strong style={{ color: TEXT_PRIMARY }}>{rows.length}</strong></span>
                <span>Est: <strong style={{ color: TEXT_PRIMARY }}>~{Math.ceil(totalLength / 5)}s</strong></span>
              </div>
            </div>

            <div style={{ ...cardStyle, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
              <h3 style={{ margin: '0 0 4px', fontSize: 14, color: TEXT_PRIMARY, alignSelf: 'flex-start' }}>Wire Preview</h3>
              <WirePreview steps={rows} />
              <div style={{ fontSize: 11, color: TEXT_MUTED }}>
                <span style={{ color: '#22c55e' }}>●</span> Start &nbsp;
                <span style={{ color: '#f59e0b' }}>●</span> End
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 10, justifyContent: 'space-between' }}>
            <button onClick={() => setWizardStep(0)} style={{ background: '#1e293b', border: `1px solid ${BORDER}`, color: TEXT_SECONDARY, padding: '10px 20px', borderRadius: 6, cursor: 'pointer', fontSize: 13 }}>
              ← Back
            </button>
            <button
              onClick={() => setShowPreflight(true)}
              disabled={rows.length === 0 || rows.some((r) => !isRowValid(r))}
              style={{
                background: rows.length > 0 && rows.every(isRowValid) ? '#1d4ed8' : '#1e293b',
                border: 'none',
                color: rows.length > 0 && rows.every(isRowValid) ? '#fff' : TEXT_MUTED,
                padding: '10px 20px',
                borderRadius: 6,
                cursor: rows.length > 0 && rows.every(isRowValid) ? 'pointer' : 'not-allowed',
                fontSize: 13,
                fontWeight: 600,
              }}
            >
              Execute Bending →
            </button>
          </div>
        </div>
      )}

      {/* ================================================================ */}
      {/* Step 2: Execute & Monitor                                        */}
      {/* ================================================================ */}
      {wizardStep === 2 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ ...cardStyle, display: 'flex', gap: 20, alignItems: 'center' }}>
            <span style={{ fontSize: 13, color: TEXT_MUTED }}>Material: <strong style={{ color: TEXT_PRIMARY }}>{material.name}</strong></span>
            <span style={{ fontSize: 13, color: TEXT_MUTED }}>Steps: <strong style={{ color: TEXT_PRIMARY }}>{rows.length}</strong></span>
            <StatusBadge variant="info" label={liveMotor ? ['IDLE','HOMING','RUNNING','JOGGING','STOPPING','FAULT','ESTOP'][liveMotor.state] ?? 'RUNNING' : 'RUNNING'} />
          </div>

          <div style={cardStyle}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <span style={{ fontSize: 13, color: TEXT_MUTED }}>Progress</span>
              <span style={{ fontSize: 13, color: TEXT_PRIMARY }}>
                {bendingStatus?.current_step ?? 0} / {bendingStatus?.total_steps ?? rows.length}
              </span>
            </div>
            <div style={{ height: 8, background: BG_PRIMARY, borderRadius: 4, overflow: 'hidden', marginBottom: 8 }}>
              <div style={{ height: '100%', width: `${bendingStatus?.progress_pct ?? 0}%`, background: '#3b82f6', borderRadius: 4, transition: 'width 0.5s' }} />
            </div>
            <div style={{ display: 'flex', gap: 20, fontSize: 12, color: TEXT_MUTED }}>
              <span>Elapsed: <strong style={{ color: TEXT_PRIMARY }}>{elapsedStr}</strong></span>
            </div>
          </div>

          <div style={cardStyle}>
            <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Axis Position (live)</h3>
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
          </div>

          <div style={{ display: 'flex', justifyContent: 'center' }}>
            <button
              onClick={stopBending}
              style={{ background: '#dc2626', color: '#fff', border: 'none', borderRadius: 6, padding: '12px 32px', cursor: 'pointer', fontSize: 14, fontWeight: 700, letterSpacing: 1 }}
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
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
            <div style={cardStyle}>
              <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Camera Inspection</h3>
              <div style={{ position: 'relative' }}>
                <img
                  src={cameraApi.streamUrl()}
                  alt="Inspection"
                  style={{ width: '100%', borderRadius: 4, border: `1px solid ${BORDER}` }}
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
                />
              </div>
              <button
                onClick={captureFrame}
                style={{ marginTop: 10, background: '#1e293b', border: `1px solid ${BORDER}`, color: TEXT_SECONDARY, padding: '7px 14px', borderRadius: 4, cursor: 'pointer', fontSize: 12, width: '100%' }}
              >
                Capture Frame
              </button>
            </div>

            <div style={cardStyle}>
              <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Step Summary</h3>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr>
                    {['#', 'L', 'beta', 'theta', 'Status'].map((h) => (
                      <th key={h} style={{ padding: '4px 8px', textAlign: 'left', color: TEXT_MUTED, borderBottom: `1px solid ${BORDER}`, fontWeight: 600, fontSize: 11 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr key={row.id}>
                      <td style={{ padding: '4px 8px', color: TEXT_MUTED }}>{i + 1}</td>
                      <td style={{ padding: '4px 8px', color: TEXT_PRIMARY }}>{row.L_mm}</td>
                      <td style={{ padding: '4px 8px', color: TEXT_PRIMARY }}>{row.beta_deg}°</td>
                      <td style={{ padding: '4px 8px', color: TEXT_PRIMARY }}>{row.theta_deg}°</td>
                      <td style={{ padding: '4px 8px' }}>
                        <StatusBadge variant="success" label="OK" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <button
              onClick={() => { setWizardStep(0); setRows([{ id: 1, L_mm: 10, beta_deg: 0, theta_deg: 0 }]); }}
              style={{ background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 6, padding: '10px 20px', cursor: 'pointer', fontSize: 13, fontWeight: 600 }}
            >
              New Bending
            </button>
            <button
              style={{ background: '#1e293b', border: `1px solid ${BORDER}`, color: TEXT_SECONDARY, borderRadius: 6, padding: '10px 20px', cursor: 'pointer', fontSize: 13 }}
            >
              Export CSV
            </button>
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
