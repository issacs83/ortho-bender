/**
 * DashboardPage.tsx — System overview dashboard with KPI strip + 2x2 card grid.
 * Fully Tailwind-based, no inline styles.
 */

import { useEffect, useState } from 'react';
import { Bell } from 'lucide-react';
import { motorApi, systemApi, type MotorStatus, type SystemStatus } from '../api/client';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ConfirmModal } from '../components/ui/ConfirmModal';
import { SkeletonLoader } from '../components/ui/SkeletonLoader';
import { EmptyState } from '../components/ui/EmptyState';
import { Button } from '../components/ui/Button';
import { Card, CardTitle } from '../components/ui/Card';
import { KpiStrip } from '../components/domain/KpiStrip';
import { AxisStatusRow } from '../components/domain/AxisStatusRow';
import { useMotorWs } from '../hooks/useMotorWs';
import { useSystemWs, type SystemEvent } from '../hooks/useSystemWs';
import type { Page } from '../App';

interface DashboardPageProps {
  onNavigate: (page: Page) => void;
}

function getSeverity(type: string): 'error' | 'warning' | 'info' {
  if (type.includes('error') || type.includes('fault')) return 'error';
  if (type.includes('warn')) return 'warning';
  return 'info';
}

export function DashboardPage({ onNavigate }: DashboardPageProps) {
  const [sysStatus, setSysStatus]             = useState<SystemStatus | null>(null);
  const [staticMotor, setStaticMotor]         = useState<MotorStatus | null>(null);
  const [motorError, setMotorError]           = useState(false);
  const [showHomeModal, setShowHomeModal]     = useState(false);
  const [showSysCheckModal, setShowSysCheckModal] = useState(false);
  const [loadingAction, setLoadingAction]     = useState<string | null>(null);

  const liveMotor    = useMotorWs();
  const systemEvents = useSystemWs();
  const motorStatus  = liveMotor ?? staticMotor;

  // Periodic polling — 3 s system, 2 s motor
  useEffect(() => {
    function pollSys() { systemApi.status().then(setSysStatus).catch(() => null); }
    function pollMotor() {
      motorApi.status()
        .then((s) => { setStaticMotor(s); setMotorError(false); })
        .catch(() => setMotorError(true));
    }
    pollSys();
    pollMotor();
    const sysId = setInterval(pollSys, 3000);
    const motId = setInterval(pollMotor, 2000);
    return () => { clearInterval(sysId); clearInterval(motId); };
  }, []);

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

  const isFault        = (motorStatus?.state ?? 0) === 5;
  const motorConnected = sysStatus?.motor_connected ?? false;

  return (
    <div className="p-4 max-w-[1100px] mx-auto">
      <h2 className="text-lg font-semibold text-text-primary mb-4">Dashboard</h2>

      {/* KPI Strip */}
      <div className="mb-4">
        {sysStatus ? (
          <KpiStrip
            cpuTemp={sysStatus.cpu_temp_c}
            uptimeS={sysStatus.uptime_s}
            bendCycles={0}
            lastRun={null}
          />
        ) : (
          <SkeletonLoader lines={2} />
        )}
      </div>

      {/* 2x2 Card Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

        {/* System Health */}
        <Card>
          <div className="flex justify-between items-center mb-3">
            <CardTitle>System Health</CardTitle>
            {sysStatus && (
              <span className={`text-[11px] font-medium ${sysStatus.ipc_connected && sysStatus.camera_connected ? 'text-success' : 'text-warning'}`}>
                {sysStatus.ipc_connected && sysStatus.camera_connected ? 'All nominal' : 'Issues detected'}
              </span>
            )}
          </div>
          {!sysStatus ? (
            <SkeletonLoader lines={4} />
          ) : (
            <div className="flex flex-col gap-2.5">
              <div className="flex gap-1.5 flex-wrap">
                <StatusBadge variant={sysStatus.ipc_connected    ? 'success' : 'error'} label="LINK" />
                <StatusBadge variant={sysStatus.m7_heartbeat_ok  ? 'success' : 'error'} label="Controller" />
                <StatusBadge variant={sysStatus.camera_connected ? 'success' : 'error'} label="CAM" />
              </div>
              {sysStatus.driver_probe && Object.keys(sysStatus.driver_probe).length > 0 && (
                <div>
                  <span className="text-[11px] text-text-tertiary block mb-1">Motor Drivers</span>
                  <div className="flex gap-1.5 flex-wrap">
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
              <div className="text-[11px] text-text-tertiary">SDK {sysStatus.sdk_version}</div>
            </div>
          )}
        </Card>

        {/* Motor Readiness */}
        <Card>
          <div className="flex justify-between items-center mb-3">
            <CardTitle>Motor Readiness</CardTitle>
            <span className={`text-[11px] font-medium ${motorConnected ? 'text-success' : 'text-warning'}`}>
              {motorConnected ? 'Online' : 'Offline'}
            </span>
          </div>
          {!motorStatus && !motorError ? (
            <SkeletonLoader lines={4} />
          ) : (
            <div className="flex flex-col gap-1.5">
              {motorConnected && motorStatus ? (
                motorStatus.axes.map((ax) => (
                  <AxisStatusRow
                    key={ax.axis}
                    axis={ax.axis}
                    position={ax.position}
                    velocity={ax.velocity}
                    drvStatus={ax.drv_status}
                    connected
                  />
                ))
              ) : (
                [0, 1, 2, 3].map((i) => (
                  <AxisStatusRow key={i} axis={i} connected={false} />
                ))
              )}
            </div>
          )}
        </Card>

        {/* Quick Actions */}
        <Card>
          <CardTitle className="mb-3">Quick Actions</CardTitle>
          <div className="grid grid-cols-2 gap-2">
            <Button variant="primary" onClick={() => onNavigate('bending')}>
              Start Bending
            </Button>
            <Button
              variant="secondary"
              loading={loadingAction === 'home'}
              onClick={() => setShowHomeModal(true)}
            >
              Home All
            </Button>
            <Button variant="secondary" onClick={() => onNavigate('camera')}>
              Camera
            </Button>
            <Button
              variant="secondary"
              disabled={!isFault}
              loading={loadingAction === 'reset'}
              onClick={resetFault}
              className={isFault ? 'bg-warning-soft text-warning border-warning/30' : ''}
            >
              Reset Fault
            </Button>
            <Button
              variant="secondary"
              className="col-span-2"
              onClick={() => setShowSysCheckModal(true)}
            >
              System Check
            </Button>
          </div>
        </Card>

        {/* Alarm History */}
        <Card>
          <div className="flex justify-between items-center mb-3">
            <CardTitle>Alarm History</CardTitle>
            <button className="text-[11px] text-text-tertiary hover:text-text-secondary transition-colors">
              View All
            </button>
          </div>
          {systemEvents.length === 0 ? (
            <EmptyState
              icon={<Bell size={32} />}
              message="No active alarms"
              hint="System events will appear here"
            />
          ) : (
            <div className="flex flex-col gap-1.5 max-h-[200px] overflow-y-auto">
              {systemEvents.slice(0, 10).map((ev: SystemEvent, i: number) => (
                <div key={i} className="flex items-start gap-2 p-1.5 bg-canvas rounded">
                  <StatusBadge variant={getSeverity(ev.type)} label={getSeverity(ev.type).toUpperCase()} />
                  <span className="text-[12px] text-text-secondary flex-1">{ev.message}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
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

      {showSysCheckModal && (
        <ConfirmModal
          title="System Check"
          description="Running connection check to all subsystems (Board, Controller Link, Motor Controller, Camera)..."
          confirmLabel="OK"
          confirmVariant="primary"
          onConfirm={() => {
            setShowSysCheckModal(false);
            systemApi.status().then(setSysStatus).catch(() => null);
          }}
          onCancel={() => setShowSysCheckModal(false)}
        />
      )}
    </div>
  );
}
