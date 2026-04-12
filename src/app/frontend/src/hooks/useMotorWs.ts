/**
 * useMotorWs.ts — WebSocket hook for /ws/motor real-time motor status.
 */

import { useEffect, useRef, useState } from 'react';
import { wsApi, type MotorStatus } from '../api/client';

export function useMotorWs() {
  const [motorStatus, setMotorStatus] = useState<MotorStatus | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = wsApi.motor((msg) => {
      const { type: _type, ...status } = msg as { type: string } & MotorStatus;
      setMotorStatus(status as MotorStatus);
    });
    wsRef.current = ws;
    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, []);

  return motorStatus;
}
