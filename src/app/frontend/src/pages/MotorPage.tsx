/**
 * MotorPage.tsx — Motor control with 4 sub-tabs: Position, Driver Config, StallGuard, Diagnostics.
 */

import { useEffect, useRef, useState } from 'react';
import { usePersistentState } from '../hooks/usePersistentState';
import { motorApi, diagApi, type MotorStatus, type AxisStatus, type DriverProbeResult, type MotionProfile, type ProtectionSettings } from '../api/client';
import { ConfirmModal } from '../components/ui/ConfirmModal';
import { SliderInput } from '../components/ui/SliderInput';
import { StatusBadge } from '../components/ui/StatusBadge';
import { useMotorWs } from '../hooks/useMotorWs';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { AXIS_COLORS, AXIS_NAMES, AXIS_UNITS, BG_PANEL, BG_PRIMARY, BORDER, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, HISTORY_LEN, SAFETY_CS_MAX, SAFETY_TOFF_MIN, SAFETY_TOFF_MAX } from '../constants';
import { useSoftLimits } from '../hooks/useSoftLimits';
import { usePsuConfig } from '../hooks/usePsuConfig';
import { useAxisCalibration, AXIS_PHYSICAL_UNIT } from '../hooks/useAxisCalibration';
import { useToast } from '../components/ui/ToastSystem';
import { SignalLed } from '../components/ui/SignalLed';

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
  // Persisted (survives reload): user-chosen jog parameters, target positions
  const [jogSpeed] = usePersistentState('motor.jogSpeed', 10);   // legacy fallback
  const [stepSize] = usePersistentState('motor.stepSize', 1);    // legacy fallback

  // Per-axis motion profiles (server-persisted): jog speed / step size /
  // accel / decel / linear-vs-S-curve. Edits auto-save (debounced).
  const [profiles, setProfiles] = useState<Record<number, MotionProfile>>({});
  const profTimers = useRef<Record<number, number>>({});
  const profPending = useRef<Record<number, Partial<MotionProfile>>>({});
  useEffect(() => {
    motorApi.motionProfiles().then((r) => setProfiles(r.profiles)).catch(() => null);
  }, []);
  const axisSpeed = (axis: number) => profiles[axis]?.jog_speed ?? jogSpeed;
  const axisStep = (axis: number) => profiles[axis]?.step_size ?? stepSize;
  function patchProfile(axis: number, patch: Partial<MotionProfile>) {
    setProfiles((p) => ({ ...p, [axis]: { ...(p[axis] as MotionProfile), ...patch } }));
    profPending.current[axis] = { ...profPending.current[axis], ...patch };
    if (profTimers.current[axis]) window.clearTimeout(profTimers.current[axis]);
    profTimers.current[axis] = window.setTimeout(() => {
      const body = profPending.current[axis];
      profPending.current[axis] = {};
      motorApi.updateMotionProfile(axis, body)
        .then((r) => setProfiles((p) => ({ ...p, [axis]: r.profile })))
        .catch(() => null);
    }, 500);
  }
  // Protection / holding-torque settings (server-side runtime state)
  const [prot, setProt] = useState<ProtectionSettings | null>(null);
  const protCsTimer = useRef<number>(0);
  useEffect(() => { motorApi.protection().then(setProt).catch(() => null); }, []);
  function patchProt(patch: Partial<ProtectionSettings>, debounceMs = 0) {
    setProt((p) => (p ? { ...p, ...patch } : p));
    const send = () => motorApi.updateProtection(patch).then(setProt).catch(() => null);
    if (debounceMs > 0) {
      if (protCsTimer.current) window.clearTimeout(protCsTimer.current);
      protCsTimer.current = window.setTimeout(send, debounceMs);
    } else {
      send();
    }
  }
  const [targetAxis, setTargetAxis] = usePersistentState('motor.targetAxis', 0);
  const [targetPos, setTargetPos] = usePersistentState('motor.targetPos', 0);
  const [multiTarget, setMultiTarget] = usePersistentState<number[]>('motor.multiTarget', [0, 0, 0, 0]);
  const [softLimits] = useSoftLimits();
  // Transient: modals + error
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

  // Auto-clear stale error banners the moment the bench leaves ESTOP.
  // Without this the operator sees a "RESET first" error after they have
  // already reset, with no obvious way to dismiss it short of reload.
  const prevStateRef = useRef<number | null>(null);
  useEffect(() => {
    const cur = motorStatus?.state;
    const prev = prevStateRef.current;
    if (prev === 6 && cur !== undefined && cur !== 6) {
      setError(null);
    }
    prevStateRef.current = cur ?? null;
  }, [motorStatus?.state]);

  async function jog(axis: number, direction: 1 | -1) {
    setError(null);
    try { await motorApi.jog(axis, direction, axisSpeed(axis), axisStep(axis)); } catch (e) { setError(String(e)); }
  }

  // Long-press jog with reliable release: button DOM only registers the
  // *start*. The release listener attaches to the WINDOW so a fast tap
  // that leaves the button DOM still fires a stop. Also stops on tab
  // blur (alt-tab / minimise) so the bench never runs unattended.
  const jogActiveRef = useRef(false);

  function attachReleaseHandlers() {
    if (jogActiveRef.current) return;  // already attached
    jogActiveRef.current = true;
    const stop = () => {
      if (!jogActiveRef.current) return;
      jogActiveRef.current = false;
      motorApi.jogStop().catch(() => null);
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
      window.removeEventListener('mouseup', stop);
      window.removeEventListener('touchend', stop);
      window.removeEventListener('touchcancel', stop);
      window.removeEventListener('blur', stop);
    };
    // pointer is the modern unified event (mouse + touch + pen).
    // mouse/touch fallbacks for older browsers + iOS quirks.
    window.addEventListener('pointerup', stop, { once: true });
    window.addEventListener('pointercancel', stop, { once: true });
    window.addEventListener('mouseup', stop, { once: true });
    window.addEventListener('touchend', stop, { once: true });
    window.addEventListener('touchcancel', stop, { once: true });
    window.addEventListener('blur', stop, { once: true });
  }

  function startContinuousJog(axis: number, dir: 1 | -1) {
    // Long-press jog: 5 s backend fallback, frontend stops on pointerup.
    setError(null);
    motorApi.jogStart(axis, dir, axisSpeed(axis)).catch((e) => setError(String(e)));
    attachReleaseHandlers();
  }
  function startSingleClickRun(axis: number, dir: 1 | -1) {
    // Single-click continuous run: 60 s backend fallback, user stops with
    // the row's STOP button. No window-release listener attached.
    setError(null);
    motorApi.jogStart(axis, dir, axisSpeed(axis), { continuous: true })
      .catch((e) => setError(String(e)));
  }
  function stopContinuousJog() {
    if (jogIntervalRef.current) { clearInterval(jogIntervalRef.current); jogIntervalRef.current = null; }
    jogActiveRef.current = false;
    motorApi.jogStop().catch(() => null);
  }

  async function moveTo() {
    setError(null);
    // Absolute move — /move is relative (moves BY the value); move_to
    // travels TO the target position.
    try { await motorApi.moveTo(targetAxis, targetPos, axisSpeed(targetAxis)); } catch (e) { setError(String(e)); }
  }
  async function moveAll() {
    setShowMoveAllModal(false);
    for (let i = 0; i < 4; i++) {
      try { await motorApi.moveTo(i, multiTarget[i], axisSpeed(i)); } catch { /* continue */ }
    }
  }

  const cardStyle = { background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 16, marginBottom: 16 };
  const btnBase = { padding: '6px 12px', border: `1px solid ${BORDER}`, borderRadius: 4, cursor: 'pointer', fontSize: 13, background: '#1e293b', color: TEXT_SECONDARY };

  return (
    <div>
      {error && <div style={{ color: '#ef4444', marginBottom: 12, fontSize: 13 }}>{error}</div>}

      {/* Jog controls — long-press supported on all directional buttons.
          Disabled rows render greyed when an axis is not present in the
          current motorStatus.axes (driver disconnected or axis_mask=0). */}
      {motorStatus?.state === 6 && (
        <div style={{
          background: '#7f1d1d', border: '1px solid #ef4444', borderRadius: 6,
          padding: '10px 14px', marginBottom: 14, color: '#fca5a5', fontSize: 13,
          display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <span style={{ fontWeight: 700 }}>⛔ E-STOP active.</span>
          <span>All motion commands are blocked. Press <strong>RESET E-STOP</strong> in the header to clear.</span>
        </div>
      )}
      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Axis Jog</h3>
        {[0, 1, 2, 3].map((axisId) => {
          const ax = (motorStatus?.axes ?? []).find((a) => a.axis === axisId);
          const estopActive = motorStatus?.state === 6;
          const enabled = !!ax && !estopActive;
          const pos = ax?.position ?? 0;
          const jogBtnStyle = {
            ...btnBase,
            cursor: enabled ? 'pointer' : 'not-allowed',
            opacity: enabled ? 1 : 0.35,
            userSelect: 'none' as const,
            WebkitUserSelect: 'none' as const,
            WebkitTouchCallout: 'none' as const,
            touchAction: 'manipulation' as const,
            transition: 'transform 50ms ease, background 100ms',
          };
          // pointerdown handler; window listener handles release.
          const press = (dir: 1 | -1) => () => { if (enabled) startContinuousJog(axisId, dir); };
          return (
            <div
              key={axisId}
              style={{
                display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12,
                padding: '8px 0', borderBottom: `1px solid ${BORDER}`,
                opacity: enabled ? 1 : 0.5,
                userSelect: 'none', WebkitUserSelect: 'none',
              }}
            >
              {/* Column 1: axis name + LED cluster stacked vertically.
                  Operators asked for the 12V/EN/SG/DIR/STEP indicators to
                  sit directly under the axis label so each row reads
                  top-to-bottom as a single block. */}
              <div style={{ width: 124, display: 'flex', flexDirection: 'column' as const, gap: 4 }}>
                <div style={{ fontSize: 13, color: AXIS_COLORS[axisId], fontWeight: 600 }}>
                  {AXIS_NAMES[axisId]}
                </div>
                {(() => {
                  const sig = ax?.signals;
                  if (!sig) return <div style={{ height: 28 }} />;
                  const sgEffective = sig.sg && sig.en;
                  const dirGlyph = sig.dir > 0 ? '▶' : sig.dir < 0 ? '◀' : '';
                  const dirTone  = sig.dir > 0 ? 'blue' : sig.dir < 0 ? 'pink' : 'off';
                  return (
                    <div style={{ display: 'flex', gap: 4, alignItems: 'flex-start' }}>
                      <SignalLed label="12V"  tone={sig.vmot ? 'green' : 'red'} title="VMot 12 V (chip responsive on SPI)" />
                      <SignalLed label="EN"   tone={sig.en   ? 'green' : 'off'} title="Driver chopper enabled (init done, not silenced)" />
                      <SignalLed label="SG"   tone={sgEffective ? 'red' : 'off'} title={sig.en ? 'StallGuard2: stall detected' : 'StallGuard masked while EN=off (silenced chip always reads SG=1)'} />
                      <SignalLed label="DIR"  tone={dirTone} glyph={dirGlyph} title={`Direction line: ${sig.dir > 0 ? 'CW (+)' : sig.dir < 0 ? 'CCW (-)' : 'never driven'}`} />
                      <SignalLed label="STEP" tone={sig.step ? 'amber' : 'off'} blink={sig.step} title={sig.step ? 'PWM4 STEP active on this axis' : 'PWM idle / targeting another axis'} />
                      {sig.limit !== null && sig.limit !== undefined && (
                        <SignalLed label="LIM" tone={sig.limit ? 'red' : 'green'} blink={sig.limit} title={sig.limit ? 'Limit switch TRIPPED (PM-L25 blocked)' : 'Limit switch clear'} />
                      )}
                    </div>
                  );
                })()}
              </div>
              {(() => {
                const limit = softLimits[axisId];
                const ratio = limit > 0 ? Math.abs(pos) / limit : 0;
                const overTravel = ratio > 1;
                const nearLimit = ratio >= 0.8 && !overTravel;
                const barColor = overTravel ? '#ef4444' : nearLimit ? '#f59e0b' : AXIS_COLORS[axisId];
                const textColor = overTravel ? '#fca5a5' : nearLimit ? '#fcd34d' : enabled ? TEXT_PRIMARY : TEXT_MUTED;
                return (
                  <>
                    <span
                      style={{ width: 110, fontSize: 12, color: textColor, textAlign: 'center' as const, fontFamily: 'monospace' }}
                      title={enabled ? `Soft limit: ${limit} ${AXIS_UNITS[axisId]}` : ''}
                    >
                      {enabled
                        ? `${pos.toFixed(2)} / ${limit} ${AXIS_UNITS[axisId]}${overTravel ? ' ⚠' : ''}`
                        : 'offline'}
                    </span>
                    <div style={{ flex: 1, height: 6, background: BG_PRIMARY, borderRadius: 3, position: 'relative' as const }}>
                      <div style={{ height: '100%', width: `${Math.min(100, ratio * 100)}%`, background: barColor, borderRadius: 3, transition: 'width 0.15s, background 0.15s' }} />
                    </div>
                  </>
                );
              })()}
              {/* ◀◀  =  single-click continuous run (CCW) */}
              <button
                disabled={!enabled}
                onClick={() => { if (enabled) startSingleClickRun(axisId, -1); }}
                onContextMenu={(e) => e.preventDefault()}
                title="한 번 클릭 → 반시계방향으로 계속 회전 (정지 버튼으로 중지)"
                style={{ ...jogBtnStyle, color: '#a5b4fc', background: '#1e1b4b' }}
                className="jog-btn"
              >◀◀</button>
              {/* ◀  =  long-press jog (hold to rotate, release to stop) */}
              <button
                disabled={!enabled}
                onPointerDown={(e) => { if (enabled) { e.preventDefault(); press(-1)(); } }}
                onContextMenu={(e) => e.preventDefault()}
                title="누르고 있는 동안 반시계방향 회전"
                style={jogBtnStyle}
                className="jog-btn"
              >◀</button>
              {/* STOP  =  halt the jog ON THIS AXIS. Bench shares PWM4 across
                  all three chips so only one axis can run at a time, but the
                  per-row STOP button must still feel local: pressing BEND's
                  STOP while FEED is the jogging axis previously cancelled
                  FEED, which surprised the operator. We now enable each row's
                  STOP only when this axis is the active jog target (signals.
                  step === true). The other rows' STOP buttons are visibly
                  disabled so the operator immediately sees which one to use. */}
              {(() => {
                const isThisAxisJogging = ax?.signals?.step === true;
                const stopEnabled = enabled && isThisAxisJogging;
                return (
                  <button
                    disabled={!stopEnabled}
                    onClick={() => { if (stopEnabled) stopContinuousJog(); }}
                    title={isThisAxisJogging
                      ? `Stop ${AXIS_NAMES[axisId]} jog`
                      : `Only the active jog axis can be stopped here. ${
                          motorStatus?.axes?.find((a) => a.signals?.step)
                            ? `${AXIS_NAMES[motorStatus.axes.find((a) => a.signals?.step)!.axis]} is currently jogging.`
                            : 'No axis is jogging.'
                        }`}
                    style={{
                      ...jogBtnStyle,
                      color: stopEnabled ? '#fca5a5' : '#64748b',
                      background: stopEnabled ? '#7f1d1d' : '#1e293b',
                      border: `1px solid ${stopEnabled ? '#991b1b' : BORDER}`,
                      fontSize: 11,
                      fontWeight: 700,
                      letterSpacing: 0.5,
                      opacity: stopEnabled ? 1 : 0.5,
                      cursor: stopEnabled ? 'pointer' : 'not-allowed',
                    }}
                    className="jog-btn"
                  >STOP</button>
                );
              })()}
              {/* ▶  =  long-press jog */}
              <button
                disabled={!enabled}
                onPointerDown={(e) => { if (enabled) { e.preventDefault(); press(+1)(); } }}
                onContextMenu={(e) => e.preventDefault()}
                title="누르고 있는 동안 시계방향 회전"
                style={jogBtnStyle}
                className="jog-btn"
              >▶</button>
              {/* ▶▶  =  single-click continuous run (CW) */}
              <button
                disabled={!enabled}
                onClick={() => { if (enabled) startSingleClickRun(axisId, +1); }}
                onContextMenu={(e) => e.preventDefault()}
                title="한 번 클릭 → 시계방향으로 계속 회전 (정지 버튼으로 중지)"
                style={{ ...jogBtnStyle, color: '#a5b4fc', background: '#1e1b4b' }}
                className="jog-btn"
              >▶▶</button>
              {/* ⌂0 = 영점 설정: 현재 물리 위치를 이 축의 0으로 선언 (모션 없음) */}
              <button
                disabled={!enabled}
                onClick={async () => {
                  if (!enabled) return;
                  if (!window.confirm(`${AXIS_NAMES[axisId]} 축의 현재 위치를 0으로 설정할까요?\n(모터는 움직이지 않고 위치 카운터만 재정의됩니다)`)) return;
                  // Position display refreshes via the regular status stream.
                  try { await motorApi.setZero(axisId, 0); }
                  catch (e) { console.error('setZero failed', e); }
                }}
                title="영점 설정 — 현재 위치를 0으로 선언 (기계적 기준점에 조그로 맞춘 뒤 사용)"
                style={{ ...jogBtnStyle, fontSize: 11, fontWeight: 700, color: '#86efac', background: '#14532d', border: `1px solid #166534` }}
                className="jog-btn"
              >⌂0</button>
              {/* HOME = 리밋스위치 호밍 — 스위치 장착 축(LIFT/BEND)에만 활성.
                  스위치 없는 축은 같은 폭의 자리를 차지해 행 정렬을 유지한다. */}
              {ax?.signals?.limit !== null && ax?.signals?.limit !== undefined ? (
                <button
                  disabled={!enabled}
                  onClick={() => {
                    if (!enabled) return;
                    if (!window.confirm(`${AXIS_NAMES[axisId]} 축을 호밍할까요?\n(스위치 감지점을 0으로 설정하고 그 위치에 정착합니다)`)) return;
                    setError(null);
                    motorApi.home(1 << axisId).catch((e) => setError(String(e)));
                  }}
                  title="리밋스위치 호밍 — 창 탐색(회전축은 1회전, 직선축은 양방향) → 감지점 = 0 정착 (정지 버튼/E-STOP으로 취소)"
                  style={{ ...jogBtnStyle, width: 52, fontSize: 10, fontWeight: 700, color: '#fbbf24', background: '#451a03', border: `1px solid #92400e` }}
                  className="jog-btn"
                >HOME</button>
              ) : (
                <div style={{ width: 52 }} />
              )}
            </div>
          );
        })}
        {/* Inline style — pressed/active feedback via :active pseudo */}
        <style>{`
          .jog-btn:not(:disabled):active {
            transform: translateY(1px) scale(0.96);
            background: #2563eb !important;
            color: #fff !important;
          }
          .jog-btn:disabled { color: #475569 !important; }
        `}</style>
        {(!motorStatus || motorStatus.axes.length === 0) && (
          <div style={{ fontSize: 13, color: TEXT_MUTED, textAlign: 'center', padding: 16 }}>Waiting for motor status...</div>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16, marginBottom: 16 }}>
        <div style={{ ...cardStyle, gridColumn: '1 / -1' }}>
          <h3 style={{ margin: '0 0 4px', fontSize: 14, color: TEXT_PRIMARY }}>Per-Axis Motion Profile</h3>
          <div style={{ fontSize: 11, color: TEXT_MUTED, marginBottom: 10 }}>
            All values in axis-native units (FEED/LIFT = mm, BEND/ROTATE = deg).
            Vmax is the machine velocity limit; Accel/Decel shape the ramp;
            S-curve runs a jerk-limited smoothstep with the same peak
            acceleration. Saved on the board.
          </div>
          {Object.keys(profiles).length === 0 && (
            <div style={{ fontSize: 12, color: TEXT_MUTED }}>Loading profiles…</div>
          )}
          <div style={{ display: 'grid', gap: 6 }}>
            {(motorStatus?.axes ?? []).map((ax) => {
              const p = profiles[ax.axis];
              if (!p) return null;
              const unit = AXIS_PHYSICAL_UNIT[ax.axis] ?? 'units';
              const numBox = (
                value: number, min: number, max: number, step: number,
                onVal: (v: number) => void, width = 64,
              ) => (
                <input
                  type="number" value={value} min={min} max={max} step={step}
                  onChange={(e) => {
                    if (e.target.value === '') return;
                    const v = Number(e.target.value);
                    // Clamp instead of reject: typing "250" must not
                    // silently persist the "25" prefix.
                    if (Number.isFinite(v)) onVal(Math.min(max, Math.max(min, v)));
                  }}
                  style={{ background: BG_PRIMARY, border: `1px solid ${BORDER}`, color: TEXT_PRIMARY, padding: '4px 6px', borderRadius: 4, fontSize: 12, width }}
                />
              );
              return (
                <div key={ax.axis} style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', padding: '6px 8px', background: BG_PRIMARY, border: `1px solid ${BORDER}`, borderRadius: 6 }}>
                  <span style={{ color: AXIS_COLORS[ax.axis], fontWeight: 600, fontSize: 12, width: 58 }}>{AXIS_NAMES[ax.axis]}</span>
                  <label style={{ fontSize: 11, color: TEXT_MUTED, display: 'flex', gap: 4, alignItems: 'center' }}>
                    Speed {numBox(p.jog_speed, 0.1, 360, 0.5, (v) => patchProfile(ax.axis, { jog_speed: v }))} {unit}/s
                  </label>
                  <label title="Machine velocity limit — every motion command on this axis is clamped to it (GRBL $110-112 analog)" style={{ fontSize: 11, color: TEXT_MUTED, display: 'flex', gap: 4, alignItems: 'center' }}>
                    Vmax {numBox(p.max_speed ?? 40, 0.1, 360, 0.5, (v) => patchProfile(ax.axis, { max_speed: v }))} {unit}/s
                  </label>
                  <label style={{ fontSize: 11, color: TEXT_MUTED, display: 'flex', gap: 4, alignItems: 'center' }}>
                    Step {numBox(p.step_size, 0.01, 360, 0.1, (v) => patchProfile(ax.axis, { step_size: v }))} {unit}
                  </label>
                  <label style={{ fontSize: 11, color: TEXT_MUTED, display: 'flex', gap: 4, alignItems: 'center' }}>
                    Accel {numBox(p.accel, 1, 200, 1, (v) => patchProfile(ax.axis, { accel: v }), 60)} {unit}/s²
                  </label>
                  <label style={{ fontSize: 11, color: TEXT_MUTED, display: 'flex', gap: 4, alignItems: 'center' }}>
                    Decel {numBox(p.decel, 1, 200, 1, (v) => patchProfile(ax.axis, { decel: v }), 60)} {unit}/s²
                  </label>
                  <div style={{ display: 'flex', gap: 0, marginLeft: 'auto' }}>
                    {(['linear', 'scurve'] as const).map((s) => (
                      <button
                        key={s}
                        onClick={() => patchProfile(ax.axis, { shape: s })}
                        title={s === 'linear'
                          ? 'Trapezoidal: constant acceleration ramp'
                          : 'S-curve: jerk-limited smoothstep ramp (same peak accel, gentler start/end)'}
                        style={{
                          padding: '4px 10px', fontSize: 11, cursor: 'pointer',
                          border: `1px solid ${BORDER}`,
                          borderRadius: s === 'linear' ? '4px 0 0 4px' : '0 4px 4px 0',
                          background: p.shape === s ? '#1d4ed8' : '#1e293b',
                          color: p.shape === s ? '#fff' : TEXT_SECONDARY,
                          fontWeight: p.shape === s ? 600 : 400,
                        }}
                      >
                        {s === 'linear' ? 'Linear' : 'S-curve'}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        <div style={cardStyle}>
          <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Protection · 정지토크</h3>
          {!prot && <div style={{ fontSize: 12, color: TEXT_MUTED }}>Loading…</div>}
          {prot && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <label style={{ fontSize: 12, color: TEXT_SECONDARY, display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' }}>
                <input type="checkbox" checked={prot.limit_stop}
                  onChange={(e) => patchProt({ limit_stop: e.target.checked })} />
                이동 중 리밋센서 감지 시 자동 정지
              </label>
              <label style={{ fontSize: 12, color: TEXT_SECONDARY, display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' }}
                title="유휴 시 LIFT 코일을 통전 유지해 중력 침하를 막습니다. 통전 중 초퍼 소음(지잉)이 나는 게 정상 — 시끄러우면 아래 토크를 낮추세요.">
                <input type="checkbox" checked={prot.hold_enabled}
                  onChange={(e) => patchProt({ hold_enabled: e.target.checked })} />
                LIFT 정지토크(홀딩) — 중력 침하 방지
              </label>
              <SliderInput
                label="Hold Torque"
                value={prot.hold_cs}
                min={1} max={14} step={1} unit="CS"
                help="정지(홀딩) 전류 스케일. 낮출수록 조용하고 발열이 적지만 유지력이 줄어듭니다. LIFT가 흘러내리면 올리세요."
                onChange={(v) => patchProt({ hold_cs: v }, 500)}
              />
            </div>
          )}
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
        {(() => {
          const estopBlocked = motorStatus?.state === 6;
          const motionBtn = (extra: object) => ({
            ...extra,
            opacity: estopBlocked ? 0.4 : 1,
            cursor: estopBlocked ? 'not-allowed' as const : 'pointer' as const,
          });
          return (
            <>
              <button
                onClick={() => { if (!estopBlocked) setShowHomeModal(true); }}
                disabled={estopBlocked}
                style={motionBtn({ background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, padding: '8px 14px', fontSize: 13, fontWeight: 600 })}
              >Home All</button>
              {AXIS_NAMES.map((n, i) => {
                // Bench: only axes with a limit switch fitted are homable —
                // hide the rest instead of offering a button that errors.
                const axEntry = motorStatus?.axes.find((a) => a.axis === i);
                const hide = motorStatus
                  ? (!axEntry || (axEntry.signals ? axEntry.signals.limit == null : false))
                  : false;
                if (hide) return null;
                return (
                  <button
                    key={i}
                    onClick={() => {
                      if (estopBlocked) return;
                      setError(null);
                      motorApi.home(1 << i).catch((e) => setError(String(e)));
                    }}
                    disabled={estopBlocked}
                    style={motionBtn({ ...btnBase, fontSize: 12 })}
                  >Home {n}</button>
                );
              })}
              <button onClick={() => motorApi.stop()} style={{ ...btnBase, background: '#78350f', color: '#fcd34d' }}>Stop</button>
              <button onClick={() => motorApi.reset()} style={btnBase}>Reset Fault</button>
            </>
          );
        })()}
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
        <ConfirmModal title="Home All Axes" description="리밋 스위치가 장착된 모든 축(LIFT, BEND)을 순차 호밍합니다: 저속 접근 → 스위치 감지점 = 0 → 백오프. 와이어가 물려 있지 않은지 확인하세요. 정지 버튼/E-STOP으로 취소할 수 있습니다." confirmLabel="Home All" onConfirm={() => { setError(null); motorApi.home(0).catch((e) => setError(String(e))); setShowHomeModal(false); }} onCancel={() => setShowHomeModal(false)} />
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
  const { psu, effectiveCsMax } = usePsuConfig();
  const toast = useToast();
  const [selectedAxis, setSelectedAxis] = usePersistentState('driver.selectedAxis', 0);
  // IRUN/IHOLD persisted values are clamped to the effective cap on every
  // render — if the user lowers the PSU rating after saving a higher CS,
  // we transparently reduce the apparent value rather than driving the
  // motor with a previously-saved unsafe number. We surface a one-shot
  // toast the first time the auto-clamp engages so the operator sees it.
  const [irunRaw,  setIrunRaw ] = usePersistentState('driver.irun',  Math.min(15, effectiveCsMax));
  const [iholdRaw, setIholdRaw] = usePersistentState('driver.ihold', Math.min(8,  effectiveCsMax));
  const irun  = Math.min(irunRaw,  effectiveCsMax);
  const ihold = Math.min(iholdRaw, effectiveCsMax);
  const clampNoticeRef = useRef(false);
  useEffect(() => {
    if (clampNoticeRef.current) return;
    const messages: string[] = [];
    if (irunRaw  > effectiveCsMax) messages.push(`IRUN ${irunRaw} → ${irun}`);
    if (iholdRaw > effectiveCsMax) messages.push(`IHOLD ${iholdRaw} → ${ihold}`);
    if (messages.length > 0) {
      clampNoticeRef.current = true;
      toast.warn(`Driver Config auto-clamped by PSU ${psu.label}:\n${messages.join('\n')}`, 7000);
    }
  }, [irunRaw, iholdRaw, effectiveCsMax, irun, ihold, psu.label, toast]);
  function setIrun(v: number) {
    if (v > effectiveCsMax) {
      toast.warn(`IRUN ${v} clamped to ${effectiveCsMax} (PSU cap ${psu.label}).`);
      v = effectiveCsMax;
    }
    setIrunRaw(v);
  }
  function setIhold(v: number) {
    if (v > effectiveCsMax) {
      toast.warn(`IHOLD ${v} clamped to ${effectiveCsMax} (PSU cap ${psu.label}).`);
      v = effectiveCsMax;
    }
    setIholdRaw(v);
  }
  const [iholdDelay, setIholdDelay] = usePersistentState('driver.iholdDelay', 6);
  const [toffRaw, setToffRaw] = usePersistentState('driver.toff', Math.min(5, SAFETY_TOFF_MAX));
  const toff = Math.max(SAFETY_TOFF_MIN, Math.min(toffRaw, SAFETY_TOFF_MAX));
  function setToff(v: number) {
    if (v > SAFETY_TOFF_MAX) {
      toast.error(`TOFF ${v} blocked: hardware safety limit ${SAFETY_TOFF_MAX}. Boards burned 2026-05-08 with TOFF=15.`);
      v = SAFETY_TOFF_MAX;
    } else if (v < SAFETY_TOFF_MIN) {
      v = SAFETY_TOFF_MIN;
    }
    setToffRaw(v);
  }
  const [hstrt, setHstrt] = usePersistentState('driver.hstrt', 4);
  const [hend, setHend] = usePersistentState('driver.hend', 0);
  const [spreadCycle, setSpreadCycle] = usePersistentState('driver.spreadCycle', true);

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
          <SliderInput
            label={`IRUN (${irunToMa(irun)} mA)`}
            value={irun} min={0} max={effectiveCsMax} onChange={setIrun}
            help={`Run current scale (CS, 0-${effectiveCsMax}). Active coil current while motor is moving. Higher = more torque + heat. Capped by selected PSU (${psu.label}); hardware absolute max ${SAFETY_CS_MAX}.`}
            style={{ marginBottom: 12 }}
          />
          <SliderInput
            label={`IHOLD (${irunToMa(ihold)} mA)`}
            value={ihold} min={0} max={effectiveCsMax} onChange={setIhold}
            help={`Hold current scale. Coil current while motor is idle (holding torque). Lower than IRUN to reduce heat. Capped by PSU.`}
            style={{ marginBottom: 12 }}
          />
          <SliderInput
            label="IHOLDDELAY"
            value={iholdDelay} min={0} max={15} onChange={setIholdDelay}
            help="Time the driver waits after motion stops before stepping the current down from IRUN to IHOLD. Higher = smoother, lower = faster cool-down. Range 0-15."
          />
          <div style={{ marginTop: 10, padding: '6px 8px', background: '#0f172a', border: '1px solid #1e3a5f', borderRadius: 4, fontSize: 11, color: TEXT_MUTED }}>
            <span style={{ color: '#fcd34d' }}>⚠ Safety cap:</span> IRUN/IHOLD ≤ <strong style={{ color: '#fcd34d' }}>{effectiveCsMax}</strong> (PSU: {psu.label}, hardware max {SAFETY_CS_MAX}). Values above cap will burn the driver.
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
            <button style={applyBtn}>Apply</button>
            <button style={readBtn}>Read Back</button>
          </div>
        </div>

        <div style={cardStyle}>
          <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Chopper Settings</h3>
          <SliderInput
            label="TOFF"
            value={toff} min={SAFETY_TOFF_MIN} max={SAFETY_TOFF_MAX} onChange={setToff}
            help={`Chopper off-time (${SAFETY_TOFF_MIN}-${SAFETY_TOFF_MAX}). Sets minimum interval between current-decay phases. Max ${SAFETY_TOFF_MAX} is a HARD safety cap — boards burned 2026-05-08 with TOFF=15.`}
            style={{ marginBottom: 12 }}
          />
          <SliderInput
            label="HSTRT"
            value={hstrt} min={0} max={7} onChange={setHstrt}
            help="Hysteresis start (0-7). Where the driver begins ramping current at the start of each chopper cycle. Tune for low audible noise."
            style={{ marginBottom: 12 }}
          />
          <SliderInput
            label="HEND"
            value={hend} min={-3} max={12} onChange={setHend}
            help="Hysteresis end (-3..+12). End-of-decay current target. Combined with HSTRT controls chopper waveform smoothness."
            style={{ marginBottom: 12 }}
          />
          <div style={{ marginTop: 4, padding: '6px 8px', background: '#0f172a', border: '1px solid #1e3a5f', borderRadius: 4, fontSize: 11, color: TEXT_MUTED, marginBottom: 8 }}>
            <span style={{ color: '#fcd34d' }}>⚠ Safety cap:</span> TOFF ≤ <strong style={{ color: '#fcd34d' }}>{SAFETY_TOFF_MAX}</strong>. Values above thermally damage the FETs (boards burned 2026-05-08 with TOFF=15).
          </div>
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
  const [sgThresholds, setSgThresholds] = usePersistentState<number[]>('stallguard.thresholds', [0, 0, 0, 0]);
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
  const [subTab, setSubTab] = usePersistentState<MotorSubTab>('motor.subTab', 'position');
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

  async function handleProbe() {
    setProbing(true);
    try { const r = await diagApi.probe(); setProbeResults(r.drivers); }
    catch { /* ignore */ }
    finally { setProbing(false); }
  }

  return (
    <div style={{ padding: 'clamp(12px, 3vw, 20px)', maxWidth: 1100, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '0 0 4px' }}>
        <h2 style={{ margin: 0, color: TEXT_PRIMARY, fontSize: 18 }}>Motor Control</h2>
        <button
          onClick={() => {
            if (!confirm('Reset cached motor settings (jog speed, step size, targets, IRUN/IHOLD, SG thresholds)?\n\nThis only clears the dashboard’s local cache; physical motor positions are not affected.')) return;
            const prefix = 'ortho-bender:';
            ['motor.jogSpeed','motor.stepSize','motor.targetAxis','motor.targetPos','motor.multiTarget',
             'driver.selectedAxis','driver.irun','driver.ihold','driver.iholdDelay',
             'driver.toff','driver.hstrt','driver.hend','driver.spreadCycle',
             'stallguard.thresholds']
              .forEach((k) => localStorage.removeItem(prefix + k));
            window.location.reload();
          }}
          style={{ background: 'transparent', border: `1px solid ${BORDER}`, color: TEXT_MUTED, borderRadius: 4, padding: '4px 12px', cursor: 'pointer', fontSize: 12 }}
          title="Clear cached jog/driver/SG settings stored in this browser"
        >Reset cache</button>
      </div>
      <div style={{ fontSize: 13, color: TEXT_MUTED, marginBottom: 14 }}>
        <span title="Motion state: IDLE = no motion, JOGGING = jog running, RUNNING = sequence executing, HOMING = StallGuard2 homing, STOPPING = decelerating, FAULT/ESTOP = error.">
          State: <strong style={{ color: TEXT_PRIMARY }}>
            {motorStatus ? (['IDLE','HOMING','RUNNING','JOGGING','STOPPING','FAULT','ESTOP'][motorStatus.state] ?? '?') : '—'}
          </strong>
        </span>
        &nbsp;|&nbsp;
        <span title="B-code bending sequence progress: current step / total steps. 0/0 means no bending sequence is active — jog/move operations do not increment this.">
          Step: <strong style={{ color: TEXT_PRIMARY }}>
            {motorStatus ? `${motorStatus.current_step} / ${motorStatus.total_steps}` : '—'}
          </strong>
          <span style={{ color: TEXT_MUTED, marginLeft: 6, fontSize: 11 }}>(B-code only)</span>
        </span>
      </div>

      {/* Driver Connection + Power Control */}
      <div style={{
        background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 6,
        padding: 14, marginBottom: 18,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <span style={{ fontSize: 13, color: TEXT_SECONDARY, fontWeight: 600 }}>Driver Connection</span>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button
              onClick={handleProbe}
              disabled={probing}
              style={{ background: '#334155', color: TEXT_SECONDARY, border: `1px solid ${BORDER}`, borderRadius: 4, padding: '4px 10px', cursor: 'pointer', fontSize: 11 }}
            >
              {probing ? 'Probing...' : 'Re-Probe'}
            </button>
            <button
              onClick={async () => {
                if (motorStatus?.driver_enabled) {
                  setShowDisableModal(true);
                } else {
                  await motorApi.enable(); await refreshMotor();
                }
              }}
              disabled={isMoving}
              style={{
                background: motorStatus?.driver_enabled ? '#065f46' : '#334155',
                color: motorStatus?.driver_enabled ? '#6ee7b7' : TEXT_MUTED,
                border: `1px solid ${motorStatus?.driver_enabled ? '#10b981' : BORDER}`,
                borderRadius: 4, padding: '4px 12px', cursor: isMoving ? 'not-allowed' : 'pointer',
                fontSize: 11, fontWeight: 600,
                opacity: isMoving ? 0.6 : 1,
              }}
            >
              {motorStatus?.driver_enabled ? 'ENERGIZED' : 'Enable Drivers'}
            </button>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {probeResults.length === 0 ? (
            <span style={{ fontSize: 12, color: TEXT_MUTED }}>Probing drivers...</span>
          ) : probeResults.map(p => (
            <div key={p.driver} style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '5px 10px', borderRadius: 5,
              background: p.connected ? '#064e3b' : '#450a0a',
              border: `1px solid ${p.connected ? '#10b981' : '#ef4444'}`,
            }}>
              <span style={{
                width: 7, height: 7, borderRadius: '50%',
                background: p.connected ? '#10b981' : '#ef4444',
              }} />
              <span style={{ fontSize: 12, color: TEXT_PRIMARY, fontWeight: 600 }}>{p.driver}</span>
              <span style={{ fontSize: 11, color: p.connected ? '#6ee7b7' : '#fca5a5' }}>
                {p.connected ? p.chip : 'NOT FOUND'}
              </span>
            </div>
          ))}
        </div>
      </div>

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
