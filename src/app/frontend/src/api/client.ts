/**
 * client.ts — Typed API helper for the Ortho-Bender SDK REST API.
 *
 * All functions throw on HTTP error or on {success: false} responses.
 * WebSocket connections return native WebSocket instances.
 */

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

export interface CameraStatus {
  connected: boolean;
  device_id: string | null;
  width: number | null;
  height: number | null;
  exposure_us: number | null;
  gain_db: number | null;
  format: string | null;
  backend: string | null;
  fps: number | null;
  power_state: "on" | "standby" | "off";
}

export interface BendingStatus {
  running: boolean;
  current_step: number;
  total_steps: number;
  progress_pct: number;
  material: number | null;
  wire_diameter_mm: number | null;
}

export interface SystemStatus {
  motion_state: number;
  camera_connected: boolean;
  ipc_connected: boolean;
  m7_heartbeat_ok: boolean;
  active_alarms: number;
  uptime_s: number;
  cpu_temp_c: number | null;
  sdk_version: string;
}

export interface BcodeStep {
  L_mm: number;
  beta_deg: number;
  theta_deg: number;
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
  status: (): Promise<CameraStatus> =>
    request("/api/camera/status"),

  captureUrl: (): string =>
    `${BASE_URL}/api/camera/capture`,

  streamUrl: (): string =>
    `${BASE_URL}/api/camera/stream`,

  settings: (params: { exposure_us?: number; gain_db?: number; format?: string }): Promise<CameraStatus> =>
    request("/api/camera/settings", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  connect: (): Promise<CameraStatus> =>
    request("/api/camera/connect", { method: "POST" }),

  disconnect: (): Promise<CameraStatus> =>
    request("/api/camera/disconnect", { method: "POST" }),
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

export const wsApi = {
  motor:  (cb: WsHandler<{ type: string } & MotorStatus>): WebSocket =>
    openWs("/ws/motor", cb),

  camera: (cb: WsHandler<{ type: string; frame_b64: string; timestamp_us: number }>): WebSocket =>
    openWs("/ws/camera", cb),

  system: (cb: WsHandler<{ type: string; message: string; timestamp_us: number }>): WebSocket =>
    openWs("/ws/system", cb),
};
