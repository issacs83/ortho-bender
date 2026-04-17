/**
 * client.ts — Typed API helper for the Ortho-Bender SDK REST API.
 *
 * All functions throw on HTTP error or on {success: false} responses.
 * WebSocket connections return native WebSocket instances.
 *
 * The diagnostic WebSocket (/ws/motor/diag) requests binary MessagePack
 * frames (?format=msgpack) for ~80 % bandwidth reduction at 200 Hz.
 * The server falls back to JSON automatically when msgpack is unavailable.
 */

import { decode as msgpackDecode } from "@msgpack/msgpack";

const BASE_URL = import.meta.env.VITE_API_BASE ?? "";

// ---------------------------------------------------------------------------
// Types (mirrors server/models/schemas.py)
// ---------------------------------------------------------------------------

export type MotionState =
  | "IDLE" | "HOMING" | "RUNNING" | "JOGGING" | "STOPPING" | "FAULT" | "ESTOP";

export interface AxisStatus {
  axis: number;
  position: number;
  velocity: number;
  drv_status: number;
  sg_result: number;
  cs_actual: number;
}

export interface MotorStatus {
  state: number;
  axes: AxisStatus[];
  current_step: number;
  total_steps: number;
  axis_mask: number;
  driver_enabled: boolean;
}

// Camera feature types (matches backend camera_schemas.py)
export interface NumericRange { min: number; max: number; step: number }
export interface CamDeviceInfo { model: string; serial: string; firmware: string; vendor: string }
export interface FrameMeta {
  timestamp_us: number; exposure_us: number; gain_db: number;
  temperature_c: number | null; fps_actual: number; width: number; height: number;
}
export interface FeatureCapability {
  supported: boolean; range?: NumericRange; auto_available?: boolean;
  available_values?: string[]; slots?: string[];
}
export interface CameraCapabilities { [feature: string]: FeatureCapability }
export interface ConnectData { device: CamDeviceInfo; capabilities: CameraCapabilities }
export interface ExposureInfo {
  auto: boolean; time_us: number; range: NumericRange;
  auto_available: boolean; invalidated: string[];
}
export interface GainInfo {
  auto: boolean; value_db: number; range: NumericRange;
  auto_available: boolean; invalidated: string[];
}
export interface RoiInfo {
  width: number; height: number; offset_x: number; offset_y: number;
  width_range: NumericRange; height_range: NumericRange;
  offset_x_range: NumericRange; offset_y_range: NumericRange;
  invalidated: string[];
}
export interface PixelFormatInfo {
  format: string; available: string[]; invalidated: string[];
}
export interface FrameRateInfo {
  enable: boolean; value: number; range: NumericRange; invalidated: string[];
}
export interface TriggerInfo {
  mode: string; source: string | null; available_modes: string[];
  available_sources: string[]; invalidated: string[];
}
export interface UserSetInfo {
  current_slot: string; available_slots: string[]; default_slot: string;
}

export interface CameraStatus {
  connected: boolean;
  streaming: boolean;
  device: CamDeviceInfo | null;
  current_exposure_us: number | null;
  current_gain_db: number | null;
  current_temperature_c: number | null;
  current_fps: number | null;
  current_pixel_format: string | null;
  current_roi: { width: number; height: number; offset_x: number; offset_y: number } | null;
  current_trigger_mode: string | null;
}

export interface BendingStatus {
  running: boolean;
  current_step: number;
  total_steps: number;
  progress_pct: number;
  material: number | null;
  wire_diameter_mm: number | null;
}

export interface DriverProbeResult {
  driver: string;
  connected: boolean;
  chip: string;
}

export interface SystemStatus {
  motion_state: number;
  camera_connected: boolean;
  camera_model: string | null;
  ipc_connected: boolean;
  m7_heartbeat_ok: boolean;
  motor_connected: boolean;
  motor_model: string | null;
  active_alarms: number;
  uptime_s: number;
  cpu_temp_c: number | null;
  sdk_version: string;
  driver_probe: Record<string, DriverProbeResult>;
}

export interface BcodeStep {
  L_mm: number;
  beta_deg: number;
  theta_deg: number;
}

export interface SpiTestResultItem {
  driver: string;
  ok: boolean;
  latency_us: number | null;
  error: string | null;
}

export interface DiagRegisterResult {
  driver: string;
  addr: string;
  value: number;
  value_hex: string;
}

export interface DiagDumpResult {
  driver: string;
  registers: Record<string, string>;
}

export interface DiagBackendInfo {
  backend: string;
  spi_device: string | null;
  spi_speed_hz: number | null;
  drivers: string[];
}

export interface DiagEvent {
  type: string;
  drivers: Record<string, { sg_result: number; stst: boolean; ot: boolean; otpw: boolean; s2ga: boolean; s2gb: boolean; ola: boolean; olb: boolean }>;
  timestamp_us: number;
}

