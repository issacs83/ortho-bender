/**
 * useSystemWs.ts — WebSocket hook for /ws/system real-time system events.
 */

import { useEffect, useRef, useState } from 'react';
import { wsApi } from '../api/client';

export interface SystemEvent {
  type: string;
  message: string;
  timestamp_us: number;
}

export function useSystemWs() {
  const [events, setEvents] = useState<SystemEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = wsApi.system((msg) => {
      if (msg.type !== 'heartbeat') {
        setEvents((prev) => [msg, ...prev.slice(0, 49)]);
      }
    });
    wsRef.current = ws;
    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, []);

  return events;
}
