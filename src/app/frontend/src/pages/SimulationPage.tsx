/**
 * SimulationPage.tsx — Phase 2 placeholder.
 */

import { Box } from 'lucide-react';
import { TEXT_PRIMARY, TEXT_MUTED, BG_PANEL, BORDER } from '../constants';

export function SimulationPage() {
  return (
    <div style={{ padding: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 'calc(100vh - 200px)' }}>
      <div style={{ textAlign: 'center', background: BG_PANEL, border: `1px solid ${BORDER}`, borderRadius: 12, padding: 60, maxWidth: 400 }}>
        <Box size={48} color="#334155" style={{ marginBottom: 16 }} />
        <h2 style={{ margin: '0 0 10px', color: TEXT_PRIMARY, fontSize: 20 }}>Coming Soon</h2>
        <p style={{ margin: 0, color: TEXT_MUTED, fontSize: 14, lineHeight: 1.6 }}>
          3D wire bending simulation and motion preview will be available in Phase 2.
        </p>
      </div>
    </div>
  );
}
