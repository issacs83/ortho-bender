/**
 * ConnectionPage.tsx — Board connection, system info, IPC status, firmware update, WiFi, Bluetooth.
 */

import { useEffect, useRef, useState } from 'react';
import { systemApi, type SystemStatus } from '../api/client';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ConfirmModal } from '../components/ui/ConfirmModal';
import { SkeletonLoader } from '../components/ui/SkeletonLoader';
import {
  BG_PANEL, BG_PRIMARY, BORDER,
  TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
  COLOR_SUCCESS, COLOR_WARNING, COLOR_ERROR,
} from '../constants';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ConnType = 'ethernet' | 'usb' | 'wifi';
type MainTab = 'board' | 'wifi' | 'bluetooth';

interface WifiNetwork {
  bssid: string;
  frequency: number;
  signal: number;
  flags: string;
  security: string;
  band: string;
  ssid: string;
}

interface WifiStatus {
  connected: boolean;
  ssid?: string;
  ip_address?: string;
  bssid?: string;
  wpa_state?: string;
  freq?: number;
}

// ---------------------------------------------------------------------------
// WiFi API helpers (inline, not via client.ts)
// ---------------------------------------------------------------------------

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  const json = await res.json();
  if (!json.success) throw new Error(json.error ?? 'API error');
  return json.data as T;
}

async function wifiScan(): Promise<WifiNetwork[]> {
  return apiFetch<WifiNetwork[]>('/api/wifi/scan');
}

async function wifiStatus(): Promise<WifiStatus> {
  return apiFetch<WifiStatus>('/api/wifi/status');
}

async function wifiConnect(ssid: string, password: string | null): Promise<{ connected: boolean }> {
  return apiFetch<{ connected: boolean }>('/api/wifi/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ssid, password }),
  });
}