// ---------------------------------------------------------------------------
// HTTP helper
// ---------------------------------------------------------------------------

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }

  const envelope = await res.json();
  if (!envelope.success) {
    throw new Error(`[${envelope.code}] ${envelope.error}`);
  }
  return envelope.data as T;
}

// ---------------------------------------------------------------------------
// Motor API
// ---------------------------------------------------------------------------

export const motorApi = {
  status: (): Promise<MotorStatus> =>
    request("/api/motor/status"),

  move: (axis: number, distance: number, speed: number): Promise<MotorStatus> =>
    request("/api/motor/move", {
      method: "POST",
      body: JSON.stringify({ axis, distance, speed }),
    }),

  jog: (axis: number, direction: 1 | -1, speed: number, distance = 0): Promise<MotorStatus> =>
    request("/api/motor/jog", {
      method: "POST",
      body: JSON.stringify({ axis, direction, speed, distance }),
    }),

  home: (axis_mask = 0): Promise<MotorStatus> =>
    request("/api/motor/home", {
      method: "POST",
      body: JSON.stringify({ axis_mask }),
    }),

  stop: (): Promise<MotorStatus> =>
    request("/api/motor/stop", { method: "POST" }),

  estop: (): Promise<MotorStatus> =>
    request("/api/motor/estop", { method: "POST" }),

  reset: (): Promise<MotorStatus> =>
    request("/api/motor/reset", { method: "POST", body: JSON.stringify({ axis_mask: 0 }) }),

  enable: (): Promise<MotorStatus> =>
    request("/api/motor/enable", { method: "POST" }),

  disable: (): Promise<MotorStatus> =>
    request("/api/motor/disable", { method: "POST" }),
};

// ---------------------------------------------------------------------------
// Camera API
// ---------------------------------------------------------------------------

export const cameraApi = {
  // Connection & status
  connect: (): Promise<ConnectData> =>
    request("/api/camera/connect", { method: "POST" }),
  disconnect: (): Promise<void> =>
    request("/api/camera/disconnect", { method: "POST" }),
  status: () =>
    request<CameraStatus>("/api/camera/status"),
  capabilities: (): Promise<CameraCapabilities> =>
    request("/api/camera/capabilities"),
  deviceInfo: (): Promise<CamDeviceInfo> =>
    request("/api/camera/device-info"),

  // Exposure
  getExposure: (): Promise<ExposureInfo> =>
    request("/api/camera/exposure"),
  setExposure: (params: { auto: boolean; time_us?: number }): Promise<ExposureInfo> =>
    request("/api/camera/exposure", { method: "POST", body: JSON.stringify(params) }),

  // Gain
  getGain: (): Promise<GainInfo> =>
    request("/api/camera/gain"),
  setGain: (params: { auto: boolean; value_db?: number }): Promise<GainInfo> =>
    request("/api/camera/gain", { method: "POST", body: JSON.stringify(params) }),

  // ROI
  getRoi: (): Promise<RoiInfo> =>
    request("/api/camera/roi"),
  setRoi: (params: { width: number; height: number; offset_x?: number; offset_y?: number }): Promise<RoiInfo> =>
    request("/api/camera/roi", { method: "POST", body: JSON.stringify(params) }),
  centerRoi: (): Promise<RoiInfo> =>
    request("/api/camera/roi/center", { method: "POST" }),

  // Pixel format
  getPixelFormat: (): Promise<PixelFormatInfo> =>
    request("/api/camera/pixel-format"),
  setPixelFormat: (params: { format: string }): Promise<PixelFormatInfo> =>
    request("/api/camera/pixel-format", { method: "POST", body: JSON.stringify(params) }),

  // Frame rate
  getFrameRate: (): Promise<FrameRateInfo> =>
    request("/api/camera/frame-rate"),
  setFrameRate: (params: { enable: boolean; value?: number }): Promise<FrameRateInfo> =>
    request("/api/camera/frame-rate", { method: "POST", body: JSON.stringify(params) }),

  // Trigger
  getTrigger: (): Promise<TriggerInfo> =>
    request("/api/camera/trigger"),
  setTrigger: (params: { mode: string; source?: string }): Promise<TriggerInfo> =>
    request("/api/camera/trigger", { method: "POST", body: JSON.stringify(params) }),
  fireTrigger: (): Promise<void> =>
    request("/api/camera/trigger/fire", { method: "POST" }),

  // Temperature
  getTemperature: (): Promise<{ value_c: number }> =>
    request("/api/camera/temperature"),

  // UserSet
  getUserSet: (): Promise<UserSetInfo> =>
    request("/api/camera/user-set"),
  loadUserSet: (params: { slot: string }): Promise<void> =>
    request("/api/camera/user-set/load", { method: "POST", body: JSON.stringify(params) }),
  saveUserSet: (params: { slot: string }): Promise<void> =>
    request("/api/camera/user-set/save", { method: "POST", body: JSON.stringify(params) }),
  setDefaultUserSet: (params: { slot: string }): Promise<void> =>
    request("/api/camera/user-set/default", { method: "POST", body: JSON.stringify(params) }),

  // Capture & stream
  captureUrl: (): string => `${BASE_URL}/api/camera/capture`,
  streamUrl: (): string => `${BASE_URL}/api/camera/stream`,
};

