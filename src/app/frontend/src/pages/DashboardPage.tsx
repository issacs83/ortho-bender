/**
 * DashboardPage.tsx — System overview dashboard with 2x2 card grid.
 */

import { useEffect, useState } from 'react';
import { motorApi, systemApi, type MotorStatus, type SystemStatus } from '../api/client';
import { StatusBadge } from '../components/ui/StatusBadge';
import { MotionStatePill } from '../components/ui/MotionStatePill';
import { ConfirmModal } from '../components/ui/ConfirmModal';
import { SkeletonLoader } from '../components/ui/SkeletonLoader';
import { useMotorWs } from '../hooks/useMotorWs';
import { useSystemWs, type SystemEvent } from '../hooks/useSystemWs';
import { AXIS_COLORS, AXIS_NAMES, AXIS_UNITS, BG_PANEL, BG_PRIMARY, BORDER, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED } from '../constants';
import type { Page } from '../App';

interface DashboardPageProps {
  onNavigate: (page: Page) => void;
}

function formatUptime(s: number): string {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${d}d ${h}h ${m}m`;
}

function getSeverity(type: string): 'error' | 'warning' | 'info' {
  if (type.includes('error') || type.includes('fault')) return 'error';
  if (type.includes('warn')) return 'warning';
  return 'info';
}

export function DashboardPage({ onNavigate }: DashboardPageProps) {
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);
  const [staticMotor, setStaticMotor] = useState<MotorStatus | null>(null);
  const [motorError, setMotorError] = useState(false);
  const [showHomeModal, setShowHomeModal] = useState(false);
  const [showSystemCheckModal, setShowSystemCheckModal] = useState(false);
  const [lastMotorUpdate, setLastMotorUpdate] = useState<string | null>(null);
  const [loadingAction, setLoadingAction] = useState<string | null>(null);

  const liveMotor = useMotorWs();
  const systemEvents = useSystemWs();

  const motorStatus = liveMotor ?? staticMotor;

  // Periodic polling (3s system, 2s motor)
  useEffect(() => {
    function pollSys() { systemApi.status().then(setSysStatus).catch(() => null); }
    function pollMotor() {
      motorApi.status().then((s) => { setStaticMotor(s); setMotorError(false); })
        .catch(() => setMotorError(true));
    }
    pollSys();
    pollMotor();
    const sysId = setInterval(pollSys, 3000);
    const motId = setInterval(pollMotor, 2000);
    return () => { clearInterval(sysId); clearInterval(motId); };
  }, []);

  useEffect(() => {
    if (liveMotor) setLastMotorUpdate(new Date().toLocaleTimeString());
  }, [liveMotor]);

  async function homeAll() {
    setLoadingAction('home');
    try { await motorApi.home(0); } catch { /* ignore */ }
    finally { setLoadingAction(null); setShowHomeModal(false); }
  }

  async function resetFault() {
    setLoadingAction('reset');
    try { await motorApi.reset(); } catch { /* ignore */ }
    finally { setLoadingAction(null); }
  }

  const cardStyle = {
    background: BG_PANEL,
    border: `1px solid ${BORDER}`,
    borderRadius: 8,
    padding: 20,
  };

  const btnBase = {
    padding: '9px 14px',
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
    fontSize: 13,
    fontWeight: 600,
    width: '100%',
    textAlign: 'left' as const,
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  };

  const isFault = (motorStatus?.state ?? 0) === 5;

  return (
    <div style={{ padding: '16px clamp(12px, 3vw, 20px)', maxWidth: 1100, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 16px', color: TEXT_PRIMARY, fontSize: 18 }}>Dashboard</h2>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>

        {/* System Health */}
        <div style={cardStyle}>
          <h3 style={{ margin: '0 0 16px', fontSize: 14, color: TEXT_PRIMARY }}>System Health</h3>
          {!sysStatus ? (
            <SkeletonLoader lines={5} />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 13, color: TEXT_MUTED }}>Motion State</span>
                <MotionStatePill stateNum={sysStatus.motion_state} />
              </div>

              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <StatusBadge variant={sysStatus.ipc_connected ? 'success' : 'error'} label="IPC" />
                <StatusBadge variant={sysStatus.m7_heartbeat_ok ? 'success' : 'error'} label="M7" />
                <StatusBadge variant={sysStatus.camera_connected ? 'success' : 'error'} label="CAM" />
              </div>

              {sysStatus.driver_probe && Object.keys(sysStatus.driver_probe).length > 0 && (
                <div>
                  <span style={{ fontSize: 11, color: TEXT_MUTED, display: 'block', marginBottom: 4 }}>Motor Drivers</span>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {Object.values(sysStatus.driver_probe).map((dp) => (
                      <StatusBadge
                        key={dp.driver}
                        variant={dp.connected ? 'success' : 'error'}
                        label={dp.connected ? dp.chip : dp.driver}
                      />
                    ))}
                  </div>
                </div>
              )}

              {[
                ['CPU Temp', sysStatus.cpu_temp_c != null ? `${sysStatus.cpu_temp_c.toFixed(1)} °C` : 'N/A'],
                ['Uptime',   formatUptime(sysStatus.uptime_s)],
                ['SDK',      sysStatus.sdk_version],
              ].map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 13, color: TEXT_MUTED }}>{k}</span>
                  <span style={{ fontSize: 13, color: TEXT_PRIMARY }}>{v}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Motor Status */}
        <div style={cardStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 14, color: TEXT_PRIMARY }}>Motor Status</h3>
            {lastMotorUpdate && (
              <span style={{ fontSize: 11, color: TEXT_MUTED }}>Updated {lastMotorUpdate}</span>
            )}
          </div>

          {!motorStatus && !motorError ? (
            <SkeletonLoader lines={4} />
          ) : !motorStatus && motorError ? (
            <div style={{ textAlign: 'center', padding: 24, color: TEXT_MUTED }}>
              <div style={{ fontSize: 13, marginBottom: 8 }}>Motor not available</div>
              <div style={{ fontSize: 11 }}>M7 IPC not responding. Check Connection page.</div>
            </div>
          ) : motorStatus ? (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  {['Axis', 'Position', 'Velocity', 'Status'].map((h) => (
                    <th key={h} style={{ padding: '4px 8px', textAlign: 'left', color: TEXT_MUTED, fontSize: 11, borderBottom: `1px solid ${BORDER}`, fontWeight: 600 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {motorStatus.axes.map((ax) => (
                  <tr key={ax.axis}>
                    <td style={{ padding: '6px 8px', color: AXIS_COLORS[ax.axis], fontWeight: 600 }}>
                      {AXIS_NAMES[ax.axis]}
                    </td>
                    <td style={{ padding: '6px 8px', color: TEXT_PRIMARY }}>
                      {ax.position.toFixed(3)} {AXIS_UNITS[ax.axis]}
                    </td>
                    <td style={{ padding: '6px 8px', color: TEXT_PRIMARY }}>
                      {ax.velocity.toFixed(2)}
                    </td>
                    <td style={{ padding: '6px 8px' }}>
                      <StatusBadge variant={ax.drv_status === 0 ? 'success' : 'error'} label={ax.drv_status === 0 ? 'OK' : 'ERR'} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </div>

        {/* Quick Actions */}
        <div style={cardStyle}>
          <h3 style={{ margin: '0 0 16px', fontSize: 14, color: TEXT_PRIMARY }}>Quick Actions</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <button
              onClick={() => onNavigate('bending')}
              style={{ ...btnBase, background: '#1d4ed8', color: '#fff' }}
            >
              <span>Start Bending</span>
            </button>
            <button
              onClick={() => setShowHomeModal(true)}
              disabled={loadingAction === 'home'}
              style={{ ...btnBase, background: '#1e293b', color: TEXT_SECONDARY, border: `1px solid ${BORDER}`, opacity: loadingAction === 'home' ? 0.7 : 1 }}
            >
              {loadingAction === 'home' && <span style={{ display: 'inline-block', width: 14, height: 14, border: '2px solid #475569', borderTop: '2px solid #93c5fd', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />}
              <span>Home All Axes</span>
            </button>
            <button
              onClick={() => onNavigate('camera')}
              style={{ ...btnBase, background: '#1e293b', color: TEXT_SECONDARY, border: `1px solid ${BORDER}` }}
            >
              <span>Open Camera</span>
            </button>
            <button
              onClick={resetFault}
              disabled={!isFault || loadingAction === 'reset'}
              style={{ ...btnBase, background: isFault ? '#78350f' : '#1e293b', color: isFault ? '#fcd34d' : TEXT_MUTED, border: `1px solid ${BORDER}`, opacity: isFault ? 1 : 0.5, cursor: isFault ? 'pointer' : 'not-allowed' }}
            >
              {loadingAction === 'reset' && <span style={{ display: 'inline-block', width: 14, height: 14, border: '2px solid #475569', borderTop: '2px solid #fcd34d', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />}
              <span>Reset Fault</span>
            </button>
            <button
              onClick={() => setShowSystemCheckModal(true)}
              style={{ ...btnBase, background: '#1e293b', color: TEXT_SECONDARY, border: `1px solid ${BORDER}`, gridColumn: '1 / -1' }}
            >
              <span>System Check</span>
            </button>
          </div>
        </div>

        {/* Alarm History */}
        <div style={cardStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 14, color: TEXT_PRIMARY }}>Alarm History</h3>
            <div style={{ display: 'flex', gap: 8 }}>
              <button style={{ fontSize: 12, background: '#1e293b', border: `1px solid ${BORDER}`, color: TEXT_SECONDARY, padding: '4px 10px', borderRadius: 4, cursor: 'pointer' }}>
                View All
              </button>
              <button style={{ fontSize: 12, background: '#1e293b', border: `1px solid ${BORDER}`, color: TEXT_SECONDARY, padding: '4px 10px', borderRadius: 4, cursor: 'pointer' }}>
                Export CSV
              </button>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 200, overflowY: 'auto' }}>
            {systemEvents.length === 0 ? (
              <div style={{ fontSize: 13, color: TEXT_MUTED, textAlign: 'center', padding: 20 }}>No alarms</div>
            ) : systemEvents.slice(0, 10).map((ev: SystemEvent, i: number) => {
              const sev = getSeverity(ev.type);
              return (
                <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '6px 8px', background: BG_PRIMARY, borderRadius: 4 }}>
                  <StatusBadge variant={sev} label={sev.toUpperCase()} />
                  <span style={{ fontSize: 12, color: TEXT_SECONDARY, flex: 1 }}>{ev.message}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {showHomeModal && (
        <ConfirmModal
          title="Home All Axes"
          description="This will move all axes to their home positions. Ensure no wire is loaded."
          confirmLabel="Home All"
          confirmVariant="primary"
          onConfirm={homeAll}
          onCancel={() => setShowHomeModal(false)}
        />
      )}

      {showSystemCheckModal && (
        <ConfirmModal
          title="System Check"
          description="Running connection check to all subsystems (Board, IPC, M7, Camera)..."
          confirmLabel="OK"
          confirmVariant="primary"
          onConfirm={() => { setShowSystemCheckModal(false); systemApi.status().then(setSysStatus).catch(() => null); }}
          onCancel={() => setShowSystemCheckModal(false)}
        />
      )}
    </div>
  );
}