async function wifiDisconnect(): Promise<void> {
  await fetch('/api/wifi/disconnect', { method: 'POST' });
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

function formatUptime(s: number): string {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${d}d ${h}h ${m}m`;
}

function signalBars(signal: number): number {
  if (signal >= -50) return 4;
  if (signal >= -65) return 3;
  if (signal >= -75) return 2;
  return 1;
}

function SignalIcon({ bars }: { bars: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 16 }}>
      {[1, 2, 3, 4].map((b) => (
        <div
          key={b}
          style={{
            width: 4,
            height: b * 4,
            borderRadius: 1,
            background: b <= bars ? COLOR_SUCCESS : BORDER,
          }}
        />
      ))}
    </div>
  );
}

function ProgressBar({ value, max, dangerThreshold }: { value: number; max: number; dangerThreshold?: number }) {
  const pct = Math.min(100, (value / max) * 100);
  const isDanger = dangerThreshold !== undefined && value >= dangerThreshold;
  return (
    <div style={{ height: 6, background: '#0f172a', borderRadius: 3, overflow: 'hidden', flex: 1 }}>
      <div style={{
        height: '100%',
        width: `${pct}%`,
        background: isDanger ? '#ef4444' : '#3b82f6',
        borderRadius: 3,
        transition: 'width 0.3s',
      }} />
    </div>
  );
}

function Spinner() {
  return (
    <span style={{
      display: 'inline-block',
      width: 14,
      height: 14,
      border: '2px solid #334155',
      borderTopColor: '#3b82f6',
      borderRadius: '50%',
      animation: 'spin 0.7s linear infinite',
    }} />
  );
}

// ---------------------------------------------------------------------------
// Password modal
// ---------------------------------------------------------------------------

function PasswordModal({
  ssid,
  onCancel,
  onConnect,
  connecting,
}: {
  ssid: string;
  onCancel: () => void;
  onConnect: (password: string | null) => void;
  connecting: boolean;
}) {
  const [pw, setPw] = useState('');
  const [show, setShow] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div style={{
        background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 10,
        padding: 28, width: 360, boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
      }}>
        <h3 style={{ margin: '0 0 6px', fontSize: 15, color: TEXT_PRIMARY }}>
          Connect to network
        </h3>
        <div style={{ fontSize: 13, color: TEXT_MUTED, marginBottom: 20 }}>
          "{ssid}"
        </div>

        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, color: TEXT_MUTED, marginBottom: 6 }}>Password</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              ref={inputRef}
              type={show ? 'text' : 'password'}
              value={pw}
              onChange={(e) => setPw(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !connecting && onConnect(pw || null)}
              placeholder="Enter password"
              style={{
                flex: 1,
                background: BG_PRIMARY,
                border: `1px solid ${BORDER}`,
                borderRadius: 4,
                color: TEXT_PRIMARY,
                padding: '7px 10px',
                fontSize: 13,
              }}
            />
            <button
              onClick={() => setShow(!show)}
              style={{
                background: BG_PRIMARY,
                border: `1px solid ${BORDER}`,
                borderRadius: 4,
                color: TEXT_SECONDARY,
                padding: '0 10px',
                cursor: 'pointer',
                fontSize: 12,
              }}
            >
              {show ? 'Hide' : 'Show'}
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button
            onClick={onCancel}
            disabled={connecting}
            style={{
              padding: '8px 16px', border: `1px solid ${BORDER}`, borderRadius: 6,
              background: 'transparent', color: TEXT_SECONDARY, cursor: 'pointer', fontSize: 13,
            }}
          >
            Cancel
          </button>
          <button
            onClick={() => onConnect(pw || null)}
            disabled={connecting}
            style={{
              padding: '8px 16px', border: 'none', borderRadius: 6,
              background: connecting ? '#1e3a5f' : '#1d4ed8',
              color: '#fff', cursor: connecting ? 'default' : 'pointer',
              fontSize: 13, fontWeight: 600,
              display: 'flex', alignItems: 'center', gap: 8,
            }}
          >
            {connecting && <Spinner />}
            {connecting ? 'Connecting...' : 'Connect'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// WiFi tab
// ---------------------------------------------------------------------------

function WifiTab() {
  const [status, setStatus] = useState<WifiStatus | null>(null);
  const [networks, setNetworks] = useState<WifiNetwork[]>([]);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);

  const [selectedSsid, setSelectedSsid] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);

  // Fetch status on mount
  useEffect(() => {
    wifiStatus()
      .then(setStatus)
      .catch(() => setStatus({ connected: false }));
  }, []);

  async function handleScan() {
    setScanning(true);
    setScanError(null);
    try {
      const nets = await wifiScan();
      setNetworks(nets);
      // Refresh status after scan
      const st = await wifiStatus();
      setStatus(st);
    } catch (e) {
      setScanError(String(e));
    } finally {
      setScanning(false);
    }
  }

  async function handleConnect(password: string | null) {
    if (!selectedSsid) return;
    setConnecting(true);
    setConnectError(null);
    try {
      const result = await wifiConnect(selectedSsid, password);
      if (result.connected) {
        const st = await wifiStatus();
        setStatus(st);
      } else {
        setConnectError('Connection failed. Check the password and try again.');
      }
    } catch (e) {
      setConnectError(String(e));
    } finally {
      setConnecting(false);
      setSelectedSsid(null);
    }
  }

  async function handleDisconnect() {
    setDisconnecting(true);
    try {
      await wifiDisconnect();
      setStatus({ connected: false });
    } finally {
      setDisconnecting(false);
    }
  }

  const cardStyle = {
    background: BG_PANEL,
    border: `1px solid ${BORDER}`,
    borderRadius: 8,
    padding: 20,
  };

  const btnBase = {
    padding: '7px 14px',
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
    fontSize: 13,
    fontWeight: 600 as const,
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Status card */}
      <div style={cardStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: 14, color: TEXT_PRIMARY }}>WiFi Status</h3>
          <button
            onClick={handleScan}
            disabled={scanning}
            style={{
              ...btnBase,
              background: scanning ? '#1e293b' : '#1d4ed8',
              color: scanning ? TEXT_MUTED : '#fff',
              border: `1px solid ${scanning ? BORDER : 'transparent'}`,
            }}
          >
            {scanning && <Spinner />}
            {scanning ? 'Scanning...' : 'Scan'}
          </button>
        </div>

        {/* Connection state */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
          <span style={{ fontSize: 13, color: TEXT_MUTED }}>Status:</span>
          {status === null ? (
            <SkeletonLoader lines={1} />
          ) : (
            <StatusBadge
              variant={status.connected ? 'success' : 'error'}
              label={status.connected ? 'Connected' : 'Disconnected'}
            />
          )}
        </div>

        {status?.connected && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 10 }}>
            {status.ssid && (
              <div style={{ display: 'flex', gap: 8 }}>
                <span style={{ fontSize: 13, color: TEXT_MUTED, width: 80 }}>SSID</span>
                <span style={{ fontSize: 13, color: TEXT_PRIMARY, fontWeight: 600 }}>{status.ssid}</span>
              </div>
            )}
            {status.ip_address && (
              <div style={{ display: 'flex', gap: 8 }}>
                <span style={{ fontSize: 13, color: TEXT_MUTED, width: 80 }}>IP Address</span>
                <span style={{ fontSize: 13, color: TEXT_PRIMARY }}>{status.ip_address}</span>
              </div>
            )}
            {status.freq && (
              <div style={{ display: 'flex', gap: 8 }}>
                <span style={{ fontSize: 13, color: TEXT_MUTED, width: 80 }}>Band</span>
                <span style={{ fontSize: 13, color: TEXT_PRIMARY }}>{status.freq >= 5000 ? '5 GHz' : '2.4 GHz'}</span>
              </div>
            )}
          </div>
        )}

        {status?.connected && (
          <button
            onClick={handleDisconnect}
            disabled={disconnecting}
            style={{
              ...btnBase,
              background: '#7f1d1d',
              color: '#fca5a5',
              border: `1px solid #991b1b`,
            }}
          >
            {disconnecting && <Spinner />}
            {disconnecting ? 'Disconnecting...' : 'Disconnect'}
          </button>
        )}

        {connectError && (
          <div style={{ marginTop: 10, fontSize: 12, color: COLOR_ERROR }}>{connectError}</div>
        )}
        {scanError && (
          <div style={{ marginTop: 10, fontSize: 12, color: COLOR_ERROR }}>{scanError}</div>
        )}
      </div>

      {/* Networks list */}
      {networks.length > 0 && (
        <div style={cardStyle}>
          <h3 style={{ margin: '0 0 14px', fontSize: 14, color: TEXT_PRIMARY }}>
            Available Networks ({networks.length})
          </h3>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  {['Signal', 'SSID', 'Security', 'Band', ''].map((h) => (
                    <th key={h} style={{
                      textAlign: 'left',
                      fontSize: 11,
                      color: TEXT_MUTED,
                      paddingBottom: 8,
                      borderBottom: `1px solid ${BORDER}`,
                      paddingRight: 16,
                      fontWeight: 500,
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {networks.map((net) => {
                  const bars = signalBars(net.signal);
                  const isConnected = status?.connected && status.ssid === net.ssid;
                  return (
                    <tr key={net.bssid} style={{ borderBottom: `1px solid ${BORDER}` }}>
                      <td style={{ padding: '10px 16px 10px 0', verticalAlign: 'middle' }}>
                        <SignalIcon bars={bars} />
                      </td>
                      <td style={{ padding: '10px 16px 10px 0', verticalAlign: 'middle' }}>
                        <span style={{ fontSize: 13, color: isConnected ? COLOR_SUCCESS : TEXT_PRIMARY }}>
                          {net.ssid}
                          {isConnected && (
                            <span style={{ marginLeft: 8, fontSize: 11, color: COLOR_SUCCESS }}>
                              (connected)
                            </span>
                          )}
                        </span>
                      </td>
                      <td style={{ padding: '10px 16px 10px 0', verticalAlign: 'middle' }}>
                        <span style={{
                          fontSize: 11,
                          padding: '2px 8px',
                          borderRadius: 4,
                          background: net.security === 'OPEN' ? '#065f4620' : '#1e3a5f',
                          color: net.security === 'OPEN' ? COLOR_SUCCESS : '#93c5fd',
                          border: `1px solid ${net.security === 'OPEN' ? '#065f46' : '#1e40af'}`,
                        }}>
                          {net.security}
                        </span>
                      </td>
                      <td style={{ padding: '10px 16px 10px 0', verticalAlign: 'middle' }}>
                        <span style={{ fontSize: 12, color: TEXT_MUTED }}>{net.band}</span>
                      </td>
                      <td style={{ padding: '10px 0', verticalAlign: 'middle', textAlign: 'right' }}>
                        {!isConnected && (
                          <button
                            onClick={() => {
                              setConnectError(null);
                              setSelectedSsid(net.ssid);
                            }}
                            style={{
                              padding: '5px 12px',
                              border: `1px solid #1d4ed8`,
                              borderRadius: 5,
                              background: 'transparent',
                              color: '#60a5fa',
                              cursor: 'pointer',
                              fontSize: 12,
                              fontWeight: 600,
                            }}
                          >
                            Connect
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Password modal */}
      {selectedSsid !== null && (
        <PasswordModal
          ssid={selectedSsid}
          onCancel={() => setSelectedSsid(null)}
          onConnect={handleConnect}
          connecting={connecting}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Bluetooth placeholder tab
// ---------------------------------------------------------------------------

function BluetoothTab() {
  return (
    <div style={{
      background: BG_PANEL,
      border: `1px solid ${BORDER}`,
      borderRadius: 8,
      padding: 48,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 14,
      minHeight: 200,
    }}>
      {/* BT icon */}
      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke={TEXT_MUTED} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="6.5 6.5 17.5 17.5 12 23 12 1 17.5 6.5 6.5 17.5" />
      </svg>
      <div style={{ fontSize: 15, color: TEXT_SECONDARY, fontWeight: 600 }}>
        Bluetooth Not Available
      </div>
      <div style={{ fontSize: 12, color: TEXT_MUTED, textAlign: 'center', maxWidth: 340, lineHeight: 1.7 }}>
        Marvell 88W8997 Bluetooth requires a kernel rebuild.
        <br />
        <code style={{ fontSize: 11, color: '#93c5fd' }}>CONFIG_BT_HCIUART_MRVL=m</code> must be enabled.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Board + System sub-content (original two-column layout)
// ---------------------------------------------------------------------------

function BoardSystemTab() {
  const [connType, setConnType] = useState<ConnType>('ethernet');
  const [boardIp, setBoardIp] = useState('192.168.77.2');
  const [port, setPort] = useState('8000');
  const [autoReconnect, setAutoReconnect] = useState(true);
  const [connStatus, setConnStatus] = useState<'connected' | 'connecting' | 'disconnected'>('disconnected');
  const [lastConnected, setLastConnected] = useState<string | null>(null);
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [ipcEvents, setIpcEvents] = useState<string[]>([]);
  const [showResetIpcModal, setShowResetIpcModal] = useState(false);

  const [fwFile, setFwFile] = useState<File | null>(null);
  const [fwProgress, setFwProgress] = useState(0);
  const [flashing, setFlashing] = useState(false);

  async function handleConnect() {
    setLoading(true);
    setConnStatus('connecting');
    setError(null);
    try {
      const status = await systemApi.status();
      setSysStatus(status);
      setConnStatus('connected');
      setLastConnected(new Date().toLocaleString());
    } catch (e) {
      setConnStatus('disconnected');
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleDisconnect() {
    setConnStatus('disconnected');
    setSysStatus(null);
  }

  useEffect(() => {
    handleConnect();
    const id = setInterval(() => {
      if (connStatus === 'connected') {
        systemApi.status().then((s) => { setSysStatus(s); }).catch(() => null);
      }
    }, 3000);
    return () => clearInterval(id);
  }, []);

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file?.name.endsWith('.bin')) setFwFile(file);
  }

  function handleFlash() {
    if (!fwFile) return;
    setFlashing(true);
    setFwProgress(0);
    const interval = setInterval(() => {
      setFwProgress((p) => {
        if (p >= 100) { clearInterval(interval); setFlashing(false); return 100; }
        return p + 5;
      });
    }, 200);
  }

  const cardStyle = {
    background: BG_PANEL,
    border: `1px solid ${BORDER}`,
    borderRadius: 8,
    padding: 20,
  };

  const labelStyle = { fontSize: 12, color: TEXT_MUTED, marginBottom: 2 };
  const inputStyle = {
    background: BG_PRIMARY,
    border: `1px solid ${BORDER}`,
    borderRadius: 4,
    color: TEXT_PRIMARY,
    padding: '6px 10px',
    fontSize: 13,
    width: '100%',
    boxSizing: 'border-box' as const,
  };
  const btnBase = {
    padding: '8px 14px',
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
    fontSize: 13,
    fontWeight: 600,
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>

      {/* Board Connection */}
      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 16px', fontSize: 14, color: TEXT_PRIMARY }}>Board Connection</h3>

        <div style={{ marginBottom: 14 }}>
          <div style={{ ...labelStyle }}>Connection Type</div>
          <div style={{ display: 'flex', gap: 16, marginTop: 6 }}>
            {(['ethernet', 'usb', 'wifi'] as ConnType[]).map((t) => (
              <label key={t} style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13, color: TEXT_SECONDARY }}>
                <input type="radio" value={t} checked={connType === t} onChange={() => setConnType(t)} style={{ accentColor: '#3b82f6' }} />
                {t === 'ethernet' ? 'Direct Ethernet' : t === 'usb' ? 'USB CDC' : 'WiFi'}
              </label>
            ))}
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 10, marginBottom: 12 }}>
          <div>
            <div style={labelStyle}>Board IP</div>
            <input style={inputStyle} value={boardIp} onChange={(e) => setBoardIp(e.target.value)} />
          </div>
          <div>
            <div style={labelStyle}>Port</div>
            <input style={{ ...inputStyle, width: 70 }} value={port} onChange={(e) => setPort(e.target.value)} />
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, color: TEXT_SECONDARY }}>
            <input type="checkbox" checked={autoReconnect} onChange={(e) => setAutoReconnect(e.target.checked)} style={{ accentColor: '#3b82f6' }} />
            Auto-reconnect
          </label>
        </div>

        {lastConnected && (
          <div style={{ fontSize: 11, color: TEXT_MUTED, marginBottom: 12 }}>Last connected: {lastConnected}</div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <span style={{ fontSize: 13, color: TEXT_SECONDARY }}>Status:</span>
          <StatusBadge
            variant={connStatus === 'connected' ? 'success' : connStatus === 'connecting' ? 'warning' : 'error'}
            label={connStatus === 'connected' ? 'Connected' : connStatus === 'connecting' ? 'Connecting...' : 'Disconnected'}
          />
        </div>

        {error && <div style={{ fontSize: 12, color: '#ef4444', marginBottom: 12 }}>{error}</div>}

        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={handleConnect} disabled={loading} style={{ ...btnBase, background: '#1d4ed8', color: '#fff', opacity: loading ? 0.6 : 1 }}>
            {loading ? 'Connecting...' : 'Connect'}
          </button>
          <button onClick={handleDisconnect} style={{ ...btnBase, background: '#1e293b', color: TEXT_SECONDARY, border: `1px solid ${BORDER}` }}>
            Disconnect
          </button>
          <button onClick={handleConnect} style={{ ...btnBase, background: '#1e293b', color: TEXT_SECONDARY, border: `1px solid ${BORDER}` }}>
            Reconnect
          </button>
        </div>
      </div>

      {/* System Info */}
      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 16px', fontSize: 14, color: TEXT_PRIMARY }}>System Info</h3>
        {!sysStatus ? (
          <SkeletonLoader lines={6} />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {[
              ['SDK Version', sysStatus.sdk_version],
              ['FW Version', 'v1.0.0'],
              ['OS Version', 'Yocto Linux 6.1'],
            ].map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 13, color: TEXT_MUTED }}>{k}</span>
                <span style={{ fontSize: 13, color: TEXT_PRIMARY }}>{v}</span>
              </div>
            ))}

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 13, color: TEXT_MUTED }}>CPU Temp</span>
                <span style={{ fontSize: 13, color: (sysStatus.cpu_temp_c ?? 0) >= 80 ? '#ef4444' : TEXT_PRIMARY }}>
                  {sysStatus.cpu_temp_c?.toFixed(1) ?? 'N/A'} °C
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <ProgressBar value={sysStatus.cpu_temp_c ?? 0} max={100} dangerThreshold={80} />
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 13, color: TEXT_MUTED }}>Uptime</span>
                <span style={{ fontSize: 13, color: TEXT_PRIMARY }}>{formatUptime(sysStatus.uptime_s)}</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Controller Link Status */}
      <div style={cardStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 14, color: TEXT_PRIMARY }}>Controller Link</h3>
          <button
            onClick={() => setShowResetIpcModal(true)}
            style={{ ...btnBase, padding: '4px 10px', background: '#1e293b', color: TEXT_SECONDARY, border: `1px solid ${BORDER}`, fontSize: 12 }}
          >
            Reset Link
          </button>
        </div>

        <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
          <StatusBadge variant={sysStatus?.ipc_connected ? 'success' : 'error'} label={`Controller Link: ${sysStatus?.ipc_connected ? 'OK' : 'FAIL'}`} />
        </div>

        {[
          ['Tx Count',    '—'],
          ['Rx Count',    '—'],
          ['Error Rate',  '0.00 %'],
          ['Avg Latency', '—'],
        ].map(([k, v]) => (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 13, color: TEXT_MUTED }}>{k}</span>
            <span style={{ fontSize: 13, color: TEXT_PRIMARY }}>{v}</span>
          </div>
        ))}

        <div style={{ marginTop: 12, fontSize: 12, color: TEXT_MUTED }}>Recent Events</div>
        <div style={{ marginTop: 6, maxHeight: 100, overflowY: 'auto', background: BG_PRIMARY, borderRadius: 4, padding: 8 }}>
          {ipcEvents.length === 0 ? (
            <div style={{ fontSize: 11, color: TEXT_MUTED }}>No events</div>
          ) : ipcEvents.map((ev, i) => (
            <div key={i} style={{ fontSize: 11, color: TEXT_MUTED, borderBottom: `1px solid ${BORDER}`, paddingBottom: 3, marginBottom: 3 }}>{ev}</div>
          ))}
        </div>

        {showResetIpcModal && (
          <ConfirmModal
            title="Reset Controller Link"
            description="This will reset the controller link channel. All in-flight commands will be discarded."
            confirmLabel="Reset"
            confirmVariant="danger"
            onConfirm={() => { setShowResetIpcModal(false); setIpcEvents([]); }}
            onCancel={() => setShowResetIpcModal(false)}
          />
        )}
      </div>

      {/* Firmware Update */}
      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 16px', fontSize: 14, color: TEXT_PRIMARY }}>Firmware Update</h3>

        <div style={{ marginBottom: 14 }}>
          <span style={{ fontSize: 13, color: TEXT_MUTED }}>Current FW: </span>
          <span style={{ fontSize: 13, color: TEXT_PRIMARY }}>v1.0.0</span>
        </div>

        <div
          onDrop={handleDrop}
          onDragOver={(e) => e.preventDefault()}
          style={{
            border: `2px dashed ${fwFile ? '#3b82f6' : BORDER}`,
            borderRadius: 8,
            padding: 24,
            textAlign: 'center',
            cursor: 'pointer',
            marginBottom: 14,
            background: fwFile ? '#1e3a5f20' : 'transparent',
          }}
          onClick={() => {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.bin';
            input.onchange = (e) => {
              const f = (e.target as HTMLInputElement).files?.[0];
              if (f) setFwFile(f);
            };
            input.click();
          }}
        >
          {fwFile ? (
            <div>
              <div style={{ fontSize: 13, color: '#3b82f6', fontWeight: 600 }}>{fwFile.name}</div>
              <div style={{ fontSize: 11, color: TEXT_MUTED, marginTop: 4 }}>
                {(fwFile.size / 1024).toFixed(1)} KB
              </div>
            </div>
          ) : (
            <div>
              <div style={{ fontSize: 13, color: TEXT_MUTED }}>Drop .bin file here or click to browse</div>
            </div>
          )}
        </div>

        {fwProgress > 0 && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ fontSize: 12, color: TEXT_MUTED }}>Flashing...</span>
              <span style={{ fontSize: 12, color: TEXT_PRIMARY }}>{fwProgress}%</span>
            </div>
            <ProgressBar value={fwProgress} max={100} />
          </div>
        )}

        <button
          onClick={handleFlash}
          disabled={!fwFile || flashing}
          style={{
            ...btnBase,
            background: fwFile && !flashing ? '#1d4ed8' : '#1e293b',
            color: fwFile && !flashing ? '#fff' : TEXT_MUTED,
            border: `1px solid ${BORDER}`,
            opacity: !fwFile ? 0.5 : 1,
            width: '100%',
          }}
        >
          {flashing ? 'Flashing...' : 'Flash Firmware'}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const TAB_LABELS: { id: MainTab; label: string }[] = [
  { id: 'board',     label: 'Board & System' },
  { id: 'wifi',      label: 'WiFi' },
  { id: 'bluetooth', label: 'Bluetooth' },
];

export function ConnectionPage() {
  const [activeTab, setActiveTab] = useState<MainTab>('board');

  return (
    <div style={{ padding: 'clamp(12px, 3vw, 20px)', maxWidth: 1100, margin: '0 auto' }}>
      {/* CSS for spinner animation */}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      <h2 style={{ margin: '0 0 20px', color: TEXT_PRIMARY, fontSize: 18 }}>Connection</h2>

      {/* Tab bar */}
      <div style={{
        display: 'flex',
        gap: 2,
        marginBottom: 20,
        borderBottom: `1px solid ${BORDER}`,
      }}>
        {TAB_LABELS.map(({ id, label }) => {
          const isActive = activeTab === id;
          return (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              style={{
                padding: '9px 18px',
                border: 'none',
                background: 'transparent',
                color: isActive ? TEXT_PRIMARY : TEXT_MUTED,
                fontSize: 13,
                fontWeight: isActive ? 600 : 400,
                cursor: 'pointer',
                borderBottom: isActive ? `2px solid #3b82f6` : '2px solid transparent',
                marginBottom: -1,
                transition: 'color 0.15s',
              }}
            >
              {label}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      {activeTab === 'board'     && <BoardSystemTab />}
      {activeTab === 'wifi'      && <WifiTab />}
      {activeTab === 'bluetooth' && <BluetoothTab />}
    </div>
  );
}
