/**
 * CameraPage.tsx — Camera control with 4 sub-tabs: Live, Acquisition, Processing, Gallery.
 */

import { useEffect, useRef, useState } from 'react';
import { cameraApi, type CameraControl, type CameraPreset, type CameraRoiInfo, type CameraStatus } from '../api/client';
import { usePersistentState } from '../hooks/usePersistentState';
import { ConnectionControl } from '../components/ui/ConnectionControl';
import { SliderInput } from '../components/ui/SliderInput';
import { StatusBadge } from '../components/ui/StatusBadge';
import { useCameraWs } from '../hooks/useCameraWs';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { BG_PANEL, BG_PRIMARY, BORDER, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED } from '../constants';

type PanelSectionId = 'tuning' | 'acquisition' | 'params' | 'presets' | 'gallery';

const PANEL_SECTIONS: { id: PanelSectionId; label: string; icon: string }[] = [
  { id: 'tuning',      label: 'Live Tuning',      icon: '🎚' },
  { id: 'acquisition', label: 'Acquisition',      icon: '📷' },
  { id: 'params',      label: 'Parameters',       icon: '🎛' },
  { id: 'presets',     label: 'Presets',          icon: '💾' },
  { id: 'gallery',     label: 'Gallery',          icon: '🗂' },
];

