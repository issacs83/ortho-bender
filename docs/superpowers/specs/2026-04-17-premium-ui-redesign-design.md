# Premium UX/UI Redesign — Design Spec

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this spec.

**Goal:** Transform the Ortho-Bender SDK Dashboard from a functional prototype into a medical-device-grade HMI with consistent design tokens, zero-flicker oscilloscope charts, and premium visual polish.

**Branch:** `ui/premium-redesign` (from `feature/motor-test-bench`)

**Merge strategy:** Sprint-end merges back into `feature/motor-test-bench`

---

## 1. Design Decisions (Confirmed)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Color palette | OLED-safe Blue-Grey (#0B0E13 base) | Reduced eye strain, no afterimage on IPS/OLED, Apple HIG + Material 3 aligned |
| Header layout | Grouped Chips — 3 zones with separators | All info visible at once, no click required, clear visual grouping |
| Dashboard layout | KPI Strip + 2x2 balanced grid | Equal weight to system/motor/actions/alarms, KPI numbers prominent |
| CSS methodology | Tailwind CSS + CSS Variables tokens | Build-time compilation, zero runtime cost, token-driven consistency |
| Chart library | uPlot (StallGuard oscilloscope) | 7KB, 100K+ points at 60fps, zero-copy TypedArray support |
| Component base | Selective shadcn/ui (Button, Card, Input, Tabs, Select only) | Accessible primitives without full library overhead |
| Numeric font | JetBrains Mono (woff2, ~50KB) | Tabular numbers, slashed zero — critical for data readability |
| Body font | system-ui (no custom font) | Zero download cost, i.MX8MP serves frontend directly |
| State management | Keep useState + fetch (no Zustand/TanStack) | Current complexity doesn't justify migration |
| WebSocket format | MessagePack binary (Sprint 2) | 10x bandwidth reduction vs JSON for StallGuard streaming |

## 2. Design System

### 2.1 Color Tokens

```css
:root {
  /* Backgrounds — 3-level depth */
  --bg-canvas:    #0B0E13;
  --bg-surface-1: #131821;
  --bg-surface-2: #1A2030;
  --bg-surface-3: #232B3D;

  /* Borders — opacity-based for consistency */
  --border-subtle:  rgba(255, 255, 255, 0.06);
  --border-default: rgba(255, 255, 255, 0.10);
  --border-strong:  rgba(255, 255, 255, 0.16);

  /* Text — 4-level hierarchy */
  --text-primary:   #ECEFF4;
  --text-secondary: #B4BCCC;
  --text-tertiary:  #7A8499;
  --text-disabled:  #4A5263;

  /* Brand accent */
  --accent:      #5B8DEF;
  --accent-soft: rgba(91, 141, 239, 0.12);

  /* Semantic — restrained saturation (S:60-70%, L:60-65%) */
  --success:      #4ECB8B;
  --success-soft: rgba(78, 203, 139, 0.12);
  --warning:      #F2B441;
  --warning-soft: rgba(242, 180, 65, 0.12);
  --danger:       #EF5B5B;
  --danger-soft:  rgba(239, 91, 91, 0.12);
  --info:         #5DCFE0;
  --info-soft:    rgba(93, 207, 224, 0.12);

  /* Channel colors — colorblind-safe palette */
  --ch-feed:   #5B8DEF;   /* blue */
  --ch-bend:   #F2B441;   /* gold */
  --ch-rotate: #C780E8;   /* purple */
  --ch-lift:   #4ECB8B;   /* green */
}
```

### 2.2 Typography

```css
:root {
  --font-body: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, 'Cascadia Code', monospace;
}

/* Type scale (Major Third 1.250) */
--text-xs:   11px / 16px;   /* labels, captions */
--text-sm:   13px / 20px;   /* body small */
--text-base: 14px / 22px;   /* body default */
--text-md:   16px / 24px;   /* card titles */
--text-lg:   20px / 28px;   /* section headings */
--text-xl:   28px / 36px;   /* page titles */

/* Numeric values use mono with tabular figures */
.numeric {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums slashed-zero;
}
```

### 2.3 Spacing & Radius (8-point grid)

```
Spacing:  4 / 8 / 12 / 16 / 24 / 32 / 48 / 64
Radius:   4 (input) / 8 (button) / 12 (card) / 16 (modal) / 999 (chip/pill)
Shadow:   Dark mode uses inset highlight instead of drop shadow
          box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
```

