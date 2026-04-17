/**
 * CameraPage.tsx — Camera control with 4 sub-tabs: Live, Acquisition, Processing, Gallery.
 */

import { useEffect, useState } from 'react';
import { cameraApi, type CameraStatus } from '../api/client';
import { Button } from '../components/ui/Button';
import { Card, CardTitle } from '../components/ui/Card';
import { ConnectionControl } from '../components/ui/ConnectionControl';
import { SliderInput } from '../components/ui/SliderInput';
import { StatusBadge } from '../components/ui/StatusBadge';
import { useCameraWs } from '../hooks/useCameraWs';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { cn } from '../lib/cn';

type CameraSubTab = 'live' | 'acquisition' | 'processing' | 'gallery';

const SUB_TABS: { id: CameraSubTab; label: string }[] = [
  { id: 'live',        label: 'Live & Capture' },
  { id: 'acquisition', label: 'Acquisition' },
  { id: 'processing',  label: 'Image Processing' },
  { id: 'gallery',     label: 'Gallery' },
];

function SubTabBar({ active, onChange }: { active: CameraSubTab; onChange: (t: CameraSubTab) => void }) {
  return (
    <div className="flex border-b border-border mb-5">
      {SUB_TABS.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={cn(
            'px-[18px] py-2.5 bg-transparent border-0 border-b-2 cursor-pointer text-[13px] transition-colors',
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
      {/* Stream container */}
      <div className="relative bg-black rounded-lg overflow-hidden mb-3 min-h-[200px] max-h-[400px] border border-border">
        {!useWs ? (
          <img
            src={streamSrc}
            alt="Camera stream"
            style={{ transform: `scale(${zoom})`, transformOrigin: 'center center' }}
            className="w-full max-h-[400px] object-contain block"
            onError={() => setUseWs(true)}
          />
        ) : wsFrame ? (
          <img
            src={`data:image/jpeg;base64,${wsFrame}`}
            alt="WS frame"
            style={{ transform: `scale(${zoom})` }}
            className="w-full max-h-[400px] object-contain block"
          />
        ) : (
          <div className="flex items-center justify-center h-60 text-text-tertiary text-[13px]">
            No camera signal
          </div>
        )}

        {/* Crosshair */}
        {showCrosshair && (
          <div className="absolute inset-0 pointer-events-none">
            <div className="absolute top-1/2 left-0 right-0 h-px bg-yellow-400/50" />
            <div className="absolute top-0 bottom-0 left-1/2 w-px bg-yellow-400/50" />
          </div>
        )}

        {/* HUD — top-left */}
        {status && (
          <div className="absolute top-2 left-2 bg-black/60 rounded px-2 py-1 text-[11px] text-text-primary">
            <span className="numeric">{status.width}×{status.height}</span>
            {' '}&nbsp;|&nbsp;{' '}
            <span className="numeric">{status.fps?.toFixed(1) ?? '—'}</span> fps
            {' '}&nbsp;|&nbsp;{' '}
            {status.format ?? '—'}
          </div>
        )}

        {/* HUD — top-right */}
        {status && (
          <div className="absolute top-2 right-2 bg-black/60 rounded px-2 py-1 text-[11px] text-text-primary text-right">
            Exp: <span className="numeric">{status.exposure_us ?? '—'}</span> μs
            {' '}&nbsp;|&nbsp;{' '}
            Gain: <span className="numeric">{status.gain_db?.toFixed(1) ?? '—'}</span> dB
          </div>
        )}

        {/* HUD — bottom-right */}
        <div className="absolute bottom-2 right-2 bg-black/60 rounded px-2 py-1 text-[10px] text-text-tertiary">
          {new Date().toLocaleTimeString()}
        </div>
      </div>

      {/* Controls */}
      <div className="flex gap-2.5 flex-wrap items-center mb-3">
        {/* Zoom buttons */}
        <div className="flex gap-1">
          {[1, 2, 4].map((z) => (
            <button
              key={z}
              onClick={() => setZoom(z)}
              className={cn(
                'px-3 py-1 border rounded text-[12px] cursor-pointer transition-colors',
                zoom === z
                  ? 'bg-accent/15 border-accent text-accent font-semibold'
                  : 'bg-surface-2 border-border text-text-tertiary hover:text-text-secondary',
              )}
            >
              {z}x
            </button>
          ))}
        </div>

        <button
          onClick={() => setShowCrosshair(!showCrosshair)}
          className={cn(
            'px-3 py-1 border rounded text-[12px] cursor-pointer transition-colors',
            showCrosshair
              ? 'bg-accent/15 border-accent text-accent'
              : 'bg-surface-2 border-border text-text-tertiary hover:text-text-secondary',
          )}
        >
          Crosshair
        </button>

        <Button variant="primary" size="sm" onClick={capture}>
          Capture
        </Button>

        <button
          onClick={() => setRecording(!recording)}
          className={cn(
            'px-3.5 py-1 border rounded text-[12px] cursor-pointer transition-colors',
            recording
              ? 'bg-danger/15 border-danger text-danger'
              : 'bg-surface-2 border-border text-text-secondary hover:text-text-primary',
          )}
        >
          {recording ? 'Stop Recording' : 'Start Recording'}
        </button>
      </div>

      {/* Status bar */}
      <div className="flex gap-3.5 text-[12px] text-text-tertiary items-center">
        <StatusBadge variant={status?.connected ? 'success' : 'error'} label={status?.connected ? 'Connected' : 'Disconnected'} />
        <span>Backend: {status?.backend ?? 'VimbaX'}</span>
        <span>Frames: <span className="numeric">{frameCount}</span></span>
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

  return (
    <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
      {/* Exposure card */}
      <Card>
        <CardTitle className="mb-3">Exposure</CardTitle>
        <div className="flex gap-3 mb-2.5">
          {(['Manual', 'Auto'] as const).map((m) => (
            <label key={m} className="flex gap-1.5 text-[13px] text-text-secondary cursor-pointer items-center">
              <input type="radio" className="accent-accent" checked={exposureAuto === (m === 'Auto')} onChange={() => setExposureAuto(m === 'Auto')} />
              {m}
            </label>
          ))}
        </div>
        {!exposureAuto && <SliderInput label="ExposureTime" value={exposureUs} min={20} max={100000} step={100} unit="μs" onChange={setExposureUs} className="mb-3" />}
        <Button variant="primary" size="sm" loading={applying} onClick={apply} className="mt-3">
          Apply
        </Button>
        {error && <div className="text-[12px] text-danger mt-2">{error}</div>}
      </Card>

      {/* Gain card */}
      <Card>
        <CardTitle className="mb-3">Gain</CardTitle>
        <div className="flex gap-3 mb-2.5">
          {(['Manual', 'Auto'] as const).map((m) => (
            <label key={m} className="flex gap-1.5 text-[13px] text-text-secondary cursor-pointer items-center">
              <input type="radio" className="accent-accent" checked={gainAuto === (m === 'Auto')} onChange={() => setGainAuto(m === 'Auto')} />
              {m}
            </label>
          ))}
        </div>
        {!gainAuto && <SliderInput label="Gain" value={gainDb} min={0} max={24} step={0.5} unit="dB" onChange={setGainDb} className="mb-3" />}
        <Button variant="primary" size="sm" loading={applying} onClick={apply} className="mt-3">
          Apply
        </Button>
      </Card>

      {/* Trigger card */}
      <Card>
        <CardTitle className="mb-3">Trigger</CardTitle>
        <div className="flex flex-col gap-2 mb-3">
          {(['freerun', 'software', 'external'] as const).map((t) => (
            <label key={t} className="flex gap-2 text-[13px] text-text-secondary cursor-pointer items-center">
              <input type="radio" className="accent-accent" checked={trigger === t} onChange={() => setTrigger(t)} />
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </label>
          ))}
        </div>
        {trigger === 'software' && (
          <Button variant="primary" size="sm">Software Trigger</Button>
        )}
      </Card>

      {/* Frame Rate card */}
      <Card>
        <CardTitle className="mb-3">Frame Rate</CardTitle>
        <label className="flex gap-2 text-[13px] text-text-secondary mb-3 cursor-pointer items-center">
          <input type="checkbox" className="accent-accent" checked={fpsEnabled} onChange={(e) => setFpsEnabled(e.target.checked)} />
          Enable Frame Rate Limit
        </label>
        {fpsEnabled && <SliderInput label="Frame Rate" value={fps} min={1} max={30} unit="fps" onChange={setFps} className="mb-3" />}
        <Button variant="primary" size="sm" className="mt-3">Apply</Button>
      </Card>
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

  return (
    <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
      {/* Pixel Format card */}
      <Card>
        <CardTitle className="mb-3">Pixel Format</CardTitle>
        <div className="mb-3">
          <label className="text-[12px] text-text-tertiary block mb-1">Format</label>
          <select
            value={pixelFormat}
            onChange={(e) => setPixelFormat(e.target.value)}
            className="bg-surface-2 border border-border text-text-primary rounded text-[13px] px-2.5 py-1.5 w-full"
          >
            {['Mono8', 'Mono12', 'BayerRG8', 'BayerRG12', 'RGB8'].map((f) => <option key={f}>{f}</option>)}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-2.5">
          <div>
            <label className="text-[12px] text-text-tertiary block mb-1">Binning H</label>
            <input
              type="number" min={1} max={4} value={binH}
              onChange={(e) => setBinH(Number(e.target.value))}
              className="bg-surface-2 border border-border text-text-primary rounded text-[13px] px-2 py-1.5 w-full"
            />
          </div>
          <div>
            <label className="text-[12px] text-text-tertiary block mb-1">Binning V</label>
            <input
              type="number" min={1} max={4} value={binV}
              onChange={(e) => setBinV(Number(e.target.value))}
              className="bg-surface-2 border border-border text-text-primary rounded text-[13px] px-2 py-1.5 w-full"
            />
          </div>
        </div>
        <Button variant="primary" size="sm" className="mt-3">Apply</Button>
      </Card>

      {/* Image Enhancement card */}
      <Card>
        <CardTitle className="mb-3">Image Enhancement</CardTitle>
        <SliderInput label="Gamma" value={gamma} min={0.1} max={4.0} step={0.1} onChange={setGamma} className="mb-3" />
        <SliderInput label="Black Level" value={blackLevel} min={0} max={255} onChange={setBlackLevel} className="mb-3" />
        <SliderInput label="Sharpness" value={sharpness} min={0} max={100} onChange={setSharpness} />
        <Button variant="primary" size="sm" className="mt-3">Apply</Button>
      </Card>

      {/* Histogram card — full width */}
      <Card className="col-span-full">
        <CardTitle className="mb-1">Histogram</CardTitle>
        <div className="text-[12px] text-text-tertiary mb-2 flex gap-5">
          <span>Min: 12 &nbsp;|&nbsp; Max: 248 &nbsp;|&nbsp; Mean: 127</span>
        </div>
        <div className="h-[120px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={histData} barCategoryGap="0%">
              <XAxis dataKey="bin" hide />
              <YAxis hide />
              <Tooltip
                contentStyle={{
                  background: 'var(--color-surface-1)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text-primary)',
                  fontSize: 11,
                }}
              />
              <Bar dataKey="count" fill="var(--color-accent)" isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>
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
      <div className="flex gap-2 mb-4">
        <Button variant="secondary" size="sm">Export All ZIP</Button>
        <Button variant="secondary" size="sm">Compare</Button>
      </div>

      {captures.length === 0 ? (
        <div className="text-center py-16 text-text-tertiary bg-surface-1 rounded-lg border border-border">
          <div className="text-[32px] mb-3">📷</div>
          <div className="text-[14px]">No captures yet</div>
          <div className="text-[12px] mt-1.5">Capture frames from the Live tab</div>
        </div>
      ) : (
        <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))' }}>
          {captures.map((c) => (
            <div
              key={c.id}
              onClick={() => setLightbox(c.id)}
              className="rounded border border-border overflow-hidden cursor-pointer relative hover:border-accent/60 transition-colors"
            >
              <img src={c.url} alt={c.ts} className="w-full h-[120px] object-cover block" />
              <div className="px-2 py-1 text-[10px] text-text-tertiary bg-surface-1">{c.ts}</div>
            </div>
          ))}
        </div>
      )}

      {/* Lightbox */}
      {selected && (
        <div className="fixed inset-0 bg-black/85 flex items-center justify-center z-[1000]">
          <div className="bg-surface-1 rounded-lg overflow-hidden max-w-[90vw] max-h-[90vh] flex">
            <img src={selected.url} alt={selected.ts} className="max-w-[800px] max-h-[90vh] object-contain" />
            <div className="w-[200px] p-4 border-l border-border flex flex-col gap-2">
              <div className="text-[12px] text-text-tertiary mb-2">{selected.ts}</div>
              <Button variant="secondary" size="sm" className="w-full" onClick={() => setLightbox(null)}>Close</Button>
              <Button variant="primary" size="sm" className="w-full">Download</Button>
              <Button
                variant="danger"
                size="sm"
                className="w-full"
                onClick={() => { setCaptures((p) => p.filter((c) => c.id !== selected.id)); setLightbox(null); }}
              >
                Delete
              </Button>
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

  const refreshStatus = () => cameraApi.status().then(setStatus).catch(() => null);

  return (
    <div className="px-[clamp(12px,3vw,20px)] max-w-[1100px] mx-auto">
      <h2 className="text-text-primary text-[18px] font-semibold mb-1 mt-0">Camera</h2>
      <div className="text-[13px] text-text-tertiary mb-3.5">
        Allied Vision Alvium 1800 U-158m
      </div>

      <Card className="mb-4.5 p-3.5">
        <ConnectionControl
          label="Camera"
          connected={status?.power_state === 'on'}
          connectedLabel={status?.backend ? `ON (${status.backend})` : 'ON'}
          disconnectedLabel="OFF"
          onConnect={async () => { await cameraApi.connect(); await refreshStatus(); }}
          onDisconnect={async () => { await cameraApi.disconnect(); await refreshStatus(); }}
          disconnectConfirm={{
            title: 'Disconnect camera?',
            description:
              'The Vimba X SDK will shut down cleanly (frame release → cam.__exit__ → VmbSystem.__exit__). ' +
              'Live streaming and capture will stop until you reconnect.',
          }}
        />
      </Card>

      <SubTabBar active={subTab} onChange={setSubTab} />

      {subTab === 'live'        && <LiveCapture status={status} />}
      {subTab === 'acquisition' && <Acquisition status={status} onApply={refreshStatus} />}
      {subTab === 'processing'  && <ImageProcessing />}
      {subTab === 'gallery'     && <Gallery />}
    </div>
  );
}