// ---------------------------------------------------------------------------
// Bending API
// ---------------------------------------------------------------------------

export const bendingApi = {
  status: (): Promise<BendingStatus> =>
    request("/api/bending/status"),

  execute: (
    steps: BcodeStep[],
    material = 0,
    wire_diameter_mm = 0.457,
  ): Promise<BendingStatus> =>
    request("/api/bending/execute", {
      method: "POST",
      body: JSON.stringify({ steps, material, wire_diameter_mm }),
    }),

  stop: (): Promise<{ motor: MotorStatus; bending: BendingStatus }> =>
    request("/api/bending/stop", { method: "POST" }),
};

// ---------------------------------------------------------------------------
// System API
// ---------------------------------------------------------------------------

export const systemApi = {
  status: (): Promise<SystemStatus> =>
    request("/api/system/status"),

  version: (): Promise<{ sdk_version: string; m7_firmware: string | null }> =>
    request("/api/system/version"),

  reboot: (): Promise<{ message: string }> =>
    request("/api/system/reboot", {
      method: "POST",
      body: JSON.stringify({ confirm: true }),
    }),
};

// ---------------------------------------------------------------------------
// Diagnostics API
// ---------------------------------------------------------------------------

export const diagApi = {
  backend: (): Promise<DiagBackendInfo> =>
    request("/api/motor/diag/backend"),

  probe: (): Promise<{ drivers: DriverProbeResult[] }> =>
    request("/api/motor/diag/probe"),

  spiTest: (): Promise<{ results: SpiTestResultItem[] }> =>
    request("/api/motor/diag/spi-test"),

  readRegister: (driver: string, addr: string): Promise<DiagRegisterResult> =>
    request(`/api/motor/diag/register/${driver}/${addr}`),

  writeRegister: (driver: string, addr: string, value: number): Promise<DiagRegisterResult> =>
    request(`/api/motor/diag/register/${driver}/${addr}`, {
      method: "POST",
      body: JSON.stringify({ value }),
    }),

  dump: (driver: string): Promise<DiagDumpResult> =>
    request(`/api/motor/diag/dump/${driver}`),
};

// ---------------------------------------------------------------------------
// WebSocket helpers
// ---------------------------------------------------------------------------

type WsHandler<T> = (data: T) => void;

function openWs<T>(path: string, onMessage: WsHandler<T>): WebSocket {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = import.meta.env.VITE_WS_HOST ?? window.location.host;
  const ws = new WebSocket(`${proto}//${host}${path}`);
  ws.onmessage = (ev) => {
    try {
      onMessage(JSON.parse(ev.data) as T);
    } catch {
      // ignore malformed frames
    }
  };
  return ws;
}

/**
 * Open a WebSocket that requests MessagePack binary frames (?format=msgpack).
 *
 * Binary frames are decoded with @msgpack/msgpack.  If the server sends a
 * text frame (e.g., during graceful fallback to JSON), it is parsed as JSON
 * so callers always receive typed objects regardless of wire format.
 */
function openWsMsgpack<T>(path: string, onMessage: WsHandler<T>): WebSocket {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = import.meta.env.VITE_WS_HOST ?? window.location.host;
  const ws = new WebSocket(`${proto}//${host}${path}?format=msgpack`);
  // Receive ArrayBuffer for binary frames
  ws.binaryType = "arraybuffer";
  ws.onmessage = (ev) => {
    try {
      if (ev.data instanceof ArrayBuffer) {
        // Binary MessagePack frame
        onMessage(msgpackDecode(new Uint8Array(ev.data)) as T);
      } else {
        // Text frame — JSON fallback (server without msgpack installed)
        onMessage(JSON.parse(ev.data as string) as T);
      }
    } catch {
      // ignore malformed frames
    }
  };
  return ws;
}

export const wsApi = {
  motor:  (cb: WsHandler<{ type: string } & MotorStatus>): WebSocket =>
    openWs("/ws/motor", cb),

  camera: (cb: WsHandler<{ type: string; frame_b64: string; width: number; height: number; timestamp_us: number; meta?: FrameMeta }>): WebSocket =>
    openWs("/ws/camera", cb),

  system: (cb: WsHandler<{ type: string; message: string; timestamp_us: number }>): WebSocket =>
    openWs("/ws/system", cb),

  /**
   * Diagnostic WebSocket — 200 Hz StallGuard2 / DRV_STATUS stream.
   *
   * Connects with ``?format=msgpack`` to receive binary frames (~80 % smaller
   * than equivalent JSON).  Falls back transparently to JSON text if the
   * server does not have msgpack installed.
   */
  motorDiag: (cb: WsHandler<DiagEvent>): WebSocket =>
    openWsMsgpack("/ws/motor/diag", cb),
};
