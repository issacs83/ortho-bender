/**
 * ConnectionPage.tsx — Board connection, system info, IPC status, firmware update, WiFi, Bluetooth.
 */

import { useEffect, useRef, useState } from 'react';
import { systemApi, type SystemStatus } from '../api/client';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ConfirmModal } from '../components/ui/ConfirmModal';
import { SkeletonLoader } from '../components/ui/SkeletonLoader';
import { Button } from '../components/ui/Button';
import { Card, CardTitle } from '../components/ui/Card';
import { EmptyState } from '../components/ui/EmptyState';
import { cn } from '../lib/cn';

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
    <div className="flex items-end gap-0.5 h-4">
      {[1, 2, 3, 4].map((b) => (
        <div
          key={b}
          className={cn('w-1 rounded-[1px] transition-colors', b <= bars ? 'bg-success' : 'bg-border')}
          style={{ height: b * 4 }}
        />
      ))}
    </div>
  );
}

function ProgressBar({ value, max, dangerThreshold }: { value: number; max: number; dangerThreshold?: number }) {
  const pct = Math.min(100, (value / max) * 100);
  const isDanger = dangerThreshold !== undefined && value >= dangerThreshold;
  return (
    <div className="h-1.5 bg-canvas rounded-full overflow-hidden flex-1">
      <div
        className={cn('h-full rounded-full transition-[width]', isDanger ? 'bg-danger' : 'bg-accent')}
        style={{ width: `${pct}%` }}
      />
    </div>
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
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[1000]">
      <div className="bg-surface-1 border border-border rounded-lg p-7 w-[360px] shadow-2xl">
        <h3 className="text-[15px] font-semibold text-text-primary mb-1.5">Connect to network</h3>
        <div className="text-[13px] text-text-tertiary mb-5">"{ssid}"</div>

        <div className="mb-4">
          <div className="text-[12px] text-text-tertiary mb-1.5">Password</div>
          <div className="flex gap-2">
            <input
              ref={inputRef}
              type={show ? 'text' : 'password'}
              value={pw}
              onChange={(e) => setPw(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !connecting && onConnect(pw || null)}
              placeholder="Enter password"
              className="flex-1 bg-surface-2 border border-border rounded text-text-primary placeholder:text-text-disabled px-2.5 py-1.5 text-[13px] outline-none focus:border-accent"
            />
            <Button variant="secondary" size="sm" onClick={() => setShow(!show)}>
              {show ? 'Hide' : 'Show'}
            </Button>
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel} disabled={connecting}>Cancel</Button>
          <Button variant="primary" onClick={() => onConnect(pw || null)} loading={connecting}>
            {connecting ? 'Connecting...' : 'Connect'}
          </Button>
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

  return (
    <div className="flex flex-col gap-4">
      {/* Status card */}
      <Card>
        <div className="flex justify-between items-center mb-3.5">
          <CardTitle>WiFi Status</CardTitle>
          <Button variant="primary" size="sm" loading={scanning} onClick={handleScan}>
            {scanning ? 'Scanning...' : 'Scan'}
          </Button>
        </div>

        {/* Connection state */}
        <div className="flex items-center gap-2.5 mb-2.5">
          <span className="text-[13px] text-text-tertiary">Status:</span>
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
          <div className="flex flex-col gap-1.5 mb-2.5">
            {status.ssid && (
              <div className="flex gap-2">
                <span className="text-[13px] text-text-tertiary w-20">SSID</span>
                <span className="text-[13px] text-text-primary font-semibold">{status.ssid}</span>
              </div>
            )}
            {status.ip_address && (
              <div className="flex gap-2">
                <span className="text-[13px] text-text-tertiary w-20">IP Address</span>
                <span className="text-[13px] text-text-primary numeric">{status.ip_address}</span>
              </div>
            )}
            {status.freq && (
              <div className="flex gap-2">
                <span className="text-[13px] text-text-tertiary w-20">Band</span>
                <span className="text-[13px] text-text-primary">{status.freq >= 5000 ? '5 GHz' : '2.4 GHz'}</span>
              </div>
            )}
          </div>
        )}

        {status?.connected && (
          <Button
            variant="danger"
            size="sm"
            loading={disconnecting}
            onClick={handleDisconnect}
          >
            {disconnecting ? 'Disconnecting...' : 'Disconnect'}
          </Button>
        )}

        {connectError && (
          <div className="mt-2.5 text-[12px] text-danger">{connectError}</div>
        )}
        {scanError && (
          <div className="mt-2.5 text-[12px] text-danger">{scanError}</div>
        )}
      </Card>

      {/* Networks list */}
      {networks.length > 0 && (
        <Card>
          <CardTitle className="mb-3.5">Available Networks ({networks.length})</CardTitle>

          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  {['Signal', 'SSID', 'Security', 'Band', ''].map((h) => (
                    <th key={h} className="text-left text-[11px] text-text-tertiary pb-2 border-b border-border pr-4 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {networks.map((net) => {
                  const bars = signalBars(net.signal);
                  const isConnected = status?.connected && status.ssid === net.ssid;
                  return (
                    <tr key={net.bssid} className="border-b border-border">
                      <td className="py-2.5 pr-4 align-middle">
                        <SignalIcon bars={bars} />
                      </td>
                      <td className="py-2.5 pr-4 align-middle">
                        <span className={cn('text-[13px]', isConnected ? 'text-success' : 'text-text-primary')}>
                          {net.ssid}
                          {isConnected && (
                            <span className="ml-2 text-[11px] text-success">(connected)</span>
                          )}
                        </span>
                      </td>
                      <td className="py-2.5 pr-4 align-middle">
                        <span className={cn(
                          'text-[11px] px-2 py-0.5 rounded',
                          net.security === 'OPEN'
                            ? 'bg-success-soft text-success border border-success/30'
                            : 'bg-accent-soft text-accent border border-accent/30'
                        )}>
                          {net.security}
                        </span>
                      </td>
                      <td className="py-2.5 pr-4 align-middle">
                        <span className="text-[12px] text-text-tertiary">{net.band}</span>
                      </td>
                      <td className="py-2.5 align-middle text-right">
                        {!isConnected && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => { setConnectError(null); setSelectedSsid(net.ssid); }}
                            className="text-accent border border-accent/40 hover:border-accent"
                          >
                            Connect
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
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
    <Card>
      <EmptyState
        icon={
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="6.5 6.5 17.5 17.5 12 23 12 1 17.5 6.5 6.5 17.5" />
          </svg>
        }
        message="Bluetooth Not Available"
        hint={`Marvell 88W8997 Bluetooth requires a kernel rebuild. CONFIG_BT_HCIUART_MRVL=m must be enabled.`}
        className="py-12"
      />
    </Card>
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

  const inputCls = 'bg-surface-2 border border-border rounded text-text-primary px-2.5 py-1.5 text-[13px] w-full outline-none focus:border-accent';
  const labelCls = 'text-[12px] text-text-tertiary mb-0.5 block';

  return (
    <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))' }}>

      {/* Board Connection */}
      <Card>
        <CardTitle className="mb-4">Board Connection</CardTitle>

        <div className="mb-3.5">
          <div className={labelCls}>Connection Type</div>
          <div className="flex gap-4 mt-1.5">
            {(['ethernet', 'usb', 'wifi'] as ConnType[]).map((t) => (
              <label key={t} className="flex items-center gap-1.5 cursor-pointer text-[13px] text-text-secondary">
                <input type="radio" value={t} checked={connType === t} onChange={() => setConnType(t)} className="accent-accent" />
                {t === 'ethernet' ? 'Direct Ethernet' : t === 'usb' ? 'USB CDC' : 'WiFi'}
              </label>
            ))}
          </div>
        </div>

        <div className="grid gap-2.5 mb-3" style={{ gridTemplateColumns: '1fr auto' }}>
          <div>
            <label className={labelCls}>Board IP</label>
            <input className={inputCls} value={boardIp} onChange={(e) => setBoardIp(e.target.value)} />
          </div>
          <div>
            <label className={labelCls}>Port</label>
            <input className={cn(inputCls, 'w-[70px]')} value={port} onChange={(e) => setPort(e.target.value)} />
          </div>
        </div>

        <div className="flex items-center gap-2.5 mb-3.5">
          <label className="flex items-center gap-2 cursor-pointer text-[13px] text-text-secondary">
            <input type="checkbox" checked={autoReconnect} onChange={(e) => setAutoReconnect(e.target.checked)} className="accent-accent" />
            Auto-reconnect
          </label>
        </div>

        {lastConnected && (
          <div className="text-[11px] text-text-tertiary mb-3">Last connected: {lastConnected}</div>
        )}

        <div className="flex items-center gap-2.5 mb-3.5">
          <span className="text-[13px] text-text-secondary">Status:</span>
          <StatusBadge
            variant={connStatus === 'connected' ? 'success' : connStatus === 'connecting' ? 'warning' : 'error'}
            label={connStatus === 'connected' ? 'Connected' : connStatus === 'connecting' ? 'Connecting...' : 'Disconnected'}
          />
        </div>

        {error && <div className="text-[12px] text-danger mb-3">{error}</div>}

        <div className="flex gap-2">
          <Button variant="primary" onClick={handleConnect} loading={loading}>
            {loading ? 'Connecting...' : 'Connect'}
          </Button>
          <Button variant="secondary" onClick={handleDisconnect}>Disconnect</Button>
          <Button variant="secondary" onClick={handleConnect}>Reconnect</Button>
        </div>
      </Card>

      {/* System Info */}
      <Card>
        <CardTitle className="mb-4">System Info</CardTitle>
        {!sysStatus ? (
          <SkeletonLoader lines={6} />
        ) : (
          <div className="flex flex-col gap-3">
            {[
              ['SDK Version', sysStatus.sdk_version],
              ['FW Version', 'v1.0.0'],
              ['OS Version', 'Yocto Linux 6.1'],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span className="text-[13px] text-text-tertiary">{k}</span>
                <span className="text-[13px] text-text-primary numeric">{v}</span>
              </div>
            ))}

            <div>
              <div className="flex justify-between mb-1">
                <span className="text-[13px] text-text-tertiary">CPU Temp</span>
                <span className={cn('text-[13px] numeric', (sysStatus.cpu_temp_c ?? 0) >= 80 ? 'text-danger' : 'text-text-primary')}>
                  {sysStatus.cpu_temp_c?.toFixed(1) ?? 'N/A'} °C
                </span>
              </div>
              <ProgressBar value={sysStatus.cpu_temp_c ?? 0} max={100} dangerThreshold={80} />
            </div>

            <div className="flex justify-between">
              <span className="text-[13px] text-text-tertiary">Uptime</span>
              <span className="text-[13px] text-text-primary numeric">{formatUptime(sysStatus.uptime_s)}</span>
            </div>
          </div>
        )}
      </Card>

      {/* Controller Link Status */}
      <Card>
        <div className="flex justify-between items-center mb-4">
          <CardTitle>Controller Link</CardTitle>
          <Button variant="secondary" size="sm" onClick={() => setShowResetIpcModal(true)}>
            Reset Link
          </Button>
        </div>

        <div className="flex gap-2.5 mb-3.5 flex-wrap">
          <StatusBadge variant={sysStatus?.ipc_connected ? 'success' : 'error'} label={`Controller Link: ${sysStatus?.ipc_connected ? 'OK' : 'FAIL'}`} />
        </div>

        {[
          ['Tx Count',    '—'],
          ['Rx Count',    '—'],
          ['Error Rate',  '0.00 %'],
          ['Avg Latency', '—'],
        ].map(([k, v]) => (
          <div key={k} className="flex justify-between mb-2">
            <span className="text-[13px] text-text-tertiary">{k}</span>
            <span className="text-[13px] text-text-primary numeric">{v}</span>
          </div>
        ))}

        <div className="mt-3 text-[12px] text-text-tertiary">Recent Events</div>
        <div className="mt-1.5 max-h-[100px] overflow-y-auto bg-canvas rounded p-2">
          {ipcEvents.length === 0 ? (
            <div className="text-[11px] text-text-tertiary">No events</div>
          ) : ipcEvents.map((ev, i) => (
            <div key={i} className="text-[11px] text-text-tertiary border-b border-border pb-0.5 mb-0.5">{ev}</div>
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
      </Card>

      {/* Firmware Update */}
      <Card>
        <CardTitle className="mb-4">Firmware Update</CardTitle>

        <div className="mb-3.5">
          <span className="text-[13px] text-text-tertiary">Current FW: </span>
          <span className="text-[13px] text-text-primary numeric">v1.0.0</span>
        </div>

        <div
          onDrop={handleDrop}
          onDragOver={(e) => e.preventDefault()}
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
          className={cn(
            'border-2 border-dashed rounded-lg p-6 text-center cursor-pointer mb-3.5 transition-colors',
            fwFile ? 'border-accent bg-accent-soft' : 'border-border hover:border-border-strong',
          )}
        >
          {fwFile ? (
            <div>
              <div className="text-[13px] text-accent font-semibold">{fwFile.name}</div>
              <div className="text-[11px] text-text-tertiary mt-1 numeric">
                {(fwFile.size / 1024).toFixed(1)} KB
              </div>
            </div>
          ) : (
            <div className="text-[13px] text-text-tertiary">Drop .bin file here or click to browse</div>
          )}
        </div>

        {fwProgress > 0 && (
          <div className="mb-3">
            <div className="flex justify-between mb-1">
              <span className="text-[12px] text-text-tertiary">Flashing...</span>
              <span className="text-[12px] text-text-primary numeric">{fwProgress}%</span>
            </div>
            <ProgressBar value={fwProgress} max={100} />
          </div>
        )}

        <Button
          variant={fwFile && !flashing ? 'primary' : 'secondary'}
          onClick={handleFlash}
          disabled={!fwFile || flashing}
          className="w-full"
        >
          {flashing ? 'Flashing...' : 'Flash Firmware'}
        </Button>
      </Card>
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
    <div className="px-[clamp(12px,3vw,20px)] py-[clamp(12px,3vw,20px)] max-w-[1100px] mx-auto">
      <h2 className="text-[18px] font-semibold text-text-primary mb-5">Connection</h2>

      {/* Tab bar */}
      <div className="flex gap-0.5 mb-5 border-b border-border">
        {TAB_LABELS.map(({ id, label }) => {
          const isActive = activeTab === id;
          return (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={cn(
                'px-[18px] py-[9px] border-none bg-transparent text-[13px] cursor-pointer -mb-px border-b-2 transition-colors',
                isActive
                  ? 'text-text-primary font-semibold border-accent'
                  : 'text-text-tertiary font-normal border-transparent hover:text-text-secondary',
              )}
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
