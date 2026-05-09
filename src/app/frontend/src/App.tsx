/**
 * App.tsx — Ortho-Bender Dashboard: sidebar + header + page routing.
 *
 * Layout:
 *   Fixed header (56px) + fixed sidebar (240px/56px) + scrollable content
 *
 * Routing: useState-based, no react-router-dom.
 */

import { useEffect, useState } from 'react';
import { Sidebar } from './components/layout/Sidebar';
import { Header } from './components/layout/Header';
import { AlarmBanner } from './components/layout/AlarmBanner';
import { ConnectionPage }  from './pages/ConnectionPage';
import { DashboardPage }   from './pages/DashboardPage';
import { BendingPage }     from './pages/BendingPage';
import { MotorPage }       from './pages/MotorPage';
import { CameraPage }      from './pages/CameraPage';
import { SimulationPage }  from './pages/SimulationPage';
import { SettingsPage }    from './pages/SettingsPage';
import { DiagnosticsPage } from './pages/DiagnosticsPage';
import { DocumentationPage } from './pages/DocumentationPage';
import { systemApi, motorApi, type SystemStatus } from './api/client';
import { wsApi } from './api/client';
import type { ConnStatus } from './components/ui/ConnectionIcon';
import type { SystemEvent } from './hooks/useSystemWs';
import { useBoardRebootDetector } from './hooks/useBoardRebootDetector';
import { ToastProvider } from './components/ui/ToastSystem';
import { BG_PRIMARY, BG_PANEL, BORDER, TEXT_PRIMARY, TEXT_MUTED } from './constants';

export type Page = 'connection' | 'dashboard' | 'bending' | 'motor' | 'camera' | 'simulation' | 'settings' | 'diagnostics' | 'docs';

export default function App() {
  const [currentPage, setCurrentPage] = useState<Page>('dashboard');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768);
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);
  const { rebootDetected, dismiss: dismissReboot } = useBoardRebootDetector();
  const [homing, setHoming] = useState(false);

  async function runHomingFromPrompt() {
    try { setHoming(true); await motorApi.home(0); dismissReboot(); }
    catch (e) { alert(`Homing failed: ${e}`); }
    finally { setHoming(false); }
  }

  // Responsive detection
  useEffect(() => {
    function onResize() {
      const mobile = window.innerWidth < 768;
      setIsMobile(mobile);
      if (!mobile) setSidebarOpen(false);
    }
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  const [systemEvents, setSystemEvents] = useState<SystemEvent[]>([]);
  const [motionStateNum, setMotionStateNum] = useState(0);

  // Derived connection statuses — based on real hardware detection
  const boardStatus: ConnStatus = sysStatus ? 'connected' : 'disconnected';
  const ipcStatus: ConnStatus = sysStatus?.ipc_connected ? 'connected' : 'disconnected';
  const motorConnStatus: ConnStatus = sysStatus?.motor_connected ? 'connected' : 'disconnected';
  const driverProbe = sysStatus?.driver_probe ?? {};
  const driverTotal = Object.keys(driverProbe).length;
  const driverConnected = Object.values(driverProbe).filter((d) => d.connected).length;
  const motorDetail = driverTotal > 0
    ? `${driverConnected}/${driverTotal}`
    : 'NO';
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
    <ToastProvider>
      {/* Global styles */}
      <style>{`
        * { box-sizing: border-box; }
        body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #475569; }
        @media (max-width: 768px) {
          .sidebar-overlay {
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            right: 0 !important;
            bottom: 0 !important;
            background: rgba(0,0,0,0.5) !important;
            z-index: 99 !important;
          }
        }
      `}</style>

      <div style={{ background: BG_PRIMARY, minHeight: '100vh', color: '#f1f5f9' }}>
        {rebootDetected && (
          <div
            role="dialog"
            aria-modal="true"
            style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
          >
            <div style={{ background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 24, maxWidth: 460, color: TEXT_PRIMARY }}>
              <h3 style={{ margin: '0 0 10px', color: '#fcd34d', fontSize: 16 }}>⚠ Board restart detected</h3>
              <p style={{ margin: '0 0 8px', fontSize: 13, lineHeight: 1.5 }}>
                The controller has rebooted since this dashboard last polled it.
                Stored motor positions have been cleared because they may no
                longer match the physical machine.
              </p>
              <p style={{ margin: '0 0 18px', fontSize: 12, color: TEXT_MUTED }}>
                Run homing before any motion command, or acknowledge if you
                will home from the bench shortly.
              </p>
              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                <button
                  onClick={dismissReboot}
                  style={{ background: 'transparent', border: `1px solid ${BORDER}`, color: TEXT_MUTED, borderRadius: 4, padding: '8px 16px', cursor: 'pointer', fontSize: 13 }}
                >Acknowledge</button>
                <button
                  onClick={runHomingFromPrompt}
                  disabled={homing}
                  style={{ background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 4, padding: '8px 16px', cursor: 'pointer', fontSize: 13, fontWeight: 600, opacity: homing ? 0.6 : 1 }}
                >{homing ? 'Homing…' : 'Run Homing'}</button>
              </div>
            </div>
          </div>
        )}
        {/* Fixed header */}
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
          onEstopAction={handleEstopAction}
        />

        {/* Mobile overlay backdrop */}
        {isMobile && sidebarOpen && (
          <div
            onClick={() => setSidebarOpen(false)}
            style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 99, top: 56 }}
          />
        )}

        {/* Sidebar: fixed on desktop, overlay drawer on mobile */}
        {(!isMobile || sidebarOpen) && (
          <Sidebar
            currentPage={currentPage}
            onNavigate={handleNavigate}
            collapsed={isMobile ? false : sidebarCollapsed}
            onToggleCollapse={() => isMobile ? setSidebarOpen(false) : setSidebarCollapsed((c) => !c)}
          />
        )}

        {/* Main content area */}
        <div style={{
          marginLeft: isMobile ? 0 : sidebarWidth,
          marginTop: 56,
          minHeight: 'calc(100vh - 56px)',
          transition: 'margin-left 0.2s ease',
          display: 'flex',
          flexDirection: 'column',
        }}>
          {/* Alarm banner (conditional) */}
          <AlarmBanner activeAlarms={sysStatus?.active_alarms ?? 0} events={systemEvents} />

          {/* Page content */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {renderPage()}
          </div>
        </div>
      </div>
    </ToastProvider>
  );
}