### 2.4 Motion

- Micro interactions: 120ms
- Default transitions: 200ms
- Page transitions: 320ms
- Easing: `cubic-bezier(0.4, 0, 0.2, 1)`
- Data value changes: **no animation** (medical device — animated numbers reduce trust)
- `prefers-reduced-motion`: all transitions disabled

## 3. StallGuard2 Oscilloscope

### 3.1 Behavior Model

The current Recharts implementation recalculates X-axis domain on every data push, causing label flicker and visual fatigue. The redesign uses an oscilloscope model:

- **Fixed X-axis window**: default 30s, user-selectable (5s / 10s / 30s / 60s / 300s)
- **X-axis labels**: relative time (-30s, -25s, ..., -5s, now) or absolute HH:MM:SS toggle
- **X-axis domain is locked**: `[now - windowSpan, now]`, never recalculated from data
- **New data slides in** from right, old data exits left
- **Y-axis modes**: Auto-scale / Manual (0–1023) / Fit-to-data

### 3.2 Technical Implementation

**RingBuffer** — pre-allocated Float64Array, O(1) push, zero GC pressure:

```typescript
class OscilloscopeBuffer {
  private xs: Float64Array;        // timestamps
  private ys: Float64Array[];      // per-channel values
  private writeIdx = 0;
  private filled = 0;
  private displayXs: Float64Array; // reused view buffer
  private displayYs: Float64Array[];

  constructor(capacity: number, channels: number);
  push(t: number, values: number[]): void;      // O(1)
  fillWindow(now: number, span: number): readonly Float64Array[];  // returns subarray views
}
```

**uPlot wrapper** — created once, never re-instantiated:

- `useEffect([], ...)` creates uPlot instance
- `requestAnimationFrame` loop calls `uplot.setData(buffer.fillWindow(...), false)`
- Second arg `false` = skip auto-scale recalculation
- X-axis `range` set as function returning `[now - span, now]`

**Controls**:
- Channel toggles (FEED / BEND / ROTATE / LIFT) with channel colors
- Window span selector (5s / 10s / 30s / 60s / 300s)
- Y-scale mode (Auto / Manual / Fit)
- Pause/Resume (paused = data still buffers, resume catches up)
- 2 draggable cursors with delta display (time diff + value diff)
- Threshold reference line (draggable horizontal)
- Export: CSV (raw data in window) + PNG (chart screenshot)

### 3.3 Backend Streaming (Sprint 2)

Current: JSON text frames at ~20fps (downsampled from 200Hz in frontend).

Target: MessagePack binary frames at ~60Hz with min/max/avg per batch:

```python
# Backend batches 1kHz → 60Hz with min/max preservation
packet = {
    't': timestamp,
    'feed':   {'min': float, 'max': float, 'avg': float},
    'bend':   {'min': float, 'max': float, 'avg': float},
    ...
}
# Sent as msgpack binary frame every 16ms
```

Benefits: 10x bandwidth reduction (80KB/s → 8KB/s), no transient data loss due to min/max pairs.

## 4. Component Architecture

### 4.1 New File Structure

