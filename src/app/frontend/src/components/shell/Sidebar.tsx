import { cn } from '../../lib/cn';
import {
  LayoutDashboard, Cable, Wrench, Gauge, Camera,
  Box, Settings, Stethoscope, FileText,
} from 'lucide-react';
import type { Page } from '../../App';

interface SidebarProps {
  currentPage: Page;
  onNavigate: (page: Page) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

const NAV_ITEMS: { page: Page; icon: typeof LayoutDashboard; label: string; disabled?: boolean }[] = [
  { page: 'dashboard',   icon: LayoutDashboard, label: 'Dashboard' },
  { page: 'connection',  icon: Cable,           label: 'Connection' },
  { page: 'bending',     icon: Wrench,          label: 'Bending' },
  { page: 'motor',       icon: Gauge,           label: 'Motor' },
  { page: 'camera',      icon: Camera,          label: 'Camera' },
  { page: 'diagnostics', icon: Stethoscope,     label: 'Diagnostics' },
  { page: 'simulation',  icon: Box,             label: 'Simulation', disabled: true },
  { page: 'settings',    icon: Settings,        label: 'Settings' },
  { page: 'docs',        icon: FileText,        label: 'Documentation' },
];

export function Sidebar({ currentPage, onNavigate, collapsed }: SidebarProps) {
  return (
    <nav
      className={cn(
        'fixed top-14 left-0 bottom-0 z-[100] bg-surface-1 border-r border-border',
        'flex flex-col py-2 transition-[width] duration-default overflow-hidden',
        collapsed ? 'w-14' : 'w-60',
      )}
    >
      {NAV_ITEMS.map(({ page, icon: Icon, label, disabled }) => {
        const active = currentPage === page;
        return (
          <button
            key={page}
            onClick={() => !disabled && onNavigate(page)}
            disabled={disabled}
            title={disabled ? 'Coming soon' : collapsed ? label : undefined}
            className={cn(
              'relative flex items-center gap-3.5 px-4 py-2.5 text-left transition-colors duration-fast',
              'hover:bg-surface-2',
              active && 'bg-surface-2',
              disabled && 'opacity-40 cursor-not-allowed',
            )}
          >
            {/* Active accent bar */}
            {active && (
              <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-accent rounded-r" />
            )}
            <Icon size={18} className={cn(
              'shrink-0',
              active ? 'text-accent' : 'text-text-tertiary',
            )} />
            {!collapsed && (
              <span className={cn(
                'text-[13px] whitespace-nowrap',
                active ? 'text-text-primary font-semibold' : 'text-text-secondary',
              )}>
                {label}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}
