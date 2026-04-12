/**
 * MotorControl.tsx — Motor jog panel + real-time axis position chart.
 *
 * Displays live position history for all active axes via /ws/motor.
 * Jog buttons call /api/motor/jog directly.
 */

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { motorApi, wsApi, type MotorStatus, type AxisStatus } from "../api/client";

const AXIS_NAMES = ["FEED (mm)", "BEND (°)", "ROTATE (°)", "LIFT (°)"];
const AXIS_COLORS = ["#3b82f6", "#f59e0b", "#10b981", "#a78bfa"];
const JOG_SPEED = 10;     // mm/s or deg/s default jog speed
const HISTORY_LEN = 60;   // data points to show in chart (~6 s at 100 ms)

interface ChartPoint {
  t: number;
  [key: string]: number;
}

export function MotorControl() {
  const [status, setStatus] = useState<MotorStatus | null>(null);
  const [history, setHistory] = useState<ChartPoint[]>([]);
  const [error, setError] = useState<string | null>(null);
  const tRef = useRef(0);

  // Initial status
  useEffect(() => {
    motorApi.status().then(setStatus).catch((e) => setError(String(e)));
  }, []);

  // Live motor WS stream
  useEffect(() => {
    const ws = wsApi.motor((msg) => {
      setStatus(msg);
      const point: ChartPoint = { t: tRef.current++ };
      msg.axes.forEach((ax: AxisStatus) => {
        point[AXIS_NAMES[ax.axis]] = parseFloat(ax.position.toFixed(3));
      });
      setHistory((prev) => [...prev.slice(-(HISTORY_LEN - 1)), point]);
    });
    return () => ws.close();
  }, []);

  async function jog(axis: number, direction: 1 | -1) {
    try {
      const s = await motorApi.jog(axis, direction, JOG_SPEED, 5);
      setStatus(s);
    } catch (e) {
      setError(String(e));
    }
  }

  async function home() {
    try {
      const s = await motorApi.home(0);
      setStatus(s);
    } catch (e) {
      setError(String(e));
    }
  }

  async function estop() {
    try {
      const s = await motorApi.estop();
      setStatus(s);
    } catch (e) {
      setError(String(e));
    }
  }

  const motionStateName = status
    ? ["IDLE","HOMING","RUNNING","JOGGING","STOPPING","FAULT","ESTOP"][status.state] ?? "?"
    : "—";

  const btnBase: CSSProperties = { padding: "6px 14px", border: "none", borderRadius: 4, cursor: "pointer", fontFamily: "monospace", fontWeight: 600 };
  const thStyle: CSSProperties = { padding: "6px 8px", textAlign: "left", color: "#64748b", fontWeight: 600, borderBottom: "1px solid #334155", fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5 };
  const tdStyle: CSSProperties = { padding: "5px 8px", color: "#cbd5e1", borderBottom: "1px solid #1e293b" };

  return (
    <section style={{ fontFamily: "monospace", padding: 16, color: "#f1f5f9" }}>
      <h2 style={{ color: "#e2e8f0", marginTop: 4, marginBottom: 12, fontSize: 14, letterSpacing: 1, textTransform: "uppercase" }}>
        Motor Control
      </h2>

      {error && <div style={{ color: "#f87171", marginBottom: 8 }}>{error}</div>}

      <div style={{ marginBottom: 12, color: "#94a3b8" }}>
        <strong style={{ color: "#f1f5f9" }}>State:</strong>{" "}
        <span style={{ color: motionStateName === "ESTOP" || motionStateName === "FAULT" ? "#f87171" : "#4ade80" }}>
          {motionStateName}
        </span>
        {status && (
          <span style={{ marginLeft: 16, color: "#64748b" }}>
            Step: {status.current_step} / {status.total_steps}
          </span>
        )}
      </div>

      {/* Axis position table */}
      {status && (
        <table style={{ borderCollapse: "collapse", marginBottom: 16, width: "100%" }}>
          <thead>
            <tr>
              <th style={thStyle}>Axis</th>
              <th style={{ ...thStyle, textAlign: "center" }}>Position</th>
              <th style={{ ...thStyle, textAlign: "center" }}>Velocity</th>
              <th style={{ ...thStyle, textAlign: "center" }}>Jog</th>
            </tr>
          </thead>
          <tbody>
            {status.axes.map((ax) => (
              <tr key={ax.axis}>
                <td style={{ ...tdStyle, color: AXIS_COLORS[ax.axis] }}>{AXIS_NAMES[ax.axis]}</td>
                <td style={{ ...tdStyle, textAlign: "center" }}>{ax.position.toFixed(3)}</td>
                <td style={{ ...tdStyle, textAlign: "center" }}>{ax.velocity.toFixed(2)}</td>
                <td style={{ ...tdStyle, textAlign: "center" }}>
                  <button onClick={() => jog(ax.axis, -1)} style={{ ...btnBase, background: "#1e3a5f", color: "#93c5fd", marginRight: 4 }}>◀</button>
                  <button onClick={() => jog(ax.axis, +1)} style={{ ...btnBase, background: "#1e3a5f", color: "#93c5fd" }}>▶</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Control buttons */}
      <div style={{ marginBottom: 16, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button onClick={home} style={{ ...btnBase, background: "#1d4ed8", color: "#fff" }}>Home All</button>
        <button onClick={() => motorApi.stop().then(setStatus)} style={{ ...btnBase, background: "#92400e", color: "#fde68a" }}>Stop</button>
        <button onClick={estop} style={{ ...btnBase, background: "#7f1d1d", color: "#fca5a5", letterSpacing: 1 }}>⚠ E-STOP</button>
        <button onClick={() => motorApi.reset().then(setStatus)} style={{ ...btnBase, background: "#1e293b", color: "#94a3b8", border: "1px solid #334155" }}>Reset Fault</button>
      </div>

      {/* Position history chart */}
      {history.length > 1 && (
        <div style={{ height: 220 }}>
          <h3 style={{ marginBottom: 4, color: "#94a3b8", fontSize: 12, textTransform: "uppercase", letterSpacing: 1 }}>Position History (live)</h3>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history} style={{ background: "#0f172a", borderRadius: 6 }}>
              <XAxis dataKey="t" hide />
              <YAxis stroke="#475569" tick={{ fill: "#64748b", fontSize: 10 }} />
              <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155", color: "#f1f5f9" }} />
              <Legend wrapperStyle={{ color: "#94a3b8", fontSize: 11 }} />
              {AXIS_NAMES.map((name, i) => (
                <Line key={name} type="monotone" dataKey={name} stroke={AXIS_COLORS[i]} dot={false} isAnimationActive={false} strokeWidth={1.5} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
