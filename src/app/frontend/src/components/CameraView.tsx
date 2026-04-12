/**
 * CameraView.tsx — Live camera feed and capture controls.
 *
 * Shows the MJPEG stream via <img src="/api/camera/stream" />.
 * Falls back to WebSocket JPEG frames if MJPEG is not available.
 */

import { useEffect, useRef, useState } from "react";
import { cameraApi, wsApi, type CameraStatus } from "../api/client";

export function CameraView() {
  const [status, setStatus] = useState<CameraStatus | null>(null);
  const [useWsFallback, setUseWsFallback] = useState(false);
  const [wsFrame, setWsFrame] = useState<string | null>(null);
  const [exposure, setExposure] = useState(5000);
  const [gain, setGain] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    cameraApi.status().then(setStatus).catch((e) => setError(String(e)));
  }, []);

  // WebSocket fallback for camera frames
  useEffect(() => {
    if (!useWsFallback) return;
    const ws = wsApi.camera((msg) => {
      if (msg.frame_b64) setWsFrame(msg.frame_b64);
    });
    return () => ws.close();
  }, [useWsFallback]);

  async function applySettings() {
    try {
      const s = await cameraApi.settings({ exposure_us: exposure, gain_db: gain });
      setStatus(s);
    } catch (e) {
      setError(String(e));
    }
  }

  async function capture() {
    const url = cameraApi.captureUrl();
    const link = document.createElement("a");
    link.href = url;
    link.download = `frame_${Date.now()}.jpg`;
    link.click();
  }

  const inputStyle = {
    width: 72, marginLeft: 6, background: "#0f172a", border: "1px solid #334155",
    color: "#f1f5f9", borderRadius: 4, padding: "3px 6px", fontFamily: "monospace",
  };
  const btnStyle = {
    padding: "4px 12px", background: "#1e293b", border: "1px solid #334155",
    color: "#94a3b8", borderRadius: 4, cursor: "pointer", fontFamily: "monospace",
  };

  return (
    <section style={{ fontFamily: "monospace", padding: 16, color: "#f1f5f9" }}>
      <h2 style={{ color: "#e2e8f0", marginTop: 4, marginBottom: 12, fontSize: 14, letterSpacing: 1, textTransform: "uppercase" }}>
        Camera
      </h2>

      {error && <div style={{ color: "#f87171", marginBottom: 8 }}>{error}</div>}

      {status && (
        <div style={{ marginBottom: 8, fontSize: 11, color: "#64748b" }}>
          <span style={{ color: "#94a3b8" }}>{status.backend ?? "N/A"}</span>
          {" | "}
          <span style={{ color: status.connected ? "#4ade80" : "#f87171" }}>
            {status.connected ? "Connected" : "Disconnected"}
          </span>
          {status.width && status.height && (
            <span> | {status.width}×{status.height}</span>
          )}
          {status.fps && <span> @ {status.fps.toFixed(1)} fps</span>}
        </div>
      )}

      {/* Live stream or WS fallback */}
      {!useWsFallback ? (
        <img
          src={cameraApi.streamUrl()}
          alt="Camera stream"
          style={{ maxWidth: "100%", border: "1px solid #334155", borderRadius: 4, display: "block" }}
          onError={() => setUseWsFallback(true)}
        />
      ) : wsFrame ? (
        <img
          src={`data:image/jpeg;base64,${wsFrame}`}
          alt="Camera frame (WS)"
          style={{ maxWidth: "100%", border: "1px solid #334155", borderRadius: 4, display: "block" }}
        />
      ) : (
        <div style={{ padding: 32, background: "#0f172a", textAlign: "center", color: "#475569", border: "1px solid #334155", borderRadius: 4 }}>
          No camera signal
        </div>
      )}

      {/* Settings */}
      <div style={{ marginTop: 12, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", color: "#94a3b8" }}>
        <label>
          Exposure (μs):
          <input type="number" value={exposure} onChange={(e) => setExposure(Number(e.target.value))} style={inputStyle} />
        </label>
        <label>
          Gain (dB):
          <input type="number" value={gain} min={0} onChange={(e) => setGain(Number(e.target.value))} style={{ ...inputStyle, width: 56 }} />
        </label>
        <button onClick={applySettings} style={btnStyle}>Apply</button>
        <button onClick={capture} style={{ ...btnStyle, color: "#7dd3fc", borderColor: "#1d4ed8" }}>Capture</button>
      </div>
    </section>
  );
}
