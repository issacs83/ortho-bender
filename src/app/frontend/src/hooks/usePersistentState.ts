/**
 * usePersistentState.ts — useState replacement that mirrors to localStorage.
 *
 * Drop-in replacement for useState<T>: state survives page reloads, browser
 * restarts, and tab navigation. Each call site supplies a unique storage key.
 *
 * Usage:
 *   const [jogSpeed, setJogSpeed] = usePersistentState('motor.jogSpeed', 10);
 *   const [subTab,   setSubTab]   = usePersistentState<MotorSubTab>('motor.subTab', 'position');
 *
 * Keys are namespaced with 'ortho-bender:' so they don't clash with anything
 * else served from the same origin.
 */

import { useEffect, useRef, useState } from 'react';

const NS = 'ortho-bender:';

function read<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(NS + key);
    if (raw === null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function write<T>(key: string, value: T): void {
  try {
    window.localStorage.setItem(NS + key, JSON.stringify(value));
  } catch {
    /* quota / disabled / private mode — silently ignore */
  }
}

export function usePersistentState<T>(
  key: string,
  initial: T
): [T, React.Dispatch<React.SetStateAction<T>>] {
  // Lazy init from localStorage on first render only
  const [state, setState] = useState<T>(() => read<T>(key, initial));

  // Track latest key so the StorageEvent listener uses the right one
  const keyRef = useRef(key);
  keyRef.current = key;

  // Mirror every state change back to localStorage
  useEffect(() => {
    write(key, state);
  }, [key, state]);

  // Cross-tab sync: react when another tab updates the same key
  useEffect(() => {
    const onStorage = (ev: StorageEvent) => {
      if (ev.key === NS + keyRef.current && ev.newValue !== null) {
        try {
          setState(JSON.parse(ev.newValue) as T);
        } catch {
          /* corrupt stored value */
        }
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  return [state, setState];
}