```
src/app/frontend/src/
├── styles/
│   ├── tokens.css              # CSS Variables (§2 tokens)
│   └── globals.css             # Tailwind directives + base styles
├── components/
│   ├── ui/                     # Base components (shadcn/ui customized)
│   │   ├── Button.tsx
│   │   ├── Card.tsx
│   │   ├── Input.tsx
│   │   ├── Tabs.tsx
│   │   ├── Select.tsx
│   │   ├── StatusBadge.tsx     # Rewritten with tokens
│   │   ├── MotionStatePill.tsx # Rewritten with tokens
│   │   ├── EStopButton.tsx     # Outline idle / fill active
│   │   ├── ConfirmModal.tsx    # Token-based
│   │   ├── SkeletonLoader.tsx  # Token-based
│   │   └── EmptyState.tsx      # NEW: icon + message + hint
│   ├── shell/
│   │   ├── Header.tsx          # 3-zone grouped chips
│   │   ├── Sidebar.tsx         # Active accent bar
│   │   └── AlarmBanner.tsx     # Token-based
│   ├── charts/
│   │   ├── OscilloscopeBuffer.ts    # RingBuffer (Float64Array)
│   │   ├── Oscilloscope.tsx         # uPlot wrapper
│   │   ├── OscilloscopeControls.tsx # Window/Y-scale/Pause/Export
│   │   └── CursorOverlay.tsx        # Dual cursor + delta display
│   └── domain/                 # Domain-specific widgets
│       ├── KpiStrip.tsx        # Dashboard hero numbers
│       ├── AxisStatusRow.tsx   # Colored bar + name + status
│       └── ChannelLegend.tsx   # Chart channel toggles
├── hooks/
│   ├── useMotorWs.ts           # Existing (unchanged)
│   ├── useSystemWs.ts          # Existing (unchanged)
│   ├── useCameraWs.ts          # Existing (unchanged)
│   └── useDiagWs.ts            # NEW: binary WS → RingBuffer pipe
├── lib/
│   ├── format.ts               # Unit formatting (°C, mm, °, μs)
│   └── cn.ts                   # Tailwind class merge utility
├── pages/                      # 9 pages (all rewritten with tokens + Tailwind)
│   ├── DashboardPage.tsx
│   ├── ConnectionPage.tsx
│   ├── BendingPage.tsx
│   ├── MotorPage.tsx
│   ├── CameraPage.tsx
│   ├── DiagnosticsPage.tsx
│   ├── SettingsPage.tsx
│   ├── DocumentationPage.tsx
│   └── SimulationPage.tsx
├── constants.ts                # DELETED — replaced by tokens.css
├── api/client.ts               # Add msgpack decode support
├── App.tsx                     # Shell composition
└── main.tsx                    # Entry
```

### 4.2 Migration Strategy

All existing components are rewritten in-place (same filenames) but restructured into the new directory layout. The migration is **not incremental** — this is a branch-based full rewrite.

Key changes:
1. `constants.ts` → `styles/tokens.css` (CSS Variables) + Tailwind config referencing tokens
2. All inline `style={{}}` → Tailwind classes
3. Recharts `StallGuardChart` → uPlot `Oscilloscope`
4. `components/layout/` → `components/shell/`
5. New `components/charts/` directory for oscilloscope
6. New `components/domain/` for reusable domain widgets
7. New `lib/format.ts` for consistent unit display

## 5. Screen-by-Screen Spec

### 5.1 Global Shell

**Header (56px fixed)**:
- 3 zones separated by 1px vertical dividers (rgba white 8%)
- Left: hamburger + "Ortho-Bender" (font-weight 700, letter-spacing 0.5px)
- Center: MotionStatePill (pill shape, 999 radius) | divider | subsystem dots (6px circles with labels: SYS, LINK, MTR, CAM) | divider | alarm bell icon + count
- Right: E-STOP button
  - IDLE/HOMING/RUNNING: outline style (transparent bg, danger border 30% opacity, danger text)
  - ESTOP state: solid fill (danger bg, white text, pulse animation)
  - FAULT state: warning outline

**Sidebar**:
- Active item: 2px left accent bar (--accent), bg-surface-2 background
- Inactive items: text-tertiary, hover → bg-surface-2
- Simulation item: opacity 0.4, "Coming soon" tooltip
- Icon-text gap: 14px
- Collapsed mode: icons only, 56px width

### 5.2 Dashboard

**KPI Strip** (top row, 4 equal cards):
- CPU Temp | Uptime | Bend Cycles | Last Run
- Large mono numbers (24px, --font-mono, tabular-nums)
- Labels: 10px uppercase, letter-spacing 1px, text-tertiary
- Units: 12px text-tertiary inline after number

**2x2 Card Grid** (below KPI strip):
1. **System Health**: status summary text next to title ("All nominal" / "1 issue"), subsystem badges, SDK version
2. **Motor Readiness**: status summary ("3 offline"), per-axis rows with channel color bar (3px × 16px), axis name, status chip
3. **Quick Actions**: 2x2 button grid. Start Bending = accent filled. Others = surface-2 + border. Reset Fault disabled when no fault (opacity 0.5, cursor not-allowed)
4. **Alarm History**: title + "View All" link. Empty state: bell icon (32px, text-disabled) + "No active alarms" + "System events will appear here" hint

