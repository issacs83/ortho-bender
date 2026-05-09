/**
 * ToastSystem.tsx — global toast/notification provider.
 *
 * Mount <ToastProvider> once at the app root, then anywhere in the tree
 * call useToast() to push messages:
 *
 *   const toast = useToast();
 *   toast.warn('IRUN clamped 17 → 14 by PSU 12 V / 2.0 A');
 *   toast.error('Backend rejected: CS=31 exceeds safety limit 19');
 *   toast.info('PSU set to 12 V / 2.9 A (35 W)');
 *   toast.success('Driver settings applied');
 *
 * Toasts auto-dismiss after `durationMs` (default 5 s, errors are sticky
 * unless explicitly given a duration). Click × to dismiss earlier.
 */

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { BG_PANEL, BORDER, TEXT_PRIMARY } from '../../constants';

export type ToastLevel = 'info' | 'success' | 'warn' | 'error';

export interface ToastEntry {
  id: number;
  level: ToastLevel;
  message: string;
  durationMs: number; // 0 = sticky
}

interface ToastApi {
  push: (level: ToastLevel, message: string, durationMs?: number) => void;
  info:    (message: string, durationMs?: number) => void;
  success: (message: string, durationMs?: number) => void;
  warn:    (message: string, durationMs?: number) => void;
  error:   (message: string, durationMs?: number) => void;
}

const ToastCtx = createContext<ToastApi | null>(null);

const COLORS: Record<ToastLevel, { fg: string; border: string; icon: string }> = {
  info:    { fg: '#bae6fd', border: '#0284c7', icon: 'ℹ' },
  success: { fg: '#bbf7d0', border: '#16a34a', icon: '✓' },
  warn:    { fg: '#fcd34d', border: '#d97706', icon: '⚠' },
  error:   { fg: '#fca5a5', border: '#dc2626', icon: '✕' },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastEntry[]>([]);

  const push = useCallback((level: ToastLevel, message: string, durationMs?: number) => {
    const id = Date.now() + Math.random();
    const dflt = level === 'error' ? 0 : 5000;
    setItems((prev) => [...prev, { id, level, message, durationMs: durationMs ?? dflt }]);
  }, []);

  const api: ToastApi = {
    push,
    info:    (m, d) => push('info',    m, d),
    success: (m, d) => push('success', m, d),
    warn:    (m, d) => push('warn',    m, d),
    error:   (m, d) => push('error',   m, d),
  };

  return (
    <ToastCtx.Provider value={api}>
      {children}
      <ToastContainer items={items} onDismiss={(id) => setItems((p) => p.filter((t) => t.id !== id))} />
    </ToastCtx.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>');
  return ctx;
}

function ToastContainer({ items, onDismiss }: { items: ToastEntry[]; onDismiss: (id: number) => void }) {
  return (
    <div
      style={{
        position: 'fixed', top: 70, right: 16, zIndex: 1200,
        display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 380,
      }}
    >
      {items.map((t) => (
        <ToastItem key={t.id} entry={t} onDismiss={() => onDismiss(t.id)} />
      ))}
    </div>
  );
}

function ToastItem({ entry, onDismiss }: { entry: ToastEntry; onDismiss: () => void }) {
  const c = COLORS[entry.level];
  useEffect(() => {
    if (entry.durationMs <= 0) return;
    const id = setTimeout(onDismiss, entry.durationMs);
    return () => clearTimeout(id);
  }, [entry.durationMs, onDismiss]);
  return (
    <div
      role="status"
      style={{
        background: BG_PANEL, border: `1px solid ${c.border}`, borderRadius: 6,
        padding: '10px 12px', color: TEXT_PRIMARY, fontSize: 13,
        boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
        display: 'grid', gridTemplateColumns: '20px 1fr 20px', gap: 8, alignItems: 'start',
      }}
    >
      <span style={{ color: c.fg, fontWeight: 700 }}>{c.icon}</span>
      <span style={{ lineHeight: 1.4, whiteSpace: 'pre-wrap' as const }}>{entry.message}</span>
      <button
        onClick={onDismiss}
        aria-label="Dismiss"
        style={{
          background: 'transparent', border: 'none', color: BORDER,
          cursor: 'pointer', fontSize: 14, padding: 0, lineHeight: 1,
        }}
      >×</button>
    </div>
  );
}
