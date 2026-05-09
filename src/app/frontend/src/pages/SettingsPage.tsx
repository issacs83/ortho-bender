/**
 * SettingsPage.tsx — User roles, appearance, and notification settings.
 */

import { useState } from 'react';
import { usePersistentState } from '../hooks/usePersistentState';
import { useSoftLimits, softLimitsDefault, type SoftLimits } from '../hooks/useSoftLimits';
import { usePsuConfig } from '../hooks/usePsuConfig';
import { AXIS_NAMES, AXIS_UNITS, BG_PANEL, BORDER, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, BG_PRIMARY, PSU_PRESETS, SAFETY_CS_MAX } from '../constants';
import { StatusBadge } from '../components/ui/StatusBadge';

type Role = 'Operator' | 'Engineer' | 'Admin';

const ROLE_PINS: Record<Role, string> = {
  Operator: '1234',
  Engineer: '5678',
  Admin:    '0000',
};

const ROLE_INFO: Record<Role, { desc: string; access: string[] }> = {
  Operator: {
    desc: 'Production operator — run bending sequences, monitor status',
    access: ['Dashboard', 'Bending', 'Camera view'],
  },
  Engineer: {
    desc: 'Service engineer — full motor control, driver config, diagnostics',
    access: ['All Operator features', 'Motor Control', 'Diagnostics', 'WiFi', 'Settings'],
  },
  Admin: {
    desc: 'System administrator — firmware update, reboot, factory reset',
    access: ['All Engineer features', 'System Reboot', 'Firmware Update', 'Factory Reset'],
  },
};

