/**
 * CameraPage.tsx — Camera control with 4 sub-tabs: Live, Acquisition, Processing, Gallery.
 *
 * Feature panels are driven by CameraCapabilities returned on connect.
 * Only panels where capabilities[feature].supported === true are rendered.
 * Invalidation-aware: when a set response includes invalidated[], those
 * features are re-fetched automatically.
 */

import { useEffect, useRef, useState } from 'react';
import {
  cameraApi,
  type CameraCapabilities,
  type CameraStatus,
  type ExposureInfo,
  type FrameMeta,
  type FrameRateInfo,
  type GainInfo,
  type PixelFormatInfo,
  type RoiInfo,
  type TriggerInfo,
  type UserSetInfo,
  wsApi,
} from '../api/client';
import { Button } from '../components/ui/Button';
import { Card, CardTitle } from '../components/ui/Card';
import { ConnectionControl } from '../components/ui/ConnectionControl';
import { SliderInput } from '../components/ui/SliderInput';
import { StatusBadge } from '../components/ui/StatusBadge';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { cn } from '../lib/cn';

// ---------------------------------------------------------------------------
// Sub-tab types
// ---------------------------------------------------------------------------

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
// Feature state container
// ---------------------------------------------------------------------------

interface FeatureState {
  exposure: ExposureInfo | null;
  gain: GainInfo | null;
  roi: RoiInfo | null;
  pixelFormat: PixelFormatInfo | null;
  frameRate: FrameRateInfo | null;
  trigger: TriggerInfo | null;
  temperature: number | null;
  userSet: UserSetInfo | null;
}

const EMPTY_FEATURES: FeatureState = {
  exposure: null, gain: null, roi: null, pixelFormat: null,
  frameRate: null, trigger: null, temperature: null, userSet: null,
};

// ---------------------------------------------------------------------------
// Live & Capture
// ---------------------------------------------------------------------------

interface LiveCaptureProps {
  status: CameraStatus | null;
  frameMeta: FrameMeta | null;
}

