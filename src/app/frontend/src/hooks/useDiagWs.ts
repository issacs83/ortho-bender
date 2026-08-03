/**
 * useDiagWs.ts — WebSocket hook that pipes /ws/motor/diag events into an OscilloscopeBuffer.
 *
 * Each DiagEvent carries per-driver sg_result values. The hook maps selected
 * channelKeys (driver names) to buffer channels, using performance.now() / 1000
 * as the monotonic timestamp for X-axis alignment with the oscilloscope.
 */

import { useEffect, useRef } from 'react';
import { wsApi, type DiagEvent } from '../api/client';
import type { OscilloscopeBuffer } from '../components/charts/OscilloscopeBuffer';

interface UseDiagWsOptions {
  buffer: OscilloscopeBuffer;
  channelKeys: string[];
  enabled?: boolean;
}

export function useDiagWs({ buffer, channelKeys, enabled = true }: UseDiagWsOptions): void {
  const bufferRef = useRef(buffer);
  bufferRef.current = buffer;

  useEffect(() => {
    if (!enabled) return;

    const ws = wsApi.motorDiag((evt: DiagEvent) => {
      const now = performance.now() / 1000;
      const values = channelKeys.map((key) => evt.drivers[key]?.sg_result ?? 0);
      bufferRef.current.push(now, values);
    });

    return () => ws.close();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, channelKeys.join(',')]);
}