function CollapsibleSection({ label, icon, open, onToggle, children }: {
  label: string; icon: string; open: boolean; onToggle: () => void; children: React.ReactNode;
}) {
  return (
    <div style={{ borderBottom: `1px solid ${BORDER}` }}>
      <button onClick={onToggle} style={{
        display: 'flex', alignItems: 'center', gap: 8, width: '100%',
        padding: '10px 14px', background: open ? '#16213a' : 'transparent',
        border: 'none', cursor: 'pointer', color: TEXT_PRIMARY, fontSize: 13,
        fontWeight: 600, textAlign: 'left' as const,
      }}>
        <span style={{
          display: 'inline-block', transition: 'transform 0.2s ease',
          transform: open ? 'rotate(90deg)' : 'none', color: '#3b82f6', fontSize: 11,
        }}>▶</span>
        <span style={{ fontSize: 13 }}>{icon}</span>
        {label}
      </button>
      {open && (
        <div style={{ padding: '10px 12px 14px', animation: 'cam-section-in 0.18s ease' }}>
          {children}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Live & Capture
// ---------------------------------------------------------------------------

function LiveTuningCard({ status, onApply }: { status: CameraStatus | null; onApply: () => void }) {
  // Sliders auto-apply (debounced) so exposure/gain can be judged against
  // the always-visible stream.
  const [liveExp, setLiveExp] = useState(20000);
  const [liveGain, setLiveGain] = useState(0);
  const [sensorFps, setSensorFps] = useState<number | ''>('');
  const [tuneMsg, setTuneMsg] = useState('');
  const tuneTimer = useRef<number | null>(null);
  const lastTouch = useRef(0);
  const pending = useRef<{ exposure_us?: number; gain_db?: number }>({});

  // Follow the camera's real values unless the user touched a slider
  // in the last few seconds (the 3 s status poll would fight the drag).
  useEffect(() => {
    if (Date.now() - lastTouch.current < 4000) return;
    const exp = status?.exposure_us ?? status?.current_exposure_us;
    const gain = status?.gain_db ?? status?.current_gain_db;
    if (exp != null) setLiveExp(Math.round(exp));
    if (gain != null) setLiveGain(gain);
  }, [status]);

  useEffect(() => {
    cameraApi.framerate().then((r) => { if (r.fps != null) setSensorFps(Math.round(r.fps * 10) / 10); }).catch(() => null);
  }, []);

  function queueTune(patch: { exposure_us?: number; gain_db?: number }) {
    lastTouch.current = Date.now();
    pending.current = { ...pending.current, ...patch };
    if (tuneTimer.current != null) window.clearTimeout(tuneTimer.current);
    tuneTimer.current = window.setTimeout(async () => {
      const body = pending.current;
      pending.current = {};
      try {
        await cameraApi.settings(body);
        setTuneMsg(`적용됨 ${new Date().toLocaleTimeString()}`);
        onApply();
      } catch (e) {
        setTuneMsg(`적용 실패: ${String(e)}`);
      }
    }, 400);
  }

  async function applyFps() {
    if (sensorFps === '') return;
    try {
      const r = await cameraApi.setFramerate(Number(sensorFps));
      if (r.fps != null) setSensorFps(Math.round(r.fps * 10) / 10);
      setTuneMsg(`센서 ${r.fps?.toFixed(1)} fps 적용됨`);
      onApply();
    } catch (e) { setTuneMsg(`fps 적용 실패: ${String(e)}`); }
  }

  return (
    <div>
      <div style={{ fontSize: 11, color: tuneMsg.startsWith('적용 실패') || tuneMsg.startsWith('fps 적용 실패') ? '#ef4444' : TEXT_MUTED, marginBottom: 6 }}>
        {tuneMsg || '슬라이더를 움직이면 자동 적용됩니다'}
      </div>
      <SliderInput label="Exposure" value={liveExp} min={20} max={100000} step={100} unit="μs"
        onChange={(v: number) => { setLiveExp(v); queueTune({ exposure_us: v }); }} />
      <SliderInput label="Gain" value={liveGain} min={0} max={48} step={0.5} unit="dB"
        onChange={(v: number) => { setLiveGain(v); queueTune({ gain_db: v }); }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
        <span style={{ fontSize: 12, color: TEXT_SECONDARY }}>Sensor FPS</span>
        <input type="number" min={1} max={500} value={sensorFps}
          onChange={(e) => setSensorFps(e.target.value === '' ? '' : Number(e.target.value))}
          style={{ width: 80, background: '#0f172a', color: TEXT_PRIMARY, border: `1px solid ${BORDER}`, borderRadius: 4, padding: '4px 6px', fontSize: 12 }} />
        <button onClick={applyFps}
          style={{ background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, padding: '4px 12px', cursor: 'pointer', fontSize: 12 }}>
          적용
        </button>
        <span style={{ fontSize: 11, color: TEXT_MUTED }}>낮출수록 노출 상한이 올라갑니다</span>
      </div>
    </div>
  );
}

function LiveCapture({ status }: { status: CameraStatus | null }) {
  // Key is versioned: the old 'camera.useWs' could get stuck true forever
  // after a single MJPEG error (e.g. a server restart mid-stream).
  const [useWs, setUseWs] = usePersistentState('camera.useWs.v2', false);
  const [zoom, setZoom] = usePersistentState('camera.zoom', 1);
  const [showCrosshair, setShowCrosshair] = usePersistentState('camera.showCrosshair', false);
  const [frameCount, setFrameCount] = useState(0);
  const [streamRetry, setStreamRetry] = useState(0);
  const wsFrame = useCameraWs(useWs);

  useEffect(() => { if (wsFrame) setFrameCount((c) => c + 1); }, [wsFrame]);

  function capture() {
    const link = document.createElement('a');
    link.href = cameraApi.captureUrl();
    link.download = `frame_${Date.now()}.jpg`;
    link.click();
  }

  const streamSrc = cameraApi.streamUrl();

  return (
    <div>
      <div style={{ position: 'relative', background: '#000', borderRadius: 8, overflow: 'hidden', marginBottom: 12, minHeight: 200, maxHeight: 400, border: `1px solid ${BORDER}` }}>
        {/* Stream */}
        {!useWs ? (
          <img
            key={streamRetry}
            src={`${streamSrc}${streamSrc.includes('?') ? '&' : '?'}r=${streamRetry}`}
            alt="Camera stream"
            style={{ width: '100%', maxHeight: 400, objectFit: 'contain', display: 'block', transform: `scale(${zoom})`, transformOrigin: 'center center' }}
            onError={() => {
              // A dropped MJPEG stream (server restart, camera reconnect) is
              // transient — retry with a cache-busted URL instead of
              // permanently switching to the WS fallback.
              setTimeout(() => setStreamRetry((k) => k + 1), 2000);
            }}
          />
        ) : wsFrame ? (
          <img
            src={`data:image/jpeg;base64,${wsFrame}`}
            alt="WS frame"
            style={{ width: '100%', maxHeight: 400, objectFit: 'contain', display: 'block', transform: `scale(${zoom})` }}
          />
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 240, color: TEXT_MUTED, fontSize: 13 }}>
            No camera signal
          </div>
        )}

        {/* Crosshair */}
        {showCrosshair && (
          <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
            <div style={{ position: 'absolute', top: '50%', left: 0, right: 0, height: 1, background: 'rgba(255,255,0,0.5)' }} />
            <div style={{ position: 'absolute', top: 0, bottom: 0, left: '50%', width: 1, background: 'rgba(255,255,0,0.5)' }} />
          </div>
        )}

        {/* HUD - top-left (flat bench schema with premium-shape fallback) */}
        {status && (
          <div style={{ position: 'absolute', top: 8, left: 8, background: 'rgba(0,0,0,0.6)', borderRadius: 4, padding: '4px 8px', fontSize: 11, color: TEXT_PRIMARY }}>
            {status.width && status.height ? `${status.width}×${status.height}`
              : status.current_roi ? `${status.current_roi.width}×${status.current_roi.height}` : '—'}
            &nbsp;|&nbsp; {(status.fps ?? status.current_fps)?.toFixed(1) ?? '—'} fps
            &nbsp;|&nbsp; {status.format ?? status.current_pixel_format ?? '—'}
          </div>
        )}

        {/* HUD - top-right */}
        {status && (() => {
          const exp = status.exposure_us ?? status.current_exposure_us;
          const gain = status.gain_db ?? status.current_gain_db;
          const temp = status.temperature_c ?? status.current_temperature_c;
          return (
            <div style={{ position: 'absolute', top: 8, right: 8, background: 'rgba(0,0,0,0.6)', borderRadius: 4, padding: '4px 8px', fontSize: 11, color: TEXT_PRIMARY, textAlign: 'right' as const }}>
              Exp: {exp != null ? (exp >= 1000 ? `${(exp / 1000).toFixed(1)} ms` : `${exp.toFixed(0)} μs`) : '—'}
              &nbsp;|&nbsp; Gain: {gain?.toFixed(1) ?? '—'} dB
              {temp != null && <> &nbsp;|&nbsp; {temp.toFixed(1)}°C</>}
            </div>
          );
        })()}

        {/* HUD - bottom-right */}
        <div style={{ position: 'absolute', bottom: 8, right: 8, background: 'rgba(0,0,0,0.6)', borderRadius: 4, padding: '4px 8px', fontSize: 10, color: '#94a3b8' }}>
          {new Date().toLocaleTimeString()}
        </div>
      </div>

      {/* Controls */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {[1, 2, 4].map((z) => (
            <button key={z} onClick={() => setZoom(z)} style={{ padding: '5px 12px', background: zoom === z ? '#1e3a5f' : '#1e293b', border: `1px solid ${zoom === z ? '#3b82f6' : BORDER}`, color: zoom === z ? '#93c5fd' : TEXT_MUTED, borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: zoom === z ? 600 : 400 }}>
              {z}x
            </button>
          ))}
        </div>
        <button onClick={() => setShowCrosshair(!showCrosshair)} style={{ padding: '5px 12px', background: showCrosshair ? '#1e3a5f' : '#1e293b', border: `1px solid ${showCrosshair ? '#3b82f6' : BORDER}`, color: showCrosshair ? '#93c5fd' : TEXT_MUTED, borderRadius: 4, cursor: 'pointer', fontSize: 12 }}>
          Crosshair
        </button>
        <button onClick={capture} style={{ padding: '5px 14px', background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>
          Capture
        </button>
        {/* Recording removed — was a UI-only dummy; server-side recording is
            tracked as a future feature. */}
      </div>

      {/* Status bar */}
      <div style={{ display: 'flex', gap: 14, fontSize: 12, color: TEXT_MUTED }}>
        <StatusBadge variant={status?.connected ? 'success' : 'error'} label={status?.connected ? 'Connected' : 'Disconnected'} />
        <span>{status?.device_id ?? (status?.device ? `${status.device.vendor} ${status.device.model}` : '—')}</span>
        <span>Frames: {frameCount}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Acquisition
// ---------------------------------------------------------------------------

function Acquisition({ status, onApply }: { status: CameraStatus | null; onApply: () => void }) {
  const [exposureUs, setExposureUs] = useState(
    status?.exposure_us ?? status?.current_exposure_us ?? 5000);
  const [exposureAuto, setExposureAuto] = useState(false);
  const [gainDb, setGainDb] = useState(status?.gain_db ?? status?.current_gain_db ?? 0);
  const [gainAuto, setGainAuto] = useState(false);
  const dirty = useRef(false);

  // Track the camera's real values so remounting this tab (or another
  // view changing settings) doesn't silently reset the controls to
  // defaults. User edits win until the next Apply.
  useEffect(() => {
    if (dirty.current) return;
    const exp = status?.exposure_us ?? status?.current_exposure_us;
    const gain = status?.gain_db ?? status?.current_gain_db;
    if (exp != null) setExposureUs(Math.round(exp));
    if (gain != null) setGainDb(gain);
  }, [status]);
  const [trigger, setTrigger] = useState<'freerun' | 'software' | 'external'>('freerun');
  const [fpsEnabled, setFpsEnabled] = useState(false);
  const [fps, setFps] = useState(15);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function apply() {
    setApplying(true);
    try {
      await cameraApi.settings({ exposure_us: exposureAuto ? undefined : exposureUs, gain_db: gainAuto ? undefined : gainDb });
      dirty.current = false;
      onApply();
    } catch (e) { setError(String(e)); }
    finally { setApplying(false); }
  }

  const cardStyle = { background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 16, marginBottom: 16 };
  const applyBtn = { background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, padding: '6px 14px', cursor: 'pointer', fontSize: 12, fontWeight: 600, marginTop: 12 };
  const radioStyle = { accentColor: '#3b82f6' };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Exposure</h3>
        <div style={{ display: 'flex', gap: 12, marginBottom: 10 }}>
          {(['Manual', 'Auto'] as const).map((m) => (
            <label key={m} style={{ display: 'flex', gap: 6, fontSize: 13, color: TEXT_SECONDARY, cursor: 'pointer' }}>
              <input type="radio" style={radioStyle} checked={exposureAuto === (m === 'Auto')} onChange={() => setExposureAuto(m === 'Auto')} />
              {m}
            </label>
          ))}
        </div>
        {!exposureAuto && <SliderInput label="ExposureTime" value={exposureUs} min={20} max={100000} step={100} unit="μs" onChange={(v: number) => { dirty.current = true; setExposureUs(v); }} />}
        <button onClick={apply} disabled={applying} style={{ ...applyBtn, display: 'flex', alignItems: 'center', gap: 6, opacity: applying ? 0.7 : 1 }}>
          {applying && <span style={{ display: 'inline-block', width: 12, height: 12, border: '2px solid rgba(255,255,255,0.3)', borderTop: '2px solid #fff', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />}
          Apply
        </button>
        {error && <div style={{ fontSize: 12, color: '#ef4444', marginTop: 8 }}>{error}</div>}
      </div>

      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Gain</h3>
        <div style={{ display: 'flex', gap: 12, marginBottom: 10 }}>
          {(['Manual', 'Auto'] as const).map((m) => (
            <label key={m} style={{ display: 'flex', gap: 6, fontSize: 13, color: TEXT_SECONDARY, cursor: 'pointer' }}>
              <input type="radio" style={radioStyle} checked={gainAuto === (m === 'Auto')} onChange={() => setGainAuto(m === 'Auto')} />
              {m}
            </label>
          ))}
        </div>
        {!gainAuto && <SliderInput label="Gain" value={gainDb} min={0} max={48} step={0.5} unit="dB" onChange={(v: number) => { dirty.current = true; setGainDb(v); }} />}
        <button onClick={apply} disabled={applying} style={applyBtn}>Apply</button>
      </div>

      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Trigger</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
          {(['freerun', 'software', 'external'] as const).map((t) => (
            <label key={t} style={{ display: 'flex', gap: 8, fontSize: 13, color: TEXT_SECONDARY, cursor: 'pointer' }}>
              <input type="radio" style={radioStyle} checked={trigger === t} onChange={() => setTrigger(t)} />
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </label>
          ))}
        </div>
        {trigger === 'software' && (
          <button style={{ background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, padding: '6px 14px', cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>
            Software Trigger
          </button>
        )}
      </div>

      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Frame Rate</h3>
        <label style={{ display: 'flex', gap: 8, fontSize: 13, color: TEXT_SECONDARY, marginBottom: 12, cursor: 'pointer' }}>
          <input type="checkbox" checked={fpsEnabled} onChange={(e) => setFpsEnabled(e.target.checked)} style={radioStyle} />
          Enable Frame Rate Limit
        </label>
        {fpsEnabled && <SliderInput label="Frame Rate" value={fps} min={1} max={30} unit="fps" onChange={setFps} />}
        <button style={{ background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, padding: '6px 14px', cursor: 'pointer', fontSize: 12, fontWeight: 600, marginTop: 12 }}>Apply</button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ROI — sensor crop (subdev selection API; not part of /controls)
// ---------------------------------------------------------------------------

function RoiCard({ onApply }: { onApply: () => void }) {
  const [info, setInfo] = useState<CameraRoiInfo | null>(null);
  const [left, setLeft] = useState(0);
  const [top, setTop] = useState(0);
  const [width, setWidth] = useState(0);
  const [height, setHeight] = useState(0);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  async function load() {
    try {
      const r = await cameraApi.roi();
      setInfo(r);
      setLeft(r.crop.left); setTop(r.crop.top);
      setWidth(r.crop.width); setHeight(r.crop.height);
    } catch (e) { setMsg(String(e)); }
  }
  useEffect(() => { load(); }, []);

  async function apply(rect: { left: number; top: number; width: number; height: number }) {
    setBusy(true);
    setMsg('적용 중… (스트림 재시작)');
    try {
      const r = await cameraApi.setRoi(rect);
      setInfo(r);
      setLeft(r.crop.left); setTop(r.crop.top);
      setWidth(r.crop.width); setHeight(r.crop.height);
      setMsg(`적용됨: (${r.crop.left},${r.crop.top}) ${r.crop.width}×${r.crop.height}`);
      onApply();
    } catch (e) { setMsg(`실패: ${String(e)}`); }
    finally { setBusy(false); }
  }

  const numStyle = { width: 74, background: '#0f172a', color: TEXT_PRIMARY, border: `1px solid ${BORDER}`, borderRadius: 4, padding: '4px 6px', fontSize: 12 };
  const b = info?.bounds;
  return (
    <div style={{ background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 14, marginBottom: 14 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 8 }}>
        <h3 style={{ margin: 0, fontSize: 14, color: TEXT_PRIMARY }}>ROI / 센서 영역</h3>
        {b && <span style={{ fontSize: 11, color: TEXT_MUTED }}>센서 최대 {b.width}×{b.height}</span>}
      </div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'end', marginBottom: 8 }}>
        {[['Offset X', left, setLeft], ['Offset Y', top, setTop], ['Width', width, setWidth], ['Height', height, setHeight]].map(([lab, val, set]) => (
          <label key={String(lab)} style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 11, color: TEXT_MUTED }}>
            {String(lab)}
            <input type="number" style={numStyle} value={Number(val)} min={0}
              onChange={(e) => (set as (n: number) => void)(Number(e.target.value))} />
          </label>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button disabled={busy} onClick={() => apply({ left, top, width, height })}
          style={{ background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, padding: '5px 14px', cursor: 'pointer', fontSize: 12, fontWeight: 600, opacity: busy ? 0.6 : 1 }}>
          Apply
        </button>
        <button disabled={busy || !info} onClick={() => info && apply({ ...info.default })}
          style={{ background: '#1e293b', color: TEXT_SECONDARY, border: `1px solid ${BORDER}`, borderRadius: 4, padding: '5px 12px', cursor: 'pointer', fontSize: 12 }}>
          Full Frame
        </button>
        <span style={{ fontSize: 11, color: msg.startsWith('실패') ? '#ef4444' : TEXT_MUTED }}>{msg}</span>
      </div>
      <div style={{ fontSize: 11, color: TEXT_MUTED, marginTop: 6 }}>
        ROI를 줄이면 프레임레이트 상승 여지가 생기고 대역폭이 줄어듭니다. 드라이버가 정렬 단위로 값을 보정할 수 있습니다 (적용값 표시).
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Parameters — full driver control surface, rendered dynamically
// ---------------------------------------------------------------------------

/** Human-readable unit conversions for known raw driver units. */
function controlHint(name: string, value: number | string | null): string {
  if (typeof value !== 'number') return '';
  if (/^Exposure($| A)/.test(name)) return value >= 1e6 ? `= ${(value / 1e6).toFixed(1)} ms` : `= ${(value / 1e3).toFixed(1)} μs`;
  if (/^Gain/.test(name)) return `= ${(value / 100).toFixed(1)} dB`;
  if (name === 'Gamma') return `= ${(value / 100).toFixed(2)}`;
  if (name === 'Device Temperature') return `= ${(value / 10).toFixed(1)} °C`;
  return '';
}

function ParametersTab() {
  const [controls, setControls] = useState<CameraControl[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [rowMsg, setRowMsg] = useState<Record<number, string>>({});
  const timers = useRef<Record<number, number>>({});

  async function load() {
    setLoading(true);
    try {
      const r = await cameraApi.controls();
      setControls(r.controls);
      setError(null);
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function applyNow(c: CameraControl, value: number) {
    try {
      const r = await cameraApi.setControl(c.id, value);
      setRowMsg((m) => ({ ...m, [c.id]: r.value != null ? `→ ${r.value}` : '✓' }));
      setControls((cs) => cs.map((x) => x.id === c.id && r.value != null ? { ...x, value: r.value } : x));
    } catch (e) {
      setRowMsg((m) => ({ ...m, [c.id]: `실패: ${String(e)}` }));
    }
  }

  function queueApply(c: CameraControl, value: number, debounceMs = 400) {
    setControls((cs) => cs.map((x) => (x.id === c.id ? { ...x, value } : x)));
    if (timers.current[c.id]) window.clearTimeout(timers.current[c.id]);
    timers.current[c.id] = window.setTimeout(() => applyNow(c, value), debounceMs);
  }

  function widget(c: CameraControl) {
    const disabled = c.read_only || c.inactive;
    if (c.type === 'string') {
      return <span style={{ fontSize: 12, color: TEXT_SECONDARY }}>{String(c.value ?? '—')}</span>;
    }
    if (c.type === 'button') {
      return (
        <button disabled={disabled} onClick={() => applyNow(c, 1)}
          style={{ padding: '4px 14px', background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, opacity: disabled ? 0.5 : 1 }}>
          실행
        </button>
      );
    }
    if (c.type === 'bool') {
      return (
        <input type="checkbox" disabled={disabled} checked={c.value === 1}
          style={{ accentColor: '#3b82f6', width: 16, height: 16 }}
          onChange={(e) => queueApply(c, e.target.checked ? 1 : 0, 0)} />
      );
    }
    if ((c.type === 'menu' || c.type === 'int_menu') && c.menu) {
      return (
        <select disabled={disabled} value={Number(c.value ?? c.default)}
          onChange={(e) => queueApply(c, Number(e.target.value), 0)}
          style={{ background: '#0f172a', color: TEXT_PRIMARY, border: `1px solid ${BORDER}`, borderRadius: 4, padding: '4px 8px', fontSize: 12 }}>
          {Object.entries(c.menu).map(([k, label]) => (
            <option key={k} value={k}>{label}</option>
          ))}
        </select>
      );
    }
    if (Array.isArray(c.value)) {
      // Compound controls, e.g. "Binning Setting" (AREA: width x height)
      return (
        <span style={{ display: 'flex', gap: 6 }}>
          {c.value.map((v, i) => (
            <input key={i} type="number" value={v} disabled={disabled}
              style={{ width: 64, background: '#0f172a', color: TEXT_PRIMARY, border: `1px solid ${BORDER}`, borderRadius: 4, padding: '4px 6px', fontSize: 12 }}
              onChange={(e) => {
                const next = [...(c.value as number[])];
                next[i] = Number(e.target.value);
                setControls((cs) => cs.map((x) => (x.id === c.id ? { ...x, value: next } : x)));
                if (timers.current[c.id]) window.clearTimeout(timers.current[c.id]);
                timers.current[c.id] = window.setTimeout(async () => {
                  try {
                    const r = await cameraApi.setControl(c.id, next);
                    setRowMsg((m) => ({ ...m, [c.id]: `→ ${JSON.stringify(r.value)}` }));
                    if (Array.isArray(r.value)) {
                      setControls((cs) => cs.map((x) => (x.id === c.id ? { ...x, value: r.value as number[] } : x)));
                    }
                  } catch (err2) {
                    setRowMsg((m) => ({ ...m, [c.id]: `실패: ${String(err2)}` }));
                  }
                }, 700);
              }} />
          ))}
        </span>
      );
    }
    if (c.type === 'int' || c.type === 'int64') {
      if (c.read_only) {
        return <span style={{ fontSize: 12, color: TEXT_SECONDARY }}>{String(c.value ?? '—')}</span>;
      }
      const span = (c.max - c.min) / (c.step || 1);
      if (span > 0 && span <= 5000) {
        return (
          <input type="range" min={c.min} max={c.max} step={c.step || 1}
            value={Number(c.value ?? c.default)} disabled={disabled}
            style={{ width: 180, accentColor: '#3b82f6' }}
            onChange={(e) => queueApply(c, Number(e.target.value))} />
        );
      }
      return (
        <input type="number" min={c.min} max={c.max} step={c.step || 1}
          value={Number(c.value ?? c.default)} disabled={disabled}
          style={{ width: 130, background: '#0f172a', color: TEXT_PRIMARY, border: `1px solid ${BORDER}`, borderRadius: 4, padding: '4px 8px', fontSize: 12 }}
          onChange={(e) => queueApply(c, Number(e.target.value), 700)} />
      );
    }
    return <span style={{ fontSize: 11, color: TEXT_MUTED }}>(미지원 타입)</span>;
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={{ fontSize: 12, color: TEXT_MUTED }}>
          카메라 드라이버가 노출하는 전체 파라미터입니다 — 값 변경 시 즉시 적용됩니다 (원시 단위, 힌트 병기)
        </span>
        <button onClick={load} disabled={loading}
          style={{ padding: '5px 14px', background: '#1e293b', border: `1px solid ${BORDER}`, color: TEXT_SECONDARY, borderRadius: 4, cursor: 'pointer', fontSize: 12 }}>
          {loading ? '갱신 중…' : '새로고침'}
        </button>
      </div>
      {error && <div style={{ fontSize: 12, color: '#ef4444', marginBottom: 10 }}>{error}</div>}
      <div style={{ background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 8, overflow: 'hidden' }}>
        {controls.map((c) => c.type === 'ctrl_class' ? (
          <div key={c.id} style={{ padding: '8px 16px', background: '#0f172a', fontSize: 12, fontWeight: 600, color: TEXT_PRIMARY, borderTop: `1px solid ${BORDER}` }}>
            {c.name}
          </div>
        ) : (
          <div key={c.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '7px 16px', borderTop: `1px solid ${BORDER}`, opacity: c.inactive ? 0.45 : 1 }}>
            <span style={{ flex: '0 0 220px', fontSize: 12, color: TEXT_SECONDARY }}>
              {c.name}{c.read_only && <span style={{ color: TEXT_MUTED }}> (읽기전용)</span>}
            </span>
            <span style={{ flex: '0 0 auto' }}>{widget(c)}</span>
            {(c.type === 'int' || c.type === 'int64') && !c.read_only && (
              <span style={{ fontSize: 11, color: TEXT_MUTED, minWidth: 90 }}>
                {String(c.value ?? '—')} <span style={{ color: '#64748b' }}>[{c.min}–{c.max}]</span>
              </span>
            )}
            <span style={{ fontSize: 11, color: '#60a5fa' }}>{Array.isArray(c.value) ? '' : controlHint(c.name, c.value)}</span>
            <span style={{ fontSize: 11, color: TEXT_MUTED, marginLeft: 'auto' }}>{rowMsg[c.id] ?? ''}</span>
          </div>
        ))}
        {!controls.length && !error && (
          <div style={{ padding: 20, fontSize: 12, color: TEXT_MUTED }}>불러오는 중…</div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Image Processing
// ---------------------------------------------------------------------------

function PresetsSection({ onApply }: { onApply: () => void }) {
  const [presets, setPresets] = useState<Record<string, CameraPreset>>({});
  const [newName, setNewName] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  async function load() {
    try { setPresets((await cameraApi.presets()).presets); }
    catch (e) { setMsg(String(e)); }
  }
  useEffect(() => { load(); }, []);

  async function save() {
    if (!newName.trim()) return;
    setBusy(true);
    try {
      await cameraApi.savePreset(newName.trim());
      setMsg(`'${newName.trim()}' 저장됨 (현재 컨트롤+ROI+fps 스냅샷)`);
      setNewName('');
      await load();
    } catch (e) { setMsg(`저장 실패: ${String(e)}`); }
    finally { setBusy(false); }
  }

  async function apply(name: string) {
    setBusy(true);
    setMsg(`'${name}' 적용 중… (ROI 변경 시 스트림 재시작)`);
    try {
      const r = await cameraApi.applyPreset(name);
      const errs = Object.keys(r.errors ?? {});
      setMsg(errs.length ? `'${name}' 적용 — 일부 실패: ${errs.join(', ')}` : `'${name}' 적용됨`);
      onApply();
    } catch (e) { setMsg(`적용 실패: ${String(e)}`); }
    finally { setBusy(false); }
  }

  async function remove(name: string) {
    try { await cameraApi.deletePreset(name); await load(); }
    catch (e) { setMsg(String(e)); }
  }

  const names = Object.keys(presets).sort();
  return (
    <div>
      <div style={{ fontSize: 11, color: TEXT_MUTED, marginBottom: 8 }}>
        현재 카메라 상태(모든 쓰기 가능 컨트롤 + ROI + 센서 fps)를 이름으로 저장하고
        한 번에 복원합니다. CSI-2 Alvium 은 온카메라 UserSet 이 없어 서버에 저장됩니다.
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input value={newName} placeholder="프리셋 이름 (예: backlight-wire)"
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') save(); }}
          style={{ flex: 1, background: '#0f172a', color: TEXT_PRIMARY, border: `1px solid ${BORDER}`, borderRadius: 4, padding: '6px 8px', fontSize: 12 }} />
        <button onClick={save} disabled={busy || !newName.trim()}
          style={{ background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, padding: '6px 14px', cursor: 'pointer', fontSize: 12, fontWeight: 600, opacity: busy || !newName.trim() ? 0.5 : 1 }}>
          현재 상태 저장
        </button>
      </div>
      {msg && <div style={{ fontSize: 11, color: msg.includes('실패') ? '#ef4444' : '#60a5fa', marginBottom: 8 }}>{msg}</div>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {names.length === 0 && <div style={{ fontSize: 12, color: TEXT_MUTED }}>저장된 프리셋이 없습니다.</div>}
        {names.map((name) => {
          const p = presets[name];
          return (
            <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 8, background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 6, padding: '8px 10px' }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, color: TEXT_PRIMARY, fontWeight: 600 }}>{name}</div>
                <div style={{ fontSize: 10, color: TEXT_MUTED }}>
                  {p.roi ? `ROI ${p.roi.width}×${p.roi.height}@(${p.roi.left},${p.roi.top})` : ''}
                  {p.fps ? ` · ${p.fps.toFixed(0)}fps` : ''} · {Object.keys(p.controls ?? {}).length}개 컨트롤 · {p.saved_at}
                </div>
              </div>
              <button onClick={() => apply(name)} disabled={busy}
                style={{ background: '#166534', color: '#bbf7d0', border: 'none', borderRadius: 4, padding: '5px 12px', cursor: 'pointer', fontSize: 12 }}>
                적용
              </button>
              <button onClick={() => remove(name)} disabled={busy}
                style={{ background: '#1e293b', color: '#fca5a5', border: `1px solid ${BORDER}`, borderRadius: 4, padding: '5px 10px', cursor: 'pointer', fontSize: 12 }}>
                삭제
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Gallery
// ---------------------------------------------------------------------------

function Gallery() {
  const [captures, setCaptures] = useState<{ id: number; ts: string; url: string }[]>([]);
  const [lightbox, setLightbox] = useState<number | null>(null);

  const selected = lightbox !== null ? captures.find((c) => c.id === lightbox) : null;

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button style={{ background: '#1e293b', border: `1px solid ${BORDER}`, color: TEXT_SECONDARY, padding: '6px 12px', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}>Export All ZIP</button>
        <button style={{ background: '#1e293b', border: `1px solid ${BORDER}`, color: TEXT_SECONDARY, padding: '6px 12px', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}>Compare</button>
      </div>

      {captures.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 60, color: TEXT_MUTED, background: BG_PANEL, borderRadius: 8, border: `1px solid ${BORDER}` }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>📷</div>
          <div style={{ fontSize: 14 }}>No captures yet</div>
          <div style={{ fontSize: 12, marginTop: 6 }}>Capture frames from the Live tab</div>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10 }}>
          {captures.map((c) => (
            <div
              key={c.id}
              onClick={() => setLightbox(c.id)}
              style={{ borderRadius: 6, overflow: 'hidden', border: `1px solid ${BORDER}`, cursor: 'pointer', position: 'relative' }}
            >
              <img src={c.url} alt={c.ts} style={{ width: '100%', height: 120, objectFit: 'cover', display: 'block' }} />
              <div style={{ padding: '4px 8px', fontSize: 10, color: TEXT_MUTED, background: BG_PANEL }}>{c.ts}</div>
            </div>
          ))}
        </div>
      )}

      {selected && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.85)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div style={{ background: BG_PANEL, borderRadius: 8, overflow: 'hidden', maxWidth: '90vw', maxHeight: '90vh', display: 'flex' }}>
            <img src={selected.url} alt={selected.ts} style={{ maxWidth: 800, maxHeight: '90vh', objectFit: 'contain' }} />
            <div style={{ width: 200, padding: 16, borderLeft: `1px solid ${BORDER}` }}>
              <div style={{ fontSize: 12, color: TEXT_MUTED, marginBottom: 8 }}>{selected.ts}</div>
              <button onClick={() => setLightbox(null)} style={{ width: '100%', background: '#1e293b', border: `1px solid ${BORDER}`, color: TEXT_SECONDARY, padding: '6px', borderRadius: 4, cursor: 'pointer', fontSize: 12, marginBottom: 8 }}>Close</button>
              <button style={{ width: '100%', background: '#1d4ed8', border: 'none', color: '#fff', padding: '6px', borderRadius: 4, cursor: 'pointer', fontSize: 12, marginBottom: 8 }}>Download</button>
              <button onClick={() => { setCaptures((p) => p.filter((c) => c.id !== selected.id)); setLightbox(null); }} style={{ width: '100%', background: '#7f1d1d', border: 'none', color: '#fca5a5', padding: '6px', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}>Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main CameraPage
// ---------------------------------------------------------------------------

export function CameraPage() {
  const [status, setStatus] = useState<CameraStatus | null>(null);

  useEffect(() => {
    function poll() { cameraApi.status().then(setStatus).catch(() => null); }
    poll();
    const id = setInterval(poll, 3000);
    return () => clearInterval(id);
  }, []);

  const refreshStatus = () => cameraApi.status().then(setStatus).catch(() => null);

  // -- side panel state (persisted) ---------------------------------------
  const [panelOpen, setPanelOpen] = usePersistentState('camera.panel.open', true);
  const [panelW, setPanelW] = usePersistentState('camera.panel.w', 430);
  const [sections, setSections] = usePersistentState<Record<string, boolean>>(
    'camera.panel.sections.v2',
    { tuning: true, acquisition: false, params: false, processing: false, gallery: false });
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);

  const toggleSection = (id: PanelSectionId) =>
    setSections((s) => ({ ...s, [id]: !s[id] }));
  const openFromRail = (id: PanelSectionId) => {
    setPanelOpen(true);
    setSections((s) => ({ ...s, [id]: true }));
  };

  function onDividerDown(e: React.PointerEvent) {
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    dragRef.current = { startX: e.clientX, startW: panelW };
    setDragging(true);
  }
  function onDividerMove(e: React.PointerEvent) {
    if (!dragRef.current) return;
    const w = dragRef.current.startW + (dragRef.current.startX - e.clientX);
    setPanelW(Math.max(330, Math.min(700, w)));
  }
  function onDividerUp() { dragRef.current = null; setDragging(false); }

  const sectionBody = (id: PanelSectionId) => {
    switch (id) {
      case 'tuning':      return <LiveTuningCard status={status} onApply={refreshStatus} />;
      case 'acquisition': return (<>
        <RoiCard onApply={refreshStatus} />
        <Acquisition status={status} onApply={refreshStatus} />
      </>);
      case 'params':      return <ParametersTab />;
      case 'presets':     return <PresetsSection onApply={refreshStatus} />;
      case 'gallery':     return <Gallery />;
    }
  };

  return (
    <div style={{ padding: 'clamp(12px, 2vw, 20px)', maxWidth: 1600, margin: '0 auto' }}>
      <style>{`@keyframes cam-section-in { from { opacity: 0; transform: translateY(-4px); } }`}</style>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 10, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, color: TEXT_PRIMARY, fontSize: 18 }}>Camera</h2>
        <span style={{ fontSize: 13, color: TEXT_MUTED }}>{status?.device_id ?? 'Allied Vision Alvium'}</span>
        <div style={{ marginLeft: 'auto' }}>
          <ConnectionControl
            label="Camera"
            connected={status?.connected ?? false}
            connectedLabel={status?.device ? `ON (${status.device.model})` : 'ON'}
            disconnectedLabel="OFF"
            onConnect={async () => { await cameraApi.connect(); await refreshStatus(); }}
            onDisconnect={async () => { await cameraApi.disconnect(); await refreshStatus(); }}
            disconnectConfirm={{
              title: 'Disconnect camera?',
              description:
                'Live streaming and capture will stop until you reconnect.',
            }}
          />
        </div>
      </div>

      {/* nowrap: the settings panel stays on the right at every viewport
          width — the live view shrinks instead of the panel dropping below. */}
      <div style={{ display: 'flex', alignItems: 'stretch', flexWrap: 'nowrap', gap: 0 }}>
        {/* Live view — always visible while tuning */}
        <div style={{ flex: '1 1 0', minWidth: 200 }}>
          <LiveCapture status={status} />
        </div>

        {/* Resize divider */}
        {panelOpen && (
          <div
            onPointerDown={onDividerDown} onPointerMove={onDividerMove}
            onPointerUp={onDividerUp} onPointerCancel={onDividerUp}
            style={{ flex: '0 0 8px', cursor: 'col-resize', display: 'flex',
                     alignItems: 'center', justifyContent: 'center', touchAction: 'none' }}>
            <div style={{ width: 3, height: 48, borderRadius: 2,
                          background: dragging ? '#3b82f6' : BORDER }} />
          </div>
        )}

        {/* Sliding side panel / collapsed rail */}
        <div style={{
          flex: `0 0 ${panelOpen ? panelW : 36}px`, width: panelOpen ? panelW : 36,
          transition: dragging ? 'none' : 'flex-basis 0.25s ease, width 0.25s ease',
          minHeight: 420,
        }}>
          {panelOpen ? (
            <div style={{ background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 8,
                          height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
              <div style={{ display: 'flex', alignItems: 'center', padding: '8px 12px',
                            borderBottom: `1px solid ${BORDER}`, background: '#0f172a' }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: TEXT_SECONDARY }}>설정 패널</span>
                <button onClick={() => setPanelOpen(false)} title="패널 접기"
                  style={{ marginLeft: 'auto', background: 'none', border: 'none', color: TEXT_MUTED,
                           cursor: 'pointer', fontSize: 14, padding: 2 }}>▶</button>
              </div>
              <div style={{ overflowY: 'auto', flex: 1 }}>
                {PANEL_SECTIONS.map((s) => (
                  <CollapsibleSection key={s.id} label={s.label} icon={s.icon}
                    open={!!sections[s.id]} onToggle={() => toggleSection(s.id)}>
                    {sections[s.id] && sectionBody(s.id)}
                  </CollapsibleSection>
                ))}
              </div>
            </div>
          ) : (
            <div style={{ background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 8,
                          height: '100%', display: 'flex', flexDirection: 'column',
                          alignItems: 'center', paddingTop: 6, gap: 10 }}>
              <button onClick={() => setPanelOpen(true)} title="패널 열기"
                style={{ background: 'none', border: 'none', color: TEXT_MUTED, cursor: 'pointer', fontSize: 14 }}>◀</button>
              {PANEL_SECTIONS.map((s) => (
                <button key={s.id} onClick={() => openFromRail(s.id)} title={s.label}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 15, padding: 2 }}>
                  {s.icon}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