function LiveCapture({ status, frameMeta }: LiveCaptureProps) {
  const [useWs, setUseWs] = useState(false);
  const [wsFrame, setWsFrame] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [showCrosshair, setShowCrosshair] = useState(false);
  const [recording, setRecording] = useState(false);
  const [frameCount, setFrameCount] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!useWs) return;
    const ws = wsApi.camera((msg) => {
      if (msg.frame_b64) { setWsFrame(msg.frame_b64); setFrameCount((c) => c + 1); }
    });
    wsRef.current = ws;
    return () => { ws.close(); wsRef.current = null; };
  }, [useWs]);

  function capture() {
    const link = document.createElement('a');
    link.href = cameraApi.captureUrl();
    link.download = `frame_${Date.now()}.jpg`;
    link.click();
  }

  // Telemetry — prefer FrameMeta from WS, fall back to status
  const expUs   = frameMeta?.exposure_us ?? status?.current_exposure_us;
  const gainDb  = frameMeta?.gain_db ?? status?.current_gain_db;
  const tempC   = frameMeta?.temperature_c ?? status?.current_temperature_c;
  const fpsAct  = frameMeta?.fps_actual ?? status?.current_fps;
  const imgW    = frameMeta?.width;
  const imgH    = frameMeta?.height;
  const pixFmt  = status?.current_pixel_format;

  return (
    <div>
      {/* Stream container */}
      <div className="relative bg-black rounded-lg overflow-hidden mb-3 min-h-[200px] max-h-[400px] border border-border">
        {!useWs ? (
          <img
            src={cameraApi.streamUrl()}
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
        <div className="absolute top-2 left-2 bg-black/60 rounded px-2 py-1 text-[11px] text-text-primary">
          {imgW && imgH
            ? <span className="numeric">{imgW}×{imgH}</span>
            : <span>—×—</span>}
          {' '}&nbsp;|&nbsp;{' '}
          <span className="numeric">{fpsAct?.toFixed(1) ?? '—'}</span> fps
          {' '}&nbsp;|&nbsp;{' '}
          {pixFmt ?? '—'}
        </div>

        {/* HUD — top-right */}
        <div className="absolute top-2 right-2 bg-black/60 rounded px-2 py-1 text-[11px] text-text-primary text-right">
          Exp: <span className="numeric">{expUs ?? '—'}</span> μs
          {' '}&nbsp;|&nbsp;{' '}
          Gain: <span className="numeric">{gainDb?.toFixed(1) ?? '—'}</span> dB
          {tempC != null && <><br />Temp: <span className="numeric">{tempC.toFixed(1)}</span> °C</>}
        </div>

        {/* HUD — bottom-right */}
        <div className="absolute bottom-2 right-2 bg-black/60 rounded px-2 py-1 text-[10px] text-text-tertiary">
          {new Date().toLocaleTimeString()}
        </div>
      </div>

      {/* Controls */}
      <div className="flex gap-2.5 flex-wrap items-center mb-3">
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
      <div className="flex gap-3.5 text-[12px] text-text-tertiary items-center flex-wrap">
        <StatusBadge variant={status?.connected ? 'success' : 'error'} label={status?.connected ? 'Connected' : 'Disconnected'} />
        {status?.device && <span>Model: {status.device.model}</span>}
        <span>Frames: <span className="numeric">{frameCount}</span></span>
        {fpsAct != null && <span>FPS: <span className="numeric">{fpsAct.toFixed(1)}</span></span>}
        {tempC != null && <span>Temp: <span className="numeric">{tempC.toFixed(1)}</span> °C</span>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Acquisition tab — Exposure, Gain, Trigger, Frame Rate
// ---------------------------------------------------------------------------

interface AcquisitionProps {
  capabilities: CameraCapabilities;
  features: FeatureState;
  onFeatureChange: (updated: Partial<FeatureState>, invalidated?: string[]) => void;
  onReset?: () => Promise<void>;
}

function Acquisition({ capabilities, features, onFeatureChange, onReset }: AcquisitionProps) {
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);

  async function handleReset() {
    if (!onReset) return;
    const ok = window.confirm(
      'Reset all camera settings to factory defaults?\n\n' +
      'This will load the "Default" UserSet and discard current Exposure, ' +
      'Gain, ROI, PixelFormat, Frame Rate and Trigger changes.',
    );
    if (!ok) return;
    setResetting(true); setResetError(null);
    try {
      await onReset();
    } catch (e) {
      setResetError(String(e));
    } finally {
      setResetting(false);
    }
  }

  // Exposure
  const [expAuto, setExpAuto] = useState(features.exposure?.auto ?? false);
  const [expUs, setExpUs] = useState(features.exposure?.time_us ?? 5000);
  const [expApplying, setExpApplying] = useState(false);
  const [expError, setExpError] = useState<string | null>(null);

  // Gain
  const [gainAuto, setGainAuto] = useState(features.gain?.auto ?? false);
  const [gainDb, setGainDb] = useState(features.gain?.value_db ?? 0);
  const [gainApplying, setGainApplying] = useState(false);
  const [gainError, setGainError] = useState<string | null>(null);

  // Trigger
  const [triggerMode, setTriggerMode] = useState(features.trigger?.mode ?? 'freerun');
  const [triggerSource, setTriggerSource] = useState(features.trigger?.source ?? '');
  const [triggerApplying, setTriggerApplying] = useState(false);
  const [fireApplying, setFireApplying] = useState(false);

  // Frame rate
  const [frEnabled, setFrEnabled] = useState(features.frameRate?.enable ?? false);
  const [frValue, setFrValue] = useState(features.frameRate?.value ?? 15);
  const [frApplying, setFrApplying] = useState(false);

  // Sync local state when features prop changes
  useEffect(() => {
    if (features.exposure) { setExpAuto(features.exposure.auto); setExpUs(features.exposure.time_us); }
  }, [features.exposure]);
  useEffect(() => {
    if (features.gain) { setGainAuto(features.gain.auto); setGainDb(features.gain.value_db); }
  }, [features.gain]);
  useEffect(() => {
    if (features.trigger) { setTriggerMode(features.trigger.mode); setTriggerSource(features.trigger.source ?? ''); }
  }, [features.trigger]);
  useEffect(() => {
    if (features.frameRate) { setFrEnabled(features.frameRate.enable); setFrValue(features.frameRate.value); }
  }, [features.frameRate]);

  const expCap = capabilities.exposure;
  const gainCap = capabilities.gain;
  const triggerCap = capabilities.trigger;
  const frCap = capabilities.frame_rate;

  async function applyExposure() {
    setExpApplying(true); setExpError(null);
    try {
      const res = await cameraApi.setExposure({ auto: expAuto, time_us: expAuto ? undefined : expUs });
      onFeatureChange({ exposure: res }, res.invalidated);
    } catch (e) { setExpError(String(e)); }
    finally { setExpApplying(false); }
  }

  async function applyGain() {
    setGainApplying(true); setGainError(null);
    try {
      const res = await cameraApi.setGain({ auto: gainAuto, value_db: gainAuto ? undefined : gainDb });
      onFeatureChange({ gain: res }, res.invalidated);
    } catch (e) { setGainError(String(e)); }
    finally { setGainApplying(false); }
  }

  async function applyTrigger() {
    setTriggerApplying(true);
    try {
      const res = await cameraApi.setTrigger({ mode: triggerMode, source: triggerSource || undefined });
      onFeatureChange({ trigger: res }, res.invalidated);
    } catch { /* silent */ }
    finally { setTriggerApplying(false); }
  }

  async function fireTrigger() {
    setFireApplying(true);
    try { await cameraApi.fireTrigger(); } catch { /* silent */ }
    finally { setFireApplying(false); }
  }

  async function applyFrameRate() {
    setFrApplying(true);
    try {
      const res = await cameraApi.setFrameRate({ enable: frEnabled, value: frEnabled ? frValue : undefined });
      onFeatureChange({ frameRate: res }, res.invalidated);
    } catch { /* silent */ }
    finally { setFrApplying(false); }
  }

  const expRange = features.exposure?.range ?? expCap?.range ?? { min: 20, max: 100000, step: 100 };
  const gainRange = features.gain?.range ?? gainCap?.range ?? { min: 0, max: 24, step: 0.5 };
  const frRange = features.frameRate?.range ?? frCap?.range ?? { min: 1, max: 60, step: 1 };

  const availableTriggerModes = features.trigger?.available_modes ?? ['freerun', 'software', 'external'];
  const availableTriggerSources = features.trigger?.available_sources ?? [];

  return (
    <div className="flex flex-col gap-4">
      {onReset && (
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="text-[12px] text-text-tertiary">
            Reset reloads the camera's <span className="numeric">Default</span> UserSet (factory state).
          </div>
          <div className="flex items-center gap-2">
            {resetError && <span className="text-[12px] text-danger">{resetError}</span>}
            <Button variant="secondary" size="sm" loading={resetting} onClick={handleReset}>
              Reset to Defaults
            </Button>
          </div>
        </div>
      )}
      <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>

      {/* Exposure */}
      {(expCap?.supported ?? true) && (
        <Card>
          <CardTitle className="mb-3">Exposure</CardTitle>
          <div className="flex gap-3 mb-2.5">
            {(['Manual', 'Auto'] as const).map((m) => (
              <label key={m} className="flex gap-1.5 text-[13px] text-text-secondary cursor-pointer items-center">
                <input
                  type="radio"
                  className="accent-accent"
                  checked={expAuto === (m === 'Auto')}
                  onChange={() => setExpAuto(m === 'Auto')}
                  disabled={m === 'Auto' && expCap?.auto_available === false}
                />
                {m}
              </label>
            ))}
          </div>
          {!expAuto && (
            <SliderInput
              label="ExposureTime"
              value={expUs}
              min={expRange.min}
              max={expRange.max}
              step={expRange.step}
              unit="μs"
              onChange={setExpUs}
              className="mb-3"
            />
          )}
          <Button variant="primary" size="sm" loading={expApplying} onClick={applyExposure} className="mt-3">
            Apply
          </Button>
          {expError && <div className="text-[12px] text-danger mt-2">{expError}</div>}
        </Card>
      )}

      {/* Gain */}
      {(gainCap?.supported ?? true) && (
        <Card>
          <CardTitle className="mb-3">Gain</CardTitle>
          <div className="flex gap-3 mb-2.5">
            {(['Manual', 'Auto'] as const).map((m) => (
              <label key={m} className="flex gap-1.5 text-[13px] text-text-secondary cursor-pointer items-center">
                <input
                  type="radio"
                  className="accent-accent"
                  checked={gainAuto === (m === 'Auto')}
                  onChange={() => setGainAuto(m === 'Auto')}
                  disabled={m === 'Auto' && gainCap?.auto_available === false}
                />
                {m}
              </label>
            ))}
          </div>
          {!gainAuto && (
            <SliderInput
              label="Gain"
              value={gainDb}
              min={gainRange.min}
              max={gainRange.max}
              step={gainRange.step}
              unit="dB"
              onChange={setGainDb}
              className="mb-3"
            />
          )}
          <Button variant="primary" size="sm" loading={gainApplying} onClick={applyGain} className="mt-3">
            Apply
          </Button>
          {gainError && <div className="text-[12px] text-danger mt-2">{gainError}</div>}
        </Card>
      )}

      {/* Trigger */}
      {(triggerCap?.supported ?? true) && (
        <Card>
          <CardTitle className="mb-3">Trigger</CardTitle>
          <div className="flex flex-col gap-2 mb-3">
            {availableTriggerModes.map((m) => (
              <label key={m} className="flex gap-2 text-[13px] text-text-secondary cursor-pointer items-center">
                <input type="radio" className="accent-accent" checked={triggerMode === m} onChange={() => setTriggerMode(m)} />
                {m.charAt(0).toUpperCase() + m.slice(1)}
              </label>
            ))}
          </div>
          {availableTriggerSources.length > 0 && triggerMode !== 'freerun' && (
            <div className="mb-3">
              <label className="text-[12px] text-text-tertiary block mb-1">Source</label>
              <select
                value={triggerSource}
                onChange={(e) => setTriggerSource(e.target.value)}
                className="bg-surface-2 border border-border text-text-primary rounded text-[13px] px-2.5 py-1.5 w-full"
              >
                {availableTriggerSources.map((s) => <option key={s}>{s}</option>)}
              </select>
            </div>
          )}
          <div className="flex gap-2 flex-wrap">
            <Button variant="primary" size="sm" loading={triggerApplying} onClick={applyTrigger}>
              Apply
            </Button>
            {triggerMode === 'software' && (
              <Button variant="secondary" size="sm" loading={fireApplying} onClick={fireTrigger}>
                Fire
              </Button>
            )}
          </div>
        </Card>
      )}

      {/* Frame Rate */}
      {(frCap?.supported ?? true) && (
        <Card>
          <CardTitle className="mb-3">Frame Rate</CardTitle>
          <label className="flex gap-2 text-[13px] text-text-secondary mb-3 cursor-pointer items-center">
            <input
              type="checkbox"
              className="accent-accent"
              checked={frEnabled}
              onChange={(e) => setFrEnabled(e.target.checked)}
            />
            Enable Frame Rate Limit
          </label>
          {frEnabled && (
            <SliderInput
              label="Frame Rate"
              value={frValue}
              min={frRange.min}
              max={frRange.max}
              step={frRange.step}
              unit="fps"
              onChange={setFrValue}
              className="mb-3"
            />
          )}
          <Button variant="primary" size="sm" loading={frApplying} onClick={applyFrameRate} className="mt-3">
            Apply
          </Button>
        </Card>
      )}

      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Processing tab — Pixel Format, ROI, Image Enhancement, Histogram
// ---------------------------------------------------------------------------

interface ImageProcessingProps {
  capabilities: CameraCapabilities;
  features: FeatureState;
  onFeatureChange: (updated: Partial<FeatureState>, invalidated?: string[]) => void;
}

function ImageProcessing({ capabilities, features, onFeatureChange }: ImageProcessingProps) {
  // Pixel format
  const [pixelFormat, setPixelFormat] = useState(features.pixelFormat?.format ?? 'Mono8');
  const [fmtApplying, setFmtApplying] = useState(false);

  // ROI
  const [roiW, setRoiW] = useState(features.roi?.width ?? 1456);
  const [roiH, setRoiH] = useState(features.roi?.height ?? 1088);
  const [roiOffX, setRoiOffX] = useState(features.roi?.offset_x ?? 0);
  const [roiOffY, setRoiOffY] = useState(features.roi?.offset_y ?? 0);
  const [roiApplying, setRoiApplying] = useState(false);
  const [roiCentering, setRoiCentering] = useState(false);

  // Image enhancement (local only — no backend endpoint in current spec)
  const [gamma, setGamma] = useState(1.0);
  const [blackLevel, setBlackLevel] = useState(0);
  const [sharpness, setSharpness] = useState(0);

  // UserSet
  const [userSetSlot, setUserSetSlot] = useState(features.userSet?.current_slot ?? 'Default');
  const [userSetLoading, setUserSetLoading] = useState(false);
  const [userSetSaving, setUserSetSaving] = useState(false);

  useEffect(() => {
    if (features.pixelFormat) setPixelFormat(features.pixelFormat.format);
  }, [features.pixelFormat]);
  useEffect(() => {
    if (features.roi) { setRoiW(features.roi.width); setRoiH(features.roi.height); setRoiOffX(features.roi.offset_x); setRoiOffY(features.roi.offset_y); }
  }, [features.roi]);
  useEffect(() => {
    if (features.userSet) setUserSetSlot(features.userSet.current_slot);
  }, [features.userSet]);

  const fmtCap = capabilities.pixel_format;
  const roiCap = capabilities.roi;
  const userSetCap = capabilities.user_set;

  const availableFormats = features.pixelFormat?.available ?? fmtCap?.available_values ?? ['Mono8', 'Mono12', 'BayerRG8', 'BayerRG12', 'RGB8'];
  const availableSlots = features.userSet?.available_slots ?? userSetCap?.slots ?? ['Default', 'UserSet1', 'UserSet2'];

  const roiWidthRange = features.roi?.width_range ?? { min: 1, max: 1456, step: 4 };
  const roiHeightRange = features.roi?.height_range ?? { min: 1, max: 1088, step: 4 };

  async function applyPixelFormat() {
    setFmtApplying(true);
    try {
      const res = await cameraApi.setPixelFormat({ format: pixelFormat });
      onFeatureChange({ pixelFormat: res }, res.invalidated);
    } catch { /* silent */ }
    finally { setFmtApplying(false); }
  }

  async function applyRoi() {
    setRoiApplying(true);
    try {
      const res = await cameraApi.setRoi({ width: roiW, height: roiH, offset_x: roiOffX, offset_y: roiOffY });
      onFeatureChange({ roi: res }, res.invalidated);
    } catch { /* silent */ }
    finally { setRoiApplying(false); }
  }

  async function centerRoi() {
    setRoiCentering(true);
    try {
      const res = await cameraApi.centerRoi();
      onFeatureChange({ roi: res }, res.invalidated);
    } catch { /* silent */ }
    finally { setRoiCentering(false); }
  }

  async function loadUserSet() {
    setUserSetLoading(true);
    try { await cameraApi.loadUserSet({ slot: userSetSlot }); } catch { /* silent */ }
    finally { setUserSetLoading(false); }
  }

  async function saveUserSet() {
    setUserSetSaving(true);
    try { await cameraApi.saveUserSet({ slot: userSetSlot }); } catch { /* silent */ }
    finally { setUserSetSaving(false); }
  }

  // Fake histogram data
  const histData = Array.from({ length: 32 }, (_, i) => ({
    bin: i * 8,
    count: Math.round(Math.random() * 1000 + 100),
  }));

  return (
    <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>

      {/* Pixel Format */}
      {(fmtCap?.supported ?? true) && (
        <Card>
          <CardTitle className="mb-3">Pixel Format</CardTitle>
          <div className="mb-3">
            <label className="text-[12px] text-text-tertiary block mb-1">Format</label>
            <select
              value={pixelFormat}
              onChange={(e) => setPixelFormat(e.target.value)}
              className="bg-surface-2 border border-border text-text-primary rounded text-[13px] px-2.5 py-1.5 w-full"
            >
              {availableFormats.map((f) => <option key={f}>{f}</option>)}
            </select>
          </div>
          <Button variant="primary" size="sm" loading={fmtApplying} onClick={applyPixelFormat}>
            Apply
          </Button>
        </Card>
      )}

      {/* ROI */}
      {(roiCap?.supported ?? true) && (
        <Card>
          <CardTitle className="mb-3">Region of Interest</CardTitle>
          <div className="grid grid-cols-2 gap-2.5 mb-3">
            <div>
              <label className="text-[12px] text-text-tertiary block mb-1">Width</label>
              <input
                type="number"
                min={roiWidthRange.min}
                max={roiWidthRange.max}
                step={roiWidthRange.step}
                value={roiW}
                onChange={(e) => setRoiW(Number(e.target.value))}
                className="bg-surface-2 border border-border text-text-primary rounded text-[13px] px-2 py-1.5 w-full"
              />
            </div>
            <div>
              <label className="text-[12px] text-text-tertiary block mb-1">Height</label>
              <input
                type="number"
                min={roiHeightRange.min}
                max={roiHeightRange.max}
                step={roiHeightRange.step}
                value={roiH}
                onChange={(e) => setRoiH(Number(e.target.value))}
                className="bg-surface-2 border border-border text-text-primary rounded text-[13px] px-2 py-1.5 w-full"
              />
            </div>
            <div>
              <label className="text-[12px] text-text-tertiary block mb-1">Offset X</label>
              <input
                type="number"
                min={0}
                value={roiOffX}
                onChange={(e) => setRoiOffX(Number(e.target.value))}
                className="bg-surface-2 border border-border text-text-primary rounded text-[13px] px-2 py-1.5 w-full"
              />
            </div>
            <div>
              <label className="text-[12px] text-text-tertiary block mb-1">Offset Y</label>
              <input
                type="number"
                min={0}
                value={roiOffY}
                onChange={(e) => setRoiOffY(Number(e.target.value))}
                className="bg-surface-2 border border-border text-text-primary rounded text-[13px] px-2 py-1.5 w-full"
              />
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="primary" size="sm" loading={roiApplying} onClick={applyRoi}>Apply</Button>
            <Button variant="secondary" size="sm" loading={roiCentering} onClick={centerRoi}>Center</Button>
          </div>
        </Card>
      )}

      {/* Image Enhancement (local) */}
      <Card>
        <CardTitle className="mb-3">Image Enhancement</CardTitle>
        <SliderInput label="Gamma" value={gamma} min={0.1} max={4.0} step={0.1} onChange={setGamma} className="mb-3" />
        <SliderInput label="Black Level" value={blackLevel} min={0} max={255} onChange={setBlackLevel} className="mb-3" />
        <SliderInput label="Sharpness" value={sharpness} min={0} max={100} onChange={setSharpness} />
        <Button variant="primary" size="sm" className="mt-3">Apply</Button>
      </Card>

      {/* UserSet */}
      {(userSetCap?.supported ?? false) && (
        <Card>
          <CardTitle className="mb-3">User Set</CardTitle>
          <div className="mb-3">
            <label className="text-[12px] text-text-tertiary block mb-1">Slot</label>
            <select
              value={userSetSlot}
              onChange={(e) => setUserSetSlot(e.target.value)}
              className="bg-surface-2 border border-border text-text-primary rounded text-[13px] px-2.5 py-1.5 w-full"
            >
              {availableSlots.map((s) => <option key={s}>{s}</option>)}
            </select>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" loading={userSetLoading} onClick={loadUserSet}>Load</Button>
            <Button variant="primary" size="sm" loading={userSetSaving} onClick={saveUserSet}>Save</Button>
          </div>
          {features.userSet?.default_slot && (
            <div className="text-[11px] text-text-tertiary mt-2">Default: {features.userSet.default_slot}</div>
          )}
        </Card>
      )}

      {/* Histogram — full width */}
      <Card className="col-span-full">
        <CardTitle className="mb-1">Histogram</CardTitle>
        <div className="text-[12px] text-text-tertiary mb-2">
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
  const [captures] = useState<{ id: number; ts: string; url: string }[]>([]);
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
                onClick={() => setLightbox(null)}
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
  const [capabilities, setCapabilities] = useState<CameraCapabilities>({});
  const [features, setFeatures] = useState<FeatureState>(EMPTY_FEATURES);
  const [latestMeta, setLatestMeta] = useState<FrameMeta | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Poll status
  useEffect(() => {
    function poll() { cameraApi.status().then(setStatus).catch(() => null); }
    poll();
    const id = setInterval(poll, 3000);
    return () => clearInterval(id);
  }, []);

  // WS for FrameMeta telemetry (always open when connected)
  useEffect(() => {
    if (!status?.connected) return;
    const ws = wsApi.camera((msg) => {
      if (msg.meta) setLatestMeta(msg.meta);
    });
    wsRef.current = ws;
    return () => { ws.close(); wsRef.current = null; };
  }, [status?.connected]);

  // Fetch all feature values
  async function fetchFeatures(caps: CameraCapabilities) {
    const next: Partial<FeatureState> = {};
    const fetches: Promise<void>[] = [];

    if (caps.exposure?.supported) fetches.push(cameraApi.getExposure().then((v) => { next.exposure = v; }).catch(() => {}));
    if (caps.gain?.supported) fetches.push(cameraApi.getGain().then((v) => { next.gain = v; }).catch(() => {}));
    if (caps.roi?.supported) fetches.push(cameraApi.getRoi().then((v) => { next.roi = v; }).catch(() => {}));
    if (caps.pixel_format?.supported) fetches.push(cameraApi.getPixelFormat().then((v) => { next.pixelFormat = v; }).catch(() => {}));
    if (caps.frame_rate?.supported) fetches.push(cameraApi.getFrameRate().then((v) => { next.frameRate = v; }).catch(() => {}));
    if (caps.trigger?.supported) fetches.push(cameraApi.getTrigger().then((v) => { next.trigger = v; }).catch(() => {}));
    if (caps.temperature?.supported) fetches.push(cameraApi.getTemperature().then((v) => { next.temperature = v.value_c; }).catch(() => {}));
    if (caps.user_set?.supported) fetches.push(cameraApi.getUserSet().then((v) => { next.userSet = v; }).catch(() => {}));

    await Promise.allSettled(fetches);
    setFeatures((prev) => ({ ...prev, ...next }));
  }

  // Re-fetch specific invalidated features
  async function refetchInvalidated(invalidated: string[], caps: CameraCapabilities) {
    const next: Partial<FeatureState> = {};
    const fetches: Promise<void>[] = [];

    for (const key of invalidated) {
      switch (key) {
        case 'exposure': fetches.push(cameraApi.getExposure().then((v) => { next.exposure = v; }).catch(() => {})); break;
        case 'gain': fetches.push(cameraApi.getGain().then((v) => { next.gain = v; }).catch(() => {})); break;
        case 'roi': fetches.push(cameraApi.getRoi().then((v) => { next.roi = v; }).catch(() => {})); break;
        case 'pixel_format': fetches.push(cameraApi.getPixelFormat().then((v) => { next.pixelFormat = v; }).catch(() => {})); break;
        case 'frame_rate': fetches.push(cameraApi.getFrameRate().then((v) => { next.frameRate = v; }).catch(() => {})); break;
        case 'trigger': fetches.push(cameraApi.getTrigger().then((v) => { next.trigger = v; }).catch(() => {})); break;
        case 'temperature': if (caps.temperature?.supported) fetches.push(cameraApi.getTemperature().then((v) => { next.temperature = v.value_c; }).catch(() => {})); break;
      }
    }
    await Promise.allSettled(fetches);
    setFeatures((prev) => ({ ...prev, ...next }));
  }

  // Handle feature update + invalidation cascade
  function handleFeatureChange(updated: Partial<FeatureState>, invalidated?: string[]) {
    setFeatures((prev) => ({ ...prev, ...updated }));
    if (invalidated && invalidated.length > 0) {
      refetchInvalidated(invalidated, capabilities);
    }
  }

  const refreshStatus = () => cameraApi.status().then(setStatus).catch(() => null);

  async function handleConnect() {
    const data = await cameraApi.connect();
    setCapabilities(data.capabilities);
    await refreshStatus();
    await fetchFeatures(data.capabilities);
  }

  async function handleDisconnect() {
    await cameraApi.disconnect();
    setCapabilities({});
    setFeatures(EMPTY_FEATURES);
    setLatestMeta(null);
    await refreshStatus();
  }

  async function handleResetDefaults() {
    await cameraApi.loadUserSet({ slot: 'Default' });
    // UserSetLoad can change every feature — refresh status + all feature
    // values so the UI reflects the reloaded camera state.
    await refreshStatus();
    await fetchFeatures(capabilities);
  }

  return (
    <div className="px-[clamp(12px,3vw,20px)] max-w-[1100px] mx-auto">
      <h2 className="text-text-primary text-[18px] font-semibold mb-1 mt-0">Camera</h2>
      <div className="text-[13px] text-text-tertiary mb-3.5">
        Allied Vision Alvium 1800 U-158m
      </div>

      <Card className="mb-4.5 p-3.5">
        <ConnectionControl
          label="Camera"
          connected={status?.connected ?? false}
          connectedLabel={status?.device ? `Connected — ${status.device.model}` : 'Connected'}
          disconnectedLabel="Disconnected"
          onConnect={handleConnect}
          onDisconnect={handleDisconnect}
          disconnectConfirm={{
            title: 'Disconnect camera?',
            description:
              'The Vimba X SDK will shut down cleanly (frame release → cam.__exit__ → VmbSystem.__exit__). ' +
              'Live streaming and capture will stop until you reconnect.',
          }}
        />
      </Card>

      {/* Temperature banner — shown when connected and supported */}
      {status?.connected && (capabilities.temperature?.supported ?? false) && (
        <div className="mb-3 px-3.5 py-2 bg-surface-2 border border-border rounded-lg flex gap-4 text-[13px] text-text-secondary items-center">
          <span className="text-text-tertiary">Sensor Temp:</span>
          <span className="numeric font-semibold">
            {latestMeta?.temperature_c?.toFixed(1) ?? features.temperature?.toFixed(1) ?? status.current_temperature_c?.toFixed(1) ?? '—'} °C
          </span>
          {status.current_fps != null && <>
            <span className="text-text-tertiary ml-auto">FPS:</span>
            <span className="numeric font-semibold">{(latestMeta?.fps_actual ?? status.current_fps).toFixed(1)}</span>
          </>}
        </div>
      )}

      <SubTabBar active={subTab} onChange={setSubTab} />

      {subTab === 'live' && (
        <LiveCapture status={status} frameMeta={latestMeta} />
      )}
      {subTab === 'acquisition' && (
        <Acquisition
          capabilities={capabilities}
          features={features}
          onFeatureChange={handleFeatureChange}
          onReset={status?.connected ? handleResetDefaults : undefined}
        />
      )}
      {subTab === 'processing' && (
        <ImageProcessing
          capabilities={capabilities}
          features={features}
          onFeatureChange={handleFeatureChange}
        />
      )}
      {subTab === 'gallery' && <Gallery />}
    </div>
  );
}
