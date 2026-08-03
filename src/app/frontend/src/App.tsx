/**
 * App.tsx — Ortho-Bender Dashboard: shell + page routing.
 */

import { useEffect, useState } from 'react';
import { Sidebar } from './components/shell/Sidebar';
import { Header } from './components/shell/Header';
import { AlarmBanner } from './components/shell/AlarmBanner';
import { ConnectionPage }  from './pages/ConnectionPage';
import { DashboardPage }   from './pages/DashboardPage';
import { BendingPage }     from './pages/BendingPage';
import { MotorPage }       from './pages/MotorPage';
import { CameraPage }      from './pages/CameraPage';
import { SimulationPage }  from './pages/SimulationPage';
import { SettingsPage }    from './pages/SettingsPage';
import { DiagnosticsPage } from './pages/DiagnosticsPage';
import { DocumentationPage } from './pages/DocumentationPage';
import { systemApi, type SystemStatus } from './api/client';
import { wsApi } from './api/client';
import type { ConnStatus } from './components/ui/ConnectionIcon';
import type { SystemEvent } from './hooks/useSystemWs';
import { cn } from './lib/cn';

export type Page = 'connection' | 'dashboard' | 'bending' | 'motor' | 'camera' | 'simulation' | 'settings' | 'diagnostics' | 'docs';

export default function App() {
  const [currentPage, setCurrentPage] = useState<Page>('dashboard');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768);
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);
  const [systemEvents, setSystemEvents] = useState<SystemEvent[]>([]);
  const [motionStateNum, setMotionStateNum] = useState(0);

  useEffect(() => {
    function onResize() {
      const mobile = window.innerWidth < 768;
      setIsMobile(mobile);
      if (!mobile) setSidebarOpen(false);
    }
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // Derived connection statuses — based on real hardware detection
  const boardStatus: ConnStatus = sysStatus ? 'connected' : 'disconnected';
  const ipcStatus: ConnStatus = sysStatus?.ipc_connected ? 'connected' : 'disconnected';
  const motorConnStatus: ConnStatus = sysStatus?.motor_connected ? 'connected' : 'disconnected';
  const driverProbe = sysStatus?.driver_probe ?? {};
  const driverTotal = Object.keys(driverProbe).length;
  const driverConnected = Object.values(driverProbe).filter((d) => d.connected).length;
  const motorDetail = driverTotal > 0 ? `${driverConnected}/${driverTotal}` : 'NO';
  const camStatus: ConnStatus = sysStatus?.camera_connected ? 'connected' : 'disconnected';

  const sidebarWidth = sidebarCollapsed ? 56 : 240;

  // Periodic system status polling (every 3s)
  useEffect(() => {
    function poll() {
      systemApi.status().then((s) => {
        setSysStatus(s);
        setMotionStateNum(s.motion_state);
      }).catch(() => null);
    }
    poll();
    const id = setInterval(poll, 3000);
    return () => clearInterval(id);
  }, []);

  // System WebSocket for heartbeat + events
  useEffect(() => {
    const ws = wsApi.system((msg) => {
      if (msg.type === 'heartbeat') {
        systemApi.status().then((s) => {
          setSysStatus(s);
          setMotionStateNum(s.motion_state);
        }).catch(() => null);
      } else {
        setSystemEvents((prev) => [msg, ...prev.slice(0, 49)]);
      }
    });
    return () => ws.close();
  }, []);

  function handleNavigate(page: Page) {
    setCurrentPage(page);
    if (isMobile) setSidebarOpen(false);
  }

  function handleEstopAction() {
    systemApi.status().then((s) => {
      setSysStatus(s);
      setMotionStateNum(s.motion_state);
    }).catch(() => null);
  }

  function renderPage() {
    switch (currentPage) {
      case 'connection':  return <ConnectionPage />;
      case 'dashboard':   return <DashboardPage onNavigate={handleNavigate} />;
      case 'bending':     return <BendingPage />;
      case 'motor':       return <MotorPage />;
      case 'camera':      return <CameraPage />;
      case 'simulation':  return <SimulationPage />;
      case 'settings':    return <SettingsPage />;
      case 'diagnostics': return <DiagnosticsPage />;
      case 'docs':        return <DocumentationPage />;
    }
  }

  return (
    <div className="bg-canvas min-h-screen text-text-primary">
      <Header
        onToggleSidebar={() => isMobile ? setSidebarOpen((o) => !o) : setSidebarCollapsed((c) => !c)}
        motionStateNum={motionStateNum}
        bdStatus={boardStatus}
        ipcStatus={ipcStatus}
        motorStatus={motorConnStatus}
        motorModel={sysStatus?.motor_model ?? null}
        motorDetail={motorDetail}
        camStatus={camStatus}
        camModel={sysStatus?.camera_model ?? null}
        alarmCount={sysStatus?.active_alarms ?? 0}
        onEstopAction={handleEstopAction}
      />

      {/* Mobile overlay backdrop */}
      {isMobile && sidebarOpen && (
        <div
          onClick={() => setSidebarOpen(false)}
          className="fixed inset-0 bg-black/50 z-[99] top-14"
        />
      )}

      {(!isMobile || sidebarOpen) && (
        <Sidebar
          currentPage={currentPage}
          onNavigate={handleNavigate}
          collapsed={isMobile ? false : sidebarCollapsed}
          onToggleCollapse={() => isMobile ? setSidebarOpen(false) : setSidebarCollapsed((c) => !c)}
        />
      )}

      <div
        className={cn('mt-14 min-h-[calc(100vh-56px)] flex flex-col transition-[margin-left] duration-default')}
        style={{ marginLeft: isMobile ? 0 : sidebarWidth }}
      >
        <AlarmBanner activeAlarms={sysStatus?.active_alarms ?? 0} events={systemEvents} />
        <div className="flex-1 overflow-y-auto">
          {renderPage()}
        </div>
      </div>
    </div>
  );
}
