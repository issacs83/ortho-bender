/**
 * SettingsPage.tsx — User roles, appearance, and notification settings.
 */

import { useState } from 'react';
import { Card, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { StatusBadge } from '../components/ui/StatusBadge';
import { cn } from '../lib/cn';

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

const inputClass = cn(
  'w-full bg-surface-2 border border-border text-text-primary',
  'px-2.5 py-1.5 rounded text-[13px]',
  'focus:outline-none focus:border-accent/60',
);

const selectClass = cn(inputClass, 'cursor-pointer');

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
    if (pin !== ROLE_PINS[targetRole]) {
      setPinError('Incorrect PIN');
      return;
    }
    setCurrentRole(targetRole);
    setPin('');
    setPinError(null);
  }

  return (
    <div className="p-4 max-w-[700px] mx-auto">
      <h2 className="text-lg font-semibold text-text-primary mb-4">Settings</h2>

      {/* User Roles */}
      <Card className="mb-3">
        <CardTitle className="mb-4">User Role</CardTitle>

        <div className="flex items-center gap-2.5 mb-3.5">
          <span className="text-[13px] text-text-tertiary">Current Role:</span>
          <StatusBadge variant="info" label={currentRole} />
        </div>

        <div className="mb-3">
          <label className="block text-[12px] text-text-tertiary mb-1">Switch to Role</label>
          <select
            value={targetRole}
            onChange={(e) => setTargetRole(e.target.value as Role)}
            className={cn(selectClass, 'max-w-[200px]')}
          >
            {(['Operator', 'Engineer', 'Admin'] as Role[]).map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </div>

        <div className="mb-3">
          <label className="block text-[12px] text-text-tertiary mb-1">PIN</label>
          <input
            type="password"
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            placeholder="Enter role PIN"
            className={cn(inputClass, 'max-w-[200px]')}
          />
          {pinError && (
            <p className="text-[12px] text-danger mt-1">{pinError}</p>
          )}
        </div>

        <Button variant="primary" onClick={handleSwitchRole}>
          Switch Role
        </Button>

        <div className="mt-4 p-3 bg-surface-2 rounded border border-border">
          <p className="text-[12px] text-text-tertiary mb-1.5">{ROLE_INFO[currentRole].desc}</p>
          <p className="text-[11px] text-text-tertiary">
            Access: {ROLE_INFO[currentRole].access.join(' · ')}
          </p>
        </div>
      </Card>

      {/* Appearance */}
      <Card className="mb-3">
        <CardTitle className="mb-4">Appearance</CardTitle>
        <div className="grid grid-cols-2 gap-3.5">
          <div>
            <label className="block text-[12px] text-text-tertiary mb-1">Theme</label>
            <select
              value={theme}
              onChange={(e) => setTheme(e.target.value)}
              className={selectClass}
            >
              {['Dark', 'Light', 'System'].map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[12px] text-text-tertiary mb-1">Language</label>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className={selectClass}
            >
              {['English', 'Korean', 'Japanese'].map((l) => <option key={l}>{l}</option>)}
            </select>
          </div>
        </div>
      </Card>

      {/* Notifications */}
      <Card>
        <CardTitle className="mb-4">Notifications</CardTitle>
        <div className="flex flex-col gap-3">
          {([
            ['Fault / E-Stop alerts', notifFault, setNotifFault],
            ['Warning alerts',        notifWarning, setNotifWarning],
            ['Bending complete',      notifComplete, setNotifComplete],
          ] as [string, boolean, (v: boolean) => void][]).map(([label, value, setter]) => (
            <label
              key={label}
              className="flex items-center gap-2.5 cursor-pointer text-[13px] text-text-secondary"
            >
              <input
                type="checkbox"
                checked={value}
                onChange={(e) => setter(e.target.checked)}
                className="accent-accent w-4 h-4"
              />
              {label}
            </label>
          ))}
        </div>
      </Card>
    </div>
  );
}