export function SettingsPage() {
  const [currentRole, setCurrentRole] = usePersistentState<Role>('settings.currentRole', 'Engineer');
  const [pin, setPin] = useState('');
  const [pinError, setPinError] = useState<string | null>(null);
  const [targetRole, setTargetRole] = useState<Role>('Operator');
  const [theme, setTheme] = usePersistentState('settings.theme', 'Dark');
  const [language, setLanguage] = usePersistentState('settings.language', 'English');
  const [notifFault, setNotifFault] = usePersistentState('settings.notifFault', true);
  const [notifWarning, setNotifWarning] = usePersistentState('settings.notifWarning', true);
  const [notifComplete, setNotifComplete] = usePersistentState('settings.notifComplete', false);
  const [softLimits, setSoftLimits] = useSoftLimits();
  const { psu, psuId, setPsuId, override, setOverride, effectiveCsMax } = usePsuConfig();

  function updateLimit(axisIdx: number, value: number) {
    if (!Number.isFinite(value) || value <= 0) return;
    const next = [...softLimits] as SoftLimits;
    next[axisIdx] = value;
    setSoftLimits(next);
  }

  function handleSwitchRole() {
    if (pin.length < 4) {
      setPinError('PIN must be at least 4 digits');
      return;
    }
    if (pin !== ROLE_PINS[targetRole]) {
      setPinError('Incorrect PIN');
      return;
    }
    setCurrentRole(targetRole);
    setPin('');
    setPinError(null);
  }

  const cardStyle = { background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 20, marginBottom: 16 };
  const inputStyle = { background: BG_PRIMARY, border: `1px solid ${BORDER}`, color: TEXT_PRIMARY, padding: '6px 10px', borderRadius: 4, fontSize: 13, width: '100%' };
  const selectStyle = { ...inputStyle };

  return (
    <div style={{ padding: 20, maxWidth: 700, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 20px', color: TEXT_PRIMARY, fontSize: 18 }}>Settings</h2>

      {/* User Roles */}
      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 16px', fontSize: 14, color: TEXT_PRIMARY }}>User Role</h3>
        <div style={{ marginBottom: 14, display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 13, color: TEXT_MUTED }}>Current Role:</span>
          <StatusBadge variant="info" label={currentRole} />
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, color: TEXT_MUTED, display: 'block', marginBottom: 4 }}>Switch to Role</label>
          <select value={targetRole} onChange={(e) => setTargetRole(e.target.value as Role)} style={{ ...selectStyle, width: 200 }}>
            {(['Operator', 'Engineer', 'Admin'] as Role[]).map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, color: TEXT_MUTED, display: 'block', marginBottom: 4 }}>PIN</label>
          <input
            type="password"
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            placeholder="Enter role PIN"
            style={{ ...inputStyle, width: 200 }}
          />
          {pinError && <div style={{ fontSize: 12, color: '#ef4444', marginTop: 4 }}>{pinError}</div>}
        </div>

        <button
          onClick={handleSwitchRole}
          style={{ background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 6, padding: '8px 16px', cursor: 'pointer', fontSize: 13, fontWeight: 600 }}
        >
          Switch Role
        </button>

        <div style={{ marginTop: 16, padding: 12, background: BG_PRIMARY, borderRadius: 6, border: `1px solid ${BORDER}` }}>
          <div style={{ fontSize: 12, color: TEXT_MUTED, marginBottom: 6 }}>{ROLE_INFO[currentRole].desc}</div>
          <div style={{ fontSize: 11, color: TEXT_MUTED }}>
            Access: {ROLE_INFO[currentRole].access.join(' · ')}
          </div>
        </div>
      </div>

      {/* Appearance */}
      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 16px', fontSize: 14, color: TEXT_PRIMARY }}>Appearance</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div>
            <label style={{ fontSize: 12, color: TEXT_MUTED, display: 'block', marginBottom: 4 }}>Theme</label>
            <select value={theme} onChange={(e) => setTheme(e.target.value)} style={selectStyle}>
              {['Dark', 'Light', 'System'].map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_MUTED, display: 'block', marginBottom: 4 }}>Language</label>
            <select value={language} onChange={(e) => setLanguage(e.target.value)} style={selectStyle}>
              {['English', 'Korean', 'Japanese'].map((l) => <option key={l}>{l}</option>)}
            </select>
          </div>
        </div>
      </div>

      {/* Power Supply + Driver safety cap */}
      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 6px', fontSize: 14, color: TEXT_PRIMARY }}>Power Supply</h3>
        <div style={{ fontSize: 11, color: TEXT_MUTED, marginBottom: 14 }}>
          Selecting the actual benchtop PSU caps IRUN/IHOLD on the Driver Config tab so the
          driver cannot be set above what the supply can sustain. Hardware safety max is
          CS = <strong style={{ color: '#fcd34d' }}>{SAFETY_CS_MAX}</strong> (boards burned 2026-05-08 with CS=31).
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 12 }}>
          <div>
            <label style={{ fontSize: 12, color: TEXT_MUTED, display: 'block', marginBottom: 4 }}>PSU preset</label>
            <select value={psuId} onChange={(e) => setPsuId(e.target.value)} style={selectStyle}>
              {PSU_PRESETS.map((p) => <option key={p.id} value={p.id}>{p.label} → CS≤{p.csCap}</option>)}
            </select>
          </div>
          <div>
            <label style={{ fontSize: 12, color: TEXT_MUTED, display: 'block', marginBottom: 4 }}>
              Manual CS cap override <span style={{ color: TEXT_MUTED }}>(0 = use preset)</span>
            </label>
            <input
              type="number"
              min={0}
              max={SAFETY_CS_MAX}
              value={override}
              onChange={(e) => {
                const v = Number(e.target.value);
                if (!Number.isFinite(v)) return;
                setOverride(Math.min(SAFETY_CS_MAX, Math.max(0, v)));
              }}
              style={inputStyle}
            />
          </div>
        </div>
        <div style={{ padding: 10, background: BG_PRIMARY, borderRadius: 6, border: `1px solid ${BORDER}`, fontSize: 12, color: TEXT_SECONDARY }}>
          Active PSU: <strong style={{ color: TEXT_PRIMARY }}>{psu.label}</strong>
          &nbsp;·&nbsp; Effective CS cap: <strong style={{ color: '#fcd34d' }}>{effectiveCsMax}</strong>
          &nbsp;·&nbsp; Hardware max: {SAFETY_CS_MAX}
        </div>
      </div>

      {/* Motor Soft Limits */}
      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 6px', fontSize: 14, color: TEXT_PRIMARY }}>Motor Soft Limits</h3>
        <div style={{ fontSize: 11, color: TEXT_MUTED, marginBottom: 14 }}>
          Position progress bar reference per axis. Bar turns amber at 80%, red beyond 100%.
          Stored locally in this browser — does not change motor firmware limits.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12 }}>
          {AXIS_NAMES.map((name, i) => (
            <div key={name}>
              <label style={{ fontSize: 12, color: TEXT_MUTED, display: 'block', marginBottom: 4 }}>
                {name} ({AXIS_UNITS[i]})
              </label>
              <input
                type="number"
                min={1}
                step={1}
                value={softLimits[i]}
                onChange={(e) => updateLimit(i, Number(e.target.value))}
                style={inputStyle}
              />
            </div>
          ))}
        </div>
        <button
          onClick={() => setSoftLimits(softLimitsDefault())}
          style={{ marginTop: 14, background: 'transparent', color: TEXT_SECONDARY, border: `1px solid ${BORDER}`, borderRadius: 4, padding: '6px 12px', cursor: 'pointer', fontSize: 12 }}
        >
          Reset to defaults
        </button>
      </div>

      {/* Notifications */}
      <div style={cardStyle}>
        <h3 style={{ margin: '0 0 16px', fontSize: 14, color: TEXT_PRIMARY }}>Notifications</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {([
            ['Fault / E-Stop alerts', notifFault, setNotifFault],
            ['Warning alerts',        notifWarning, setNotifWarning],
            ['Bending complete',      notifComplete, setNotifComplete],
          ] as [string, boolean, (v: boolean) => void][]).map(([label, value, setter]) => (
            <label key={label} style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', fontSize: 13, color: TEXT_SECONDARY }}>
              <input
                type="checkbox"
                checked={value}
                onChange={(e) => setter(e.target.checked)}
                style={{ accentColor: '#3b82f6', width: 16, height: 16 }}
              />
              {label}
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}
