/**
 * RegisterInspector.tsx — TMC register read/write panel.
 *
 * Dropdown selects driver, text input for address and value,
 * Read/Write buttons, shows last result.
 */

import { useState } from 'react';
import { diagApi, type DiagRegisterResult } from '../api/client';

const DRIVERS = ['tmc260c_0', 'tmc260c_1', 'tmc5072'] as const;

const BTN_STYLE: React.CSSProperties = {
  padding: '6px 16px',
  borderRadius: 6,
  border: 'none',
  cursor: 'pointer',
  fontWeight: 600,
  fontSize: 13,
};

export function RegisterInspector() {
  const [driver, setDriver] = useState<string>('tmc260c_0');
  const [addr, setAddr] = useState('0x04');
  const [writeValue, setWriteValue] = useState('');
  const [result, setResult] = useState<DiagRegisterResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleRead() {
    setLoading(true);
    setError(null);
    try {
      const r = await diagApi.readRegister(driver, addr);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleWrite() {
    if (!writeValue) return;
    setLoading(true);
    setError(null);
    try {
      const val = parseInt(writeValue, writeValue.startsWith('0x') ? 16 : 10);
      const r = await diagApi.writeRegister(driver, addr, val);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ fontSize: 12, color: '#94a3b8' }}>Driver:</label>
        <select
          value={driver}
          onChange={e => setDriver(e.target.value)}
          style={{ background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155', borderRadius: 4, padding: '4px 8px' }}
        >
          {DRIVERS.map(d => <option key={d} value={d}>{d}</option>)}
        </select>

        <label style={{ fontSize: 12, color: '#94a3b8' }}>Addr:</label>
        <input
          value={addr}
          onChange={e => setAddr(e.target.value)}
          style={{ width: 60, background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155', borderRadius: 4, padding: '4px 8px', fontFamily: 'monospace' }}
        />

        <button
          onClick={handleRead}
          disabled={loading}
          style={{ ...BTN_STYLE, background: '#3b82f6', color: '#fff' }}
        >
          Read
        </button>
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ fontSize: 12, color: '#94a3b8' }}>Value:</label>
        <input
          value={writeValue}
          onChange={e => setWriteValue(e.target.value)}
          placeholder="0x101D5"
          style={{ width: 100, background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155', borderRadius: 4, padding: '4px 8px', fontFamily: 'monospace' }}
        />

        <button
          onClick={handleWrite}
          disabled={loading || !writeValue}
          style={{ ...BTN_STYLE, background: '#f59e0b', color: '#000' }}
        >
          Write
        </button>
      </div>

      {error && (
        <div style={{ color: '#ef4444', fontSize: 12 }}>Error: {error}</div>
      )}

      {result && (
        <div style={{ fontSize: 12, color: '#94a3b8', fontFamily: 'monospace' }}>
          Last: {result.driver} [{result.addr}] = {result.value_hex}
        </div>
      )}
    </div>
  );
}
