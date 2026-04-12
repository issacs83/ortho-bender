/**
 * CameraPage.tsx — Camera control with 4 sub-tabs: Live, Acquisition, Processing, Gallery.
 */

import { useEffect, useRef, useState } from 'react';
import { cameraApi, type CameraStatus } from '../api/client';
import { SliderInput } from '../components/ui/SliderInput';
import { StatusBadge } from '../components/ui/StatusBadge';
import { useCameraWs } from '../hooks/useCameraWs';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { BG_PANEL, BG_PRIMARY, BORDER, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED } from '../constants';

type CameraSubTab = 'live' | 'acquisition' | 'processing' | 'gallery';

const SUB_TABS: { id: CameraSubTab; label: string }[] = [
  { id: 'live',        label: 'Live & Capture' },
  { id: 'acquisition', label: 'Acquisition' },
  { id: 'processing',  label: 'Image Processing' },
  { id: 'gallery',     label: 'Gallery' },
];

function SubTabBar({ active, onChange }: { active: CameraSubTab; onChange: (t: CameraSubTab) => void }) {
  return (
    <div style={{ display: 'flex', borderBottom: `1px solid ${BORDER}`, marginBottom: 20 }}>
      {SUB_TABS.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)} style={{
          padding: '10px 18px', background: 'none', border: 'none',
          borderBottom: active === t.id ? '2px solid #3b82f6' : '2px solid transparent',
          color: active === t.id ? TEXT_PRIMARY : TEXT_MUTED,
          cursor: 'pointer', fontSize: 13, fontWeight: active === t.id ? 600 : 400,
        }}>{t.label}</button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Live & Capture
// ---------------------------------------------------------------------------

function LiveCapture({ status }: { status: CameraStatus | null }) {
  const [useWs, setUseWs] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [showCrosshair, setShowCrosshair] = useState(false);
  const [recording, setRecording] = useState(false);
  const [frameCount, setFrameCount] = useState(0);
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
      <div style={{ position: 'relative', background: '#000', borderRadius: 8, overflow: 'hidden', marginBottom: 12, minHeight: 240, border: `1px solid ${BORDER}` }}>
        {/* Stream */}
        {!useWs ? (
          <img
            src={streamSrc}
            alt="Camera stream"
            style={{ width: '100%', display: 'block', transform: `scale(${zoom})`, transformOrigin: 'center center' }}
            onError={() => setUseWs(true)}
          />
        ) : wsFrame ? (
          <img
            src={`data:image/jpeg;base64,${wsFrame}`}
            alt="WS frame"
            style={{ width: '100%', display: 'block', transform: `scale(${zoom})` }}
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

        {/* HUD - top-left */}
        {status && (
          <div style={{ position: 'absolute', top: 8, left: 8, background: 'rgba(0,0,0,0.6)', borderRadius: 4, padding: '4px 8px', fontSize: 11, color: TEXT_PRIMARY }}>
            {status.width}×{status.height} &nbsp;|&nbsp; {status.fps?.toFixed(1) ?? '—'} fps &nbsp;|&nbsp; {status.format ?? '—'}
          </div>
        )}

        {/* HUD - top-right */}
        {status && (
          <div style={{ position: 'absolute', top: 8, right: 8, background: 'rgba(0,0,0,0.6)', borderRadius: 4, padding: '4px 8px', fontSize: 11, color: TEXT_PRIMARY, textAlign: 'right' as const }}>
            Exp: {status.exposure_us ?? '—'} μs &nbsp;|&nbsp; Gain: {status.gain_db?.toFixed(1) ?? '—'} dB
          </div>
        )}

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
        <button
          onClick={() => setRecording(!recording)}
          style={{ padding: '5px 14px', background: recording ? '#7f1d1d' : '#1e293b', color: recording ? '#fca5a5' : TEXT_SECONDARY, border: `1px solid ${recording ? '#ef4444' : BORDER}`, borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
        >
          {recording ? 'Stop Recording' : 'Start Recording'}
        </button>
      </div>

      {/* Status bar */}
      <div style={{ display: 'flex', gap: 14, fontSize: 12, color: TEXT_MUTED }}>
        <StatusBadge variant={status?.connected ? 'success' : 'error'} label={status?.connected ? 'Connected' : 'Disconnected'} />
        <span>Backend: {status?.backend ?? 'VimbaX'}</span>
        <span>Frames: {frameCount}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Acquisition
// ---------------------------------------------------------------------------

function Acquisition({ status, onApply }: { status: CameraStatus | null; onApply: () => void }) {
  const [exposureUs, setExposureUs] = useState(status?.exposure_us ?? 5000);
  const [exposureAuto, setExposureAuto] = useState(false);
  const [gainDb, setGainDb] = useState(status?.gain_db ?? 0);
  const [gainAuto, setGainAuto] = useState(false);
  const [trigger, setTrigger] = useState<'freerun' | 'software' | 'external'>('freerun');
  const [fpsEnabled, setFpsEnabled] = useState(false);
  const [fps, setFps] = useState(15);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function apply() {
    setApplying(true);
    try {
      await cameraApi.settings({ exposure_us: exposureAuto ? undefined : exposureUs, gain_db: gainAuto ? undefined : gainDb });
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
        {!exposureAuto && <SliderInput label="ExposureTime" value={exposureUs} min={20} max={100000} step={100} unit="μs" onChange={setExposureUs} />}
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
        {!gainAuto && <SliderInput label="Gain" value={gainDb} min={0} max={24} step={0.5} unit="dB" onChange={setGainDb} />}
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
// Image Processing
// ---------------------------------------------------------------------------

function ImageProcessing() {
  const [gamma, setGamma] = useState(1.0);
  const [blackLevel, setBlackLevel] = useState(0);
  const [sharpness, setSharpness] = useState(0);
  const [pixelFormat, setPixelFormat] = useState('Mono8');
  const [binH, setBinH] = useState(1);
  const [binV, setBinV] = useState(1);

  // Fake histogram data
  const histData = Array.from({ length: 32 }, (_, i) => ({
    bin: i * 8,
    count: Math.round(Math.random() * 1000 + 100),
  }));

  const cardStyle = { background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 16, marginBottom: 16 };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Pixel Format</h3>
        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, color: TEXT_MUTED, display: 'block', marginBottom: 4 }}>Format</label>
          <select value={pixelFormat} onChange={(e) => setPixelFormat(e.target.value)} style={{ background: BG_PRIMARY, border: `1px solid ${BORDER}`, color: TEXT_PRIMARY, padding: '6px 10px', borderRadius: 4, fontSize: 13, width: '100%' }}>
            {['Mono8', 'Mono12', 'BayerRG8', 'BayerRG12', 'RGB8'].map((f) => <option key={f}>{f}</option>)}
          </select>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <div>
            <label style={{ fontSize: 12, color: TEXT_MUTED, display: 'block', marginBottom: 4 }}>Binning H</label>
            <input type="number" min={1} max={4} value={binH} onChange={(e) => setBinH(Number(e.target.value))} style={{ background: BG_PRIMARY, border: `1px solid ${BORDER}`, color: TEXT_PRIMARY, padding: '5px 8px', borderRadius: 4, fontSize: 13, width: '100%' }} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_MUTED, display: 'block', marginBottom: 4 }}>Binning V</label>
            <input type="number" min={1} max={4} value={binV} onChange={(e) => setBinV(Number(e.target.value))} style={{ background: BG_PRIMARY, border: `1px solid ${BORDER}`, color: TEXT_PRIMARY, padding: '5px 8px', borderRadius: 4, fontSize: 13, width: '100%' }} />
          </div>
        </div>
        <button style={{ background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, padding: '6px 14px', cursor: 'pointer', fontSize: 12, fontWeight: 600, marginTop: 12 }}>Apply</button>
      </div>

      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 12px', fontSize: 14, color: TEXT_PRIMARY }}>Image Enhancement</h3>
        <SliderInput label="Gamma" value={gamma} min={0.1} max={4.0} step={0.1} onChange={setGamma} style={{ marginBottom: 12 }} />
        <SliderInput label="Black Level" value={blackLevel} min={0} max={255} onChange={setBlackLevel} style={{ marginBottom: 12 }} />
        <SliderInput label="Sharpness" value={sharpness} min={0} max={100} onChange={setSharpness} />
        <button style={{ background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, padding: '6px 14px', cursor: 'pointer', fontSize: 12, fontWeight: 600, marginTop: 12 }}>Apply</button>
      </div>

      <div style={{ ...cardStyle, gridColumn: '1 / -1' }}>
        <h3 style={{ margin: '0 0 4px', fontSize: 14, color: TEXT_PRIMARY }}>Histogram</h3>
        <div style={{ fontSize: 12, color: TEXT_MUTED, marginBottom: 8, display: 'flex', gap: 20 }}>
          <span>Min: 12 &nbsp;|&nbsp; Max: 248 &nbsp;|&nbsp; Mean: 127</span>
        </div>
        <div style={{ height: 120 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={histData} barCategoryGap="0%">
              <XAxis dataKey="bin" hide />
              <YAxis hide />
              <Tooltip contentStyle={{ background: BG_PANEL, border: `1px solid ${BORDER}`, color: TEXT_PRIMARY, fontSize: 11 }} />
              <Bar dataKey="count" fill="#3b82f6" isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
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
  const [subTab, setSubTab] = useState<CameraSubTab>('live');
  const [status, setStatus] = useState<CameraStatus | null>(null);

  useEffect(() => {
    function poll() { cameraApi.status().then(setStatus).catch(() => null); }
    poll();
    const id = setInterval(poll, 3000);
    return () => clearInterval(id);
  }, []);

  return (
    <div style={{ padding: 'clamp(12px, 3vw, 20px)', maxWidth: 1100, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 4px', color: TEXT_PRIMARY, fontSize: 18 }}>Camera</h2>
      <div style={{ fontSize: 13, color: TEXT_MUTED, marginBottom: 20 }}>
        Allied Vision Alvium 1800 U-158m &nbsp;|&nbsp;
        <span style={{ color: status?.connected ? '#22c55e' : '#ef4444' }}>
          {status?.connected ? 'Connected' : 'Disconnected'}
        </span>
      </div>

      <SubTabBar active={subTab} onChange={setSubTab} />

      {subTab === 'live'        && <LiveCapture status={status} />}
      {subTab === 'acquisition' && <Acquisition status={status} onApply={() => cameraApi.status().then(setStatus).catch(() => null)} />}
      {subTab === 'processing'  && <ImageProcessing />}
      {subTab === 'gallery'     && <Gallery />}
    </div>
  );
}