**All cards**: bg-surface-1, border-default, radius 12px (not 8px), inset highlight shadow.

### 5.3 Connection Page

- Board Connection card: 4px left green/red bar indicating connection state
- "Last connected" in relative time ("2 minutes ago")
- Controller Link: add Tx/Rx mini sparkline (last 60s) using simple canvas element
- Firmware Update dropzone: icon + hint text + procedure link in empty state

### 5.4 Bending Wizard

- Step indicator: completed steps show checkmark + clickable (navigate back)
- Wire Profile card: add diameter visual comparison (simple SVG circles at scale)
- Material Properties: property gauge bars (Springback: filled bar + label "High")
- Pre-flight checks: channel-colored status per axis

### 5.5 Motor Control

- Per-axis channel color bar on left (3px, full height of row)
- Target position ghost marker when Move To value entered
- Energize toggle: segmented control `[DE-ENERGIZED ●━━○ ENERGIZED]`
- Driver NOT FOUND: icon + cause text + inline "Re-Probe" button
- Velocity/position values: mono font, tabular-nums

### 5.6 Diagnostics

- StallGuard chart promoted to main content (full width, 480px height)
- SPI Test / Register Inspector / Register Dump as compact toolbar buttons above chart
- Below chart: per-channel stats panel (current value, average, peak, min)
- Register Inspector: right slide-out panel (not modal), doesn't obscure chart

### 5.7 Camera

- Live & Capture: metadata overlay with semi-transparent background box for readability
- Capture button shows keyboard shortcut hint ("Capture · Space")
- Status bar (Connected/Backend/Frames) integrated into video container bottom
- Acquisition: segmented control for Manual/Auto (not radio buttons)
- ExposureTime slider: log scale option for 1μs–60s range
- Apply buttons: only active when value changed (dirty indicator dot)
- Image Processing: histogram with log scale toggle, clipping warning (0/255 pixel ratio)
- Gallery empty state: illustration + 3-step usage guide + shortcut hints
- Gallery populated: grid/list view toggle, sort, filter, multi-select

### 5.8 Settings

- Role section: permission matrix visualization (table showing which features each role can access)
- Theme: Dark / Light / Auto + High Contrast option
- Language: ko / en + unit system toggle (mm / inch)
- About section: version, license, open-source acknowledgements

### 5.9 Documentation

- File tree: folder vs file icons, file extension chips (MD / PDF)
- Empty state: 3 recommended document cards ("Quick Start", "API Reference", "Hardware Spec")
- Search bar at top of sidebar

## 6. E-STOP Button States

| System State | E-STOP Appearance | Action |
|---|---|---|
| IDLE | Outline: transparent bg, `--danger` text, border 30% opacity | Sends estop command |
| HOMING | Outline (same as IDLE) | Sends estop command |
| RUNNING | Outline (same as IDLE) | Sends estop command |
| JOGGING | Outline (same as IDLE) | Sends estop command |
| STOPPING | Outline, disabled (opacity 0.5) | No action |
| FAULT | Warning outline: `--warning` border/text | Opens reset modal |
| ESTOP | **Solid fill**: `--danger` bg, white text, subtle pulse glow | Opens reset modal |

## 7. Empty State Design

Every empty state follows this pattern:

```
[Icon — 32-40px, text-disabled color]
[Primary message — text-sm, text-secondary]
[Hint/CTA — text-xs, text-tertiary]
```

| Screen | Icon | Message | Hint |
|--------|------|---------|------|
| Alarm History | Bell | No active alarms | System events will appear here |
| Gallery | Image | No captures yet | Use Live & Capture tab to take photos |
| Documentation | FileText | Select a document | Recommended: Quick Start, API Ref, Hardware |
| Motor (no driver) | AlertCircle | No motor drivers detected | Check Connection page for SPI probe status |

## 8. Sprint Plan

### Sprint 1 — Foundation + Shell (3-4 days)

