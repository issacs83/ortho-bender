/**
 * SettingsPage.tsx — User roles, appearance, and notification settings.
 */

import { useState } from 'react';
import { BG_PANEL, BORDER, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, BG_PRIMARY } from '../constants';
import { StatusBadge } from '../components/ui/StatusBadge';

type Role = 'Operator' | 'Engineer' | 'Admin';

export function SettingsPage() {
  const [currentRole, setCurrentRole] = useState<Role>('Engineer');
  const [pin, setPin] = useState('');
  const [pinError, setPinError] = useState<string | null>(null);
  const [targetRole, setTargetRole] = useState<Role>('Operator');
  const [theme, setTheme] = useState('Dark');
  const [language, setLanguage] = useState('English');
  const [notifFault, setNotifFault] = useState(true);
  const [notifWarning, setNotifWarning] = useState(true);
  const [notifComplete, setNotifComplete] = useState(false);

  function handleSwitchRole() {
    if (pin.length < 4) {
      setPinError('PIN must be at least 4 digits');
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
