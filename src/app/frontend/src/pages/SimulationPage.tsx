/**
 * SimulationPage.tsx — Phase 2 placeholder.
 */

import { Box } from 'lucide-react';
import { EmptyState } from '../components/ui/EmptyState';

export function SimulationPage() {
  return (
    <div className="p-4 max-w-[1100px] mx-auto">
      <h2 className="text-lg font-semibold text-text-primary mb-4">3D Simulation</h2>
      <EmptyState
        icon={<Box size={48} />}
        message="Simulation module is under development"
        hint="Wire path visualization and collision detection will be available in a future release"
      />
    </div>
  );
}