1. Install Tailwind CSS + configure with CSS Variable tokens
2. Create `styles/tokens.css` with all color/typography/spacing tokens
3. Self-host JetBrains Mono woff2
4. Create `lib/cn.ts` (Tailwind class merge utility)
5. Create `lib/format.ts` (unit formatting)
6. Rewrite Header → 3-zone grouped chips layout
7. Rewrite Sidebar → active accent bar, icon spacing
8. Rewrite StatusBadge → token-based
9. Rewrite MotionStatePill → token-based, pill shape
10. Rewrite EStopButton → outline/fill state machine
11. Create EmptyState component
12. Rewrite AlarmBanner → token-based
13. Rewrite ConfirmModal → token-based
14. Rewrite SkeletonLoader → token-based
15. Status expression consistency pass (all screens)
16. Delete `constants.ts`, migrate all references to CSS Variables

**Merge into `feature/motor-test-bench` at Sprint 1 end.**

### Sprint 2 — Oscilloscope + Dashboard (4-5 days)

1. Implement OscilloscopeBuffer (RingBuffer with Float64Array)
2. Unit test OscilloscopeBuffer (push, fillWindow, wrap-around, subarray views)
3. Install uPlot, create Oscilloscope wrapper component
4. Implement OscilloscopeControls (window span, Y-scale, pause/resume)
5. Implement CursorOverlay (dual cursors, delta display)
6. Implement threshold reference line (draggable)
7. Implement CSV/PNG export
8. Create useDiagWs hook (binary WebSocket → buffer pipe)
9. Backend: add MessagePack WebSocket option to diag router
10. Create KpiStrip component
11. Create AxisStatusRow component (channel color bar + name + status)
12. Rewrite DashboardPage (KPI strip + 2x2 grid)
13. Rewrite DiagnosticsPage (oscilloscope main content, toolbar, stats panel, slide-out inspector)
14. Create ChannelLegend component

**Merge into `feature/motor-test-bench` at Sprint 2 end.**

### Sprint 3 — Remaining Pages + Polish (3-4 days)

1. Rewrite MotorPage (channel colors, energize segmented control, inline actions)
2. Rewrite ConnectionPage (left color bar, sparkline, firmware dropzone)
3. Rewrite BendingPage (step indicator checkmarks, wire visual, gauge bars)
4. Rewrite CameraPage (overlay bg, shortcut hints, segmented controls, dirty indicators)
5. Rewrite SettingsPage (permission matrix, high contrast, unit system)
6. Rewrite DocumentationPage (search bar, file icons, recommended docs empty state)
7. Empty state design pass (all screens)
8. SimulationPage: opacity 0.4 + "Coming soon" overlay
9. Final consistency audit (all screens use tokens, no hardcoded colors)

**Merge into `feature/motor-test-bench` at Sprint 3 end.**

## 9. New Dependencies

| Package | Version | Size (gzipped) | Purpose |
|---------|---------|----------------|---------|
| tailwindcss | ^3.4 | dev only | Utility CSS |
| @tailwindcss/forms | ^0.5 | dev only | Form element resets |
| autoprefixer | ^10 | dev only | PostCSS plugin |
| postcss | ^8 | dev only | CSS processing |
| uplot | ^1.6 | ~7KB | StallGuard oscilloscope |
| msgpack-lite or @msgpack/msgpack | ^2 | ~4KB | Binary WebSocket decode |
| clsx | ^2 | <1KB | Class name composition |
| tailwind-merge | ^2 | ~3KB | Tailwind class dedup |

Backend (Python):
| Package | Purpose |
|---------|---------|
| msgpack | Binary WebSocket encoding |

**Total frontend bundle addition: ~15KB gzipped.** Well within the 250KB budget.

## 10. Performance Budget

| Metric | Target | Measurement |
|--------|--------|-------------|
| Initial bundle | < 250KB gzipped | `vite build` output |
| First interaction | < 1.5s | Lighthouse on i.MX8MP |
| StallGuard 60fps | 1kHz input, 60fps render | Chrome DevTools FPS meter |
| StallGuard CPU | < 15% on A53 | Chrome DevTools Performance |
| Memory (1hr) | < 5MB growth | Chrome DevTools Memory |
| X-axis domain jumps | 0 in 1hr | Visual observation |

## 11. Out of Scope

- Simulation page full implementation (placeholder only)
- Mobile responsive layout (workstation environment assumed)
- i18n full translation (structure prepared, content separate track)
- Light theme implementation (token structure supports it, actual theme in future sprint)
- Formal IEC 62366 usability engineering (prototype stage)
- Zustand / TanStack Query migration
- Custom fonts (Inter, Pretendard)
