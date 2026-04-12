/**
 * useCameraWs.ts — WebSocket hook for /ws/camera real-time frames.
 */

import { useEffect, useRef, useState } from 'react';
import { wsApi } from '../api/client';

export function useCameraWs(enabled: boolean) {
  const [frame, setFrame] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const ws = wsApi.camera((msg) => {
      if (msg.frame_b64) setFrame(msg.frame_b64);
    });
    wsRef.current = ws;
    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [enabled]);

  return frame;
}
