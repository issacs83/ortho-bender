/**
 * SystemStatus.tsx — Displays aggregated system health (IPC, M7, camera, alarms).
 */

import { useEffect, useState } from "react";
import { systemApi, wsApi, type SystemStatus } from "../api/client";

const MOTION_STATE_LABELS: Record<number, string> = {
  0: "IDLE",
  1: "HOMING",
  2: "RUNNING",
  3: "JOGGING",
  4: "STOPPING",
  5: "FAULT",
  6: "ESTOP",
};

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: 4,
        fontSize: 12,
        fontWeight: 600,
        background: ok ? "#22c55e" : "#ef4444",
        color: "#fff",
        marginLeft: 8,
      }}
    >
      {ok ? "OK" : "FAIL"} — {label}
    </span>
  );
}

export function SystemStatus() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<string[]>([]);

  // Initial fetch
  useEffect(() => {
    systemApi.status().then(setStatus).catch((e) => setError(String(e)));
  }, []);

  // WebSocket system events
  useEffect(() => {
    const ws = wsApi.system((msg) => {
      if (msg.type === "heartbeat") {
        systemApi.status().then(setStatus).catch(() => null);
      } else {
        setEvents((prev) => [`[${msg.type}] ${msg.message}`, ...prev.slice(0, 19)]);
      }
    });
    return () => ws.close();
  }, []);

  const dark = { color: "#f1f5f9" };
  const muted = { color: "#94a3b8" };
  const tdStyle = { padding: "5px 8px", ...muted };
  const tdVal = { padding: "5px 8px", ...dark };

  if (error) return <div style={{ color: "#f87171", padding: 16 }}>System status error: {error}</div>;
  if (!status) return <div style={{ padding: 16, ...muted }}>Loading system status...</div>;

  return (
    <section style={{ fontFamily: "monospace", padding: 16, color: "#f1f5f9" }}>
      <h2 style={{ color: "#e2e8f0", marginTop: 4, marginBottom: 12, fontSize: 14, letterSpacing: 1, textTransform: "uppercase" }}>
        System Status
      </h2>
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <tbody>
          {[
            ["SDK Version",   status.sdk_version],
            ["Motion State",  MOTION_STATE_LABELS[status.motion_state] ?? status.motion_state],
          ].map(([label, val]) => (
            <tr key={label}>
              <td style={tdStyle}>{label}</td>
              <td style={tdVal}>{val}</td>
            </tr>
          ))}
          <tr><td style={tdStyle}>IPC (RPMsg)</td><td style={tdVal}><StatusBadge ok={status.ipc_connected} label="IPC" /></td></tr>
          <tr><td style={tdStyle}>M7 Heartbeat</td><td style={tdVal}><StatusBadge ok={status.m7_heartbeat_ok} label="M7" /></td></tr>
          <tr><td style={tdStyle}>Camera</td><td style={tdVal}><StatusBadge ok={status.camera_connected} label="Camera" /></td></tr>
          <tr>
            <td style={tdStyle}>Active Alarms</td>
            <td style={{ ...tdVal, color: status.active_alarms > 0 ? "#f87171" : "#4ade80" }}>
              {status.active_alarms}
            </td>
          </tr>
          <tr><td style={tdStyle}>CPU Temp</td><td style={tdVal}>{status.cpu_temp_c != null ? `${status.cpu_temp_c} °C` : "N/A"}</td></tr>
          <tr><td style={tdStyle}>Uptime</td><td style={tdVal}>{status.uptime_s.toFixed(0)} s</td></tr>
        </tbody>
      </table>

      {events.length > 0 && (
        <>
          <h3 style={{ color: "#94a3b8", fontSize: 12, marginTop: 16, marginBottom: 6, textTransform: "uppercase", letterSpacing: 1 }}>
            Recent Events
          </h3>
          <ul style={{ maxHeight: 200, overflowY: "auto", fontSize: 11, color: "#64748b", padding: "0 0 0 16px" }}>
            {events.map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        </>
      )}
    </section>
  );
}
