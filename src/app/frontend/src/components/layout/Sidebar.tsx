/**
 * Sidebar.tsx — Collapsible navigation sidebar (240px / 56px icon-only).
 */

import { useState } from 'react';
import {
  Network, LayoutDashboard, GitBranch, Settings2, Camera, Box, Settings, ChevronLeft, ChevronRight,
  type LucideIcon,
} from 'lucide-react';
import { BG_SIDEBAR, BORDER, TEXT_PRIMARY, TEXT_MUTED } from '../../constants';
import type { Page } from '../../App';

interface SidebarProps {
  currentPage: Page;
  onNavigate: (page: Page) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

interface NavItem {
  page: Page;
  label: string;
  icon: LucideIcon;
  disabled?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { page: 'connection',  label: 'Connect',     icon: Network },
  { page: 'dashboard',   label: 'Dashboard',   icon: LayoutDashboard },
  { page: 'bending',     label: 'Bending',     icon: GitBranch },
  { page: 'motor',       label: 'Motor',       icon: Settings2 },
  { page: 'camera',      label: 'Camera',      icon: Camera },
  { page: 'simulation',  label: 'Simulation',  icon: Box, disabled: true },
  { page: 'settings',    label: 'Settings',    icon: Settings },
];

export function Sidebar({ currentPage, onNavigate, collapsed, onToggleCollapse }: SidebarProps) {
  const [hoveredPage, setHoveredPage] = useState<Page | null>(null);

  const width = collapsed ? 56 : 240;

  return (
    <aside style={{
      width,
      minWidth: width,
      height: '100%',
      background: BG_SIDEBAR,
      borderRight: `1px solid ${BORDER}`,
      display: 'flex',
      flexDirection: 'column',
      transition: 'width 0.2s ease',
      overflow: 'hidden',
      position: 'fixed',
      top: 56,
      bottom: 0,
      left: 0,
      zIndex: 100,
    }}>
      {/* Nav items */}
      <nav style={{ flex: 1, paddingTop: 8 }}>
        {NAV_ITEMS.map(({ page, label, icon: Icon, disabled }) => {
          const isActive = currentPage === page;
          const isHovered = hoveredPage === page;

          return (
            <button
              key={page}
              onClick={() => !disabled && onNavigate(page)}
              onMouseEnter={() => setHoveredPage(page)}
              onMouseLeave={() => setHoveredPage(null)}
              disabled={disabled}
              title={collapsed ? label : undefined}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: collapsed ? '12px 0' : '11px 16px',
                justifyContent: collapsed ? 'center' : 'flex-start',
                background: isActive ? '#334155' : (isHovered && !disabled ? '#263548' : 'transparent'),
                border: 'none',
                borderLeft: isActive ? '3px solid #3b82f6' : '3px solid transparent',
                cursor: disabled ? 'not-allowed' : 'pointer',
                opacity: disabled ? 0.4 : 1,
                color: isActive ? TEXT_PRIMARY : TEXT_MUTED,
                transition: 'background 0.15s, color 0.15s',
                textAlign: 'left',
              }}
            >
              <Icon size={18} color={isActive ? '#3b82f6' : isHovered && !disabled ? TEXT_PRIMARY : TEXT_MUTED} />
              {!collapsed && (
                <span style={{ fontSize: 13, fontWeight: isActive ? 600 : 400, whiteSpace: 'nowrap' }}>
                  {label}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Role badge */}
      {!collapsed && (
        <div style={{
          padding: '10px 16px',
          borderTop: `1px solid ${BORDER}`,
          fontSize: 11,
          color: TEXT_MUTED,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}>
          <span style={{
            background: '#1e3a5f',
            color: '#93c5fd',
            padding: '2px 8px',
            borderRadius: 4,
            fontWeight: 600,
          }}>
            Engineer
          </span>
          <span>Current Role</span>
        </div>
      )}

      {/* Collapse toggle */}
      <button
        onClick={onToggleCollapse}
        style={{
          width: '100%',
          padding: '10px 0',
          background: 'transparent',
          border: 'none',
          borderTop: `1px solid ${BORDER}`,
          cursor: 'pointer',
          color: TEXT_MUTED,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
      </button>
    </aside>
  );
}
