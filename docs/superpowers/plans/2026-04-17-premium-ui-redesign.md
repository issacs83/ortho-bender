# Premium UX/UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Ortho-Bender dashboard from inline-style prototype to medical-device-grade HMI with Tailwind CSS, CSS Variable tokens, uPlot oscilloscope, and premium visual polish.

**Architecture:** Branch `ui/premium-redesign` from `feature/motor-test-bench`. All styling migrates from React inline `style={{}}` to Tailwind utility classes driven by CSS Variable design tokens. StallGuard chart replaces Recharts with uPlot + RingBuffer for flicker-free oscilloscope rendering. Three sprints with merge-back after each.

**Tech Stack:** React 18, TypeScript strict, Vite 5, Tailwind CSS 3.4, uPlot 1.6, JetBrains Mono (woff2), MessagePack (binary WS)

**Design Spec:** `docs/superpowers/specs/2026-04-17-premium-ui-redesign-design.md`

---

## File Structure Map

```
src/app/frontend/
├── src/
│   ├── styles/
│   │   ├── tokens.css          # NEW — CSS Variables (colors, typography, spacing)
│   │   └── globals.css         # NEW — Tailwind directives + base + keyframes
│   ├── lib/
│   │   ├── cn.ts               # NEW — clsx + tailwind-merge utility
│   │   └── format.ts           # NEW — unit formatting helpers
│   ├── components/
│   │   ├── ui/
│   │   │   ├── Button.tsx      # NEW — base button (shadcn-style)
│   │   │   ├── Card.tsx        # NEW — base card wrapper
│   │   │   ├── StatusBadge.tsx # REWRITE
│   │   │   ├── MotionStatePill.tsx # REWRITE
│   │   │   ├── EStopButton.tsx # REWRITE
│   │   │   ├── ConfirmModal.tsx # REWRITE
│   │   │   ├── SkeletonLoader.tsx # REWRITE
│   │   │   ├── SliderInput.tsx # REWRITE
│   │   │   ├── EmptyState.tsx  # NEW
│   │   │   ├── ConnectionControl.tsx # REWRITE
│   │   │   └── ConnectionIcon.tsx # REWRITE
│   │   ├── shell/
│   │   │   ├── Header.tsx      # REWRITE (from layout/)
│   │   │   ├── Sidebar.tsx     # REWRITE (from layout/)
│   │   │   └── AlarmBanner.tsx # REWRITE (from layout/)
│   │   ├── charts/
│   │   │   ├── OscilloscopeBuffer.ts   # NEW — RingBuffer (Float64Array)
│   │   │   ├── Oscilloscope.tsx        # NEW — uPlot wrapper
│   │   │   ├── OscilloscopeControls.tsx # NEW
│   │   │   └── CursorOverlay.tsx       # NEW
│   │   └── domain/
│   │       ├── KpiStrip.tsx            # NEW
│   │       ├── AxisStatusRow.tsx       # NEW
│   │       └── ChannelLegend.tsx       # NEW
│   ├── hooks/
│   │   ├── useMotorWs.ts      # KEEP (unchanged)
│   │   ├── useSystemWs.ts     # KEEP (unchanged)
│   │   ├── useCameraWs.ts     # KEEP (unchanged)
│   │   └── useDiagWs.ts       # NEW — binary WS → RingBuffer
│   ├── pages/                  # ALL REWRITE (9 pages)
│   ├── api/client.ts           # MODIFY — add msgpack support
│   ├── App.tsx                 # REWRITE
│   ├── main.tsx                # MODIFY — import globals.css
│   └── constants.ts            # DELETE (replaced by tokens.css)
├── tailwind.config.ts          # NEW
├── postcss.config.js           # NEW
└── package.json                # MODIFY — add deps
```

---

## Sprint 1: Foundation + Shell

### Task 1: Tailwind CSS Installation & Configuration

**Files:**
- Create: `src/app/frontend/tailwind.config.ts`
- Create: `src/app/frontend/postcss.config.js`
- Create: `src/app/frontend/src/styles/tokens.css`
- Create: `src/app/frontend/src/styles/globals.css`
- Modify: `src/app/frontend/src/main.tsx`
- Modify: `src/app/frontend/package.json`
- Modify: `src/app/frontend/index.html`

- [ ] **Step 1: Install dependencies**

```bash
cd src/app/frontend
npm install -D tailwindcss@^3.4 postcss@^8 autoprefixer@^10 @tailwindcss/forms@^0.5
npm install clsx@^2 tailwind-merge@^2
```

- [ ] **Step 2: Create PostCSS config**

Create `src/app/frontend/postcss.config.js`:

```js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 3: Create tokens.css**

Create `src/app/frontend/src/styles/tokens.css`:

```css
:root {
  /* Backgrounds — 3-level depth */
  --bg-canvas:    #0B0E13;
  --bg-surface-1: #131821;
  --bg-surface-2: #1A2030;
  --bg-surface-3: #232B3D;

  /* Borders — opacity-based */
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

  /* Semantic */
  --success:      #4ECB8B;
  --success-soft: rgba(78, 203, 139, 0.12);
  --warning:      #F2B441;
  --warning-soft: rgba(242, 180, 65, 0.12);
  --danger:       #EF5B5B;
  --danger-soft:  rgba(239, 91, 91, 0.12);
  --info:         #5DCFE0;
  --info-soft:    rgba(93, 207, 224, 0.12);

  /* Channel colors — colorblind-safe */
  --ch-feed:   #5B8DEF;
  --ch-bend:   #F2B441;
  --ch-rotate: #C780E8;
  --ch-lift:   #4ECB8B;

  /* Spacing (reference, used in Tailwind config) */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --radius-full: 999px;

  /* Motion */
  --duration-fast: 120ms;
  --duration-default: 200ms;
  --duration-slow: 320ms;
  --ease-default: cubic-bezier(0.4, 0, 0.2, 1);
}
```

- [ ] **Step 4: Create globals.css**

Create `src/app/frontend/src/styles/globals.css`:

```css
@import './tokens.css';

@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  *, *::before, *::after {
    box-sizing: border-box;
  }

  body {
    margin: 0;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg-canvas);
    color: var(--text-primary);
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  /* Scrollbar */
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: var(--bg-canvas); }
  ::-webkit-scrollbar-thumb { background: var(--bg-surface-3); border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--border-strong); }
}

@layer components {
  .numeric {
    font-family: 'JetBrains Mono', ui-monospace, 'Cascadia Code', monospace;
    font-variant-numeric: tabular-nums slashed-zero;
  }

  .inset-highlight {
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
  }
}

@layer utilities {
  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
  @keyframes pulse-glow {
    0%, 100% { box-shadow: 0 0 0 0 rgba(239, 91, 91, 0); }
    50% { box-shadow: 0 0 12px 2px rgba(239, 91, 91, 0.3); }
  }
  @keyframes skeleton-shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
  }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 5: Create Tailwind config**

Create `src/app/frontend/tailwind.config.ts`:

```ts
import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas:      'var(--bg-canvas)',
        surface: {
          1: 'var(--bg-surface-1)',
          2: 'var(--bg-surface-2)',
          3: 'var(--bg-surface-3)',
        },
        border: {
          subtle:  'var(--border-subtle)',
          DEFAULT: 'var(--border-default)',
          strong:  'var(--border-strong)',
        },
        text: {
          primary:   'var(--text-primary)',
          secondary: 'var(--text-secondary)',
          tertiary:  'var(--text-tertiary)',
          disabled:  'var(--text-disabled)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          soft:    'var(--accent-soft)',
        },
        success: {
          DEFAULT: 'var(--success)',
          soft:    'var(--success-soft)',
        },
        warning: {
          DEFAULT: 'var(--warning)',
          soft:    'var(--warning-soft)',
        },
        danger: {
          DEFAULT: 'var(--danger)',
          soft:    'var(--danger-soft)',
        },
        info: {
          DEFAULT: 'var(--info)',
          soft:    'var(--info-soft)',
        },
        ch: {
          feed:   'var(--ch-feed)',
          bend:   'var(--ch-bend)',
          rotate: 'var(--ch-rotate)',
          lift:   'var(--ch-lift)',
        },
      },
      fontFamily: {
        mono: ["'JetBrains Mono'", 'ui-monospace', "'Cascadia Code'", 'monospace'],
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        xl: 'var(--radius-xl)',
        full: 'var(--radius-full)',
      },
      transitionDuration: {
        fast: 'var(--duration-fast)',
        DEFAULT: 'var(--duration-default)',
        slow: 'var(--duration-slow)',
      },
      transitionTimingFunction: {
        DEFAULT: 'var(--ease-default)',
      },
      animation: {
        'spin': 'spin 0.8s linear infinite',
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite',
        'skeleton': 'skeleton-shimmer 1.5s ease-in-out infinite',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms')({ strategy: 'class' }),
  ],
};

export default config;
```

- [ ] **Step 6: Update main.tsx to import globals**

Modify `src/app/frontend/src/main.tsx`:

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/globals.css';
import App from './App';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [ ] **Step 7: Download JetBrains Mono woff2 and add @font-face**

```bash
mkdir -p src/app/frontend/public/fonts
curl -L -o src/app/frontend/public/fonts/jetbrains-mono-v21-latin-regular.woff2 \
  "https://fonts.gstatic.com/s/jetbrainsmono/v21/tDbY2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKxjPVmUsaaDhw.woff2"
curl -L -o src/app/frontend/public/fonts/jetbrains-mono-v21-latin-700.woff2 \
  "https://fonts.gstatic.com/s/jetbrainsmono/v21/tDbY2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKxjDVGUsaaDhw.woff2"
```

Add to `tokens.css` before `:root`:

```css
@font-face {
  font-family: 'JetBrains Mono';
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url('/fonts/jetbrains-mono-v21-latin-regular.woff2') format('woff2');
}
@font-face {
  font-family: 'JetBrains Mono';
  font-style: normal;
  font-weight: 700;
  font-display: swap;
  src: url('/fonts/jetbrains-mono-v21-latin-700.woff2') format('woff2');
}
```

- [ ] **Step 8: Verify build succeeds**

```bash
cd src/app/frontend && npm run build
```

Expected: Build succeeds with Tailwind processing CSS. Output should show CSS file in `dist/assets/`.

- [ ] **Step 9: Commit**

```bash
git add src/app/frontend/tailwind.config.ts src/app/frontend/postcss.config.js \
  src/app/frontend/src/styles/ src/app/frontend/src/main.tsx \
  src/app/frontend/public/fonts/ src/app/frontend/package.json \
  src/app/frontend/package-lock.json
git commit -m "feat: install Tailwind CSS + design tokens + JetBrains Mono"
```

---

### Task 2: Utility Libraries (cn.ts + format.ts)

**Files:**
- Create: `src/app/frontend/src/lib/cn.ts`
- Create: `src/app/frontend/src/lib/format.ts`

- [ ] **Step 1: Create cn.ts**

Create `src/app/frontend/src/lib/cn.ts`:

```ts
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 2: Create format.ts**

Create `src/app/frontend/src/lib/format.ts`:

```ts
export function formatTemp(celsius: number | null | undefined): string {
  if (celsius == null) return 'N/A';
  return `${celsius.toFixed(1)} °C`;
}

export function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${d}d ${h}h ${m}m`;
}

export function formatPosition(value: number, unit: string): string {
  return `${value.toFixed(3)} ${unit}`;
}

export function formatVelocity(value: number): string {
  return value.toFixed(2);
}

export function formatRelativeTime(date: Date): string {
  const diff = Math.floor((Date.now() - date.getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}
```

- [ ] **Step 3: Verify build**

```bash
cd src/app/frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add src/app/frontend/src/lib/
git commit -m "feat: add cn() class merge utility and format helpers"
```

---

### Task 3: Base UI Components (Button + Card)

**Files:**
- Create: `src/app/frontend/src/components/ui/Button.tsx`
- Create: `src/app/frontend/src/components/ui/Card.tsx`

- [ ] **Step 1: Create Button.tsx**

Create `src/app/frontend/src/components/ui/Button.tsx`:

```tsx
import { cn } from '../../lib/cn';
import type { ButtonHTMLAttributes } from 'react';

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';
type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

const variantClasses: Record<ButtonVariant, string> = {
  primary:   'bg-accent text-white hover:opacity-90',
  secondary: 'bg-surface-2 text-text-secondary border border-border hover:bg-surface-3',
  danger:    'bg-danger text-white hover:opacity-90',
  ghost:     'bg-transparent text-text-secondary hover:bg-surface-2',
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: 'px-3 py-1.5 text-[11px]',
  md: 'px-3.5 py-2 text-[13px]',
  lg: 'px-4 py-2.5 text-sm',
};

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  disabled,
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-md font-semibold',
        'transition-[background,opacity] duration-fast',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        variantClasses[variant],
        sizeClasses[size],
        className,
      )}
      {...props}
    >
      {loading && (
        <span className="inline-block w-3.5 h-3.5 border-2 border-current/30 border-t-current rounded-full animate-spin" />
      )}
      {children}
    </button>
  );
}
```

- [ ] **Step 2: Create Card.tsx**

Create `src/app/frontend/src/components/ui/Card.tsx`:

```tsx
import { cn } from '../../lib/cn';
import type { HTMLAttributes } from 'react';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  noPadding?: boolean;
}

export function Card({ className, noPadding, children, ...props }: CardProps) {
  return (
    <div
      className={cn(
        'bg-surface-1 border border-border rounded-lg inset-highlight',
        !noPadding && 'p-4',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardTitle({ className, children, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3 className={cn('text-[13px] font-semibold text-text-primary', className)} {...props}>
      {children}
    </h3>
  );
}
```

- [ ] **Step 3: Verify build**

```bash
cd src/app/frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add src/app/frontend/src/components/ui/Button.tsx src/app/frontend/src/components/ui/Card.tsx
git commit -m "feat: add Button and Card base components (Tailwind)"
```

---

### Task 4: Rewrite StatusBadge + MotionStatePill + EmptyState

**Files:**
- Rewrite: `src/app/frontend/src/components/ui/StatusBadge.tsx`
- Rewrite: `src/app/frontend/src/components/ui/MotionStatePill.tsx`
- Create: `src/app/frontend/src/components/ui/EmptyState.tsx`

- [ ] **Step 1: Rewrite StatusBadge.tsx**

Replace `src/app/frontend/src/components/ui/StatusBadge.tsx`:

```tsx
import { cn } from '../../lib/cn';

export type BadgeVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral';

interface StatusBadgeProps {
  variant: BadgeVariant;
  label: string;
  className?: string;
}

const variantClasses: Record<BadgeVariant, string> = {
  success: 'bg-success-soft text-success',
  warning: 'bg-warning-soft text-warning',
  error:   'bg-danger-soft text-danger',
  info:    'bg-info-soft text-info',
  neutral: 'bg-surface-2 text-text-tertiary border border-border',
};

export function StatusBadge({ variant, label, className }: StatusBadgeProps) {
  return (
    <span className={cn(
      'inline-flex items-center px-2 py-0.5 rounded-sm text-[11px] font-semibold tracking-wide',
      variantClasses[variant],
      className,
    )}>
      {label}
    </span>
  );
}
```

- [ ] **Step 2: Rewrite MotionStatePill.tsx**

Replace `src/app/frontend/src/components/ui/MotionStatePill.tsx`:

```tsx
import { cn } from '../../lib/cn';

const MOTION_STATES: Record<number, { label: string; className: string }> = {
  0: { label: 'IDLE',     className: 'bg-success-soft text-success' },
  1: { label: 'HOMING',   className: 'bg-info-soft text-info' },
  2: { label: 'RUNNING',  className: 'bg-accent-soft text-accent' },
  3: { label: 'JOGGING',  className: 'bg-accent-soft text-accent' },
  4: { label: 'STOPPING', className: 'bg-warning-soft text-warning' },
  5: { label: 'FAULT',    className: 'bg-danger-soft text-danger' },
  6: { label: 'E-STOP',   className: 'bg-danger-soft text-danger' },
};

interface MotionStatePillProps {
  stateNum: number;
  className?: string;
}

export function MotionStatePill({ stateNum, className }: MotionStatePillProps) {
  const state = MOTION_STATES[stateNum] ?? { label: `STATE ${stateNum}`, className: 'bg-surface-2 text-text-tertiary' };
  return (
    <span className={cn(
      'inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold tracking-wide',
      state.className,
      className,
    )}>
      {state.label}
    </span>
  );
}
```

- [ ] **Step 3: Create EmptyState.tsx**

Create `src/app/frontend/src/components/ui/EmptyState.tsx`:

```tsx
import { cn } from '../../lib/cn';
import type { ReactNode } from 'react';

interface EmptyStateProps {
  icon: ReactNode;
  message: string;
  hint?: string;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ icon, message, hint, action, className }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center py-8 text-center', className)}>
      <div className="text-text-disabled mb-3">{icon}</div>
      <p className="text-[13px] text-text-secondary mb-1">{message}</p>
      {hint && <p className="text-[11px] text-text-tertiary">{hint}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
```

- [ ] **Step 4: Verify build**

```bash
cd src/app/frontend && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add src/app/frontend/src/components/ui/StatusBadge.tsx \
  src/app/frontend/src/components/ui/MotionStatePill.tsx \
  src/app/frontend/src/components/ui/EmptyState.tsx
git commit -m "feat: rewrite StatusBadge, MotionStatePill + add EmptyState (Tailwind)"
```

---

### Task 5: Rewrite EStopButton + ConfirmModal + SkeletonLoader

**Files:**
- Rewrite: `src/app/frontend/src/components/ui/EStopButton.tsx`
- Rewrite: `src/app/frontend/src/components/ui/ConfirmModal.tsx`
- Rewrite: `src/app/frontend/src/components/ui/SkeletonLoader.tsx`

- [ ] **Step 1: Rewrite EStopButton.tsx**

Replace `src/app/frontend/src/components/ui/EStopButton.tsx`:

```tsx
import { useState } from 'react';
import { cn } from '../../lib/cn';
import { motorApi } from '../../api/client';
import { ConfirmModal } from './ConfirmModal';

interface EStopButtonProps {
  stateNum: number;
  onAction?: () => void;
}

export function EStopButton({ stateNum, onAction }: EStopButtonProps) {
  const [showResetModal, setShowResetModal] = useState(false);
  const isEstop = stateNum === 6;
  const isFault = stateNum === 5;
  const isStopping = stateNum === 4;

  async function handleEstop() {
    try { await motorApi.estop(); onAction?.(); } catch { /* fire-and-forget */ }
  }

  async function handleReset() {
    try { await motorApi.reset(); onAction?.(); } catch { /* fire-and-forget */ }
  }

  return (
    <>
      <button
        disabled={isStopping}
        onClick={isEstop || isFault ? () => setShowResetModal(true) : handleEstop}
        className={cn(
          'min-w-[80px] h-10 rounded-md font-bold text-[12px] tracking-wider px-3.5 transition-all duration-fast',
          isEstop && 'bg-danger text-white border-2 border-danger animate-pulse-glow',
          isFault && 'bg-transparent text-warning border-[1.5px] border-warning/40',
          !isEstop && !isFault && 'bg-transparent text-danger border-[1.5px] border-danger/30 hover:border-danger/60',
          isStopping && 'opacity-50 cursor-not-allowed',
        )}
      >
        {isEstop ? 'RESET E-STOP' : isFault ? 'RESET FAULT' : 'E-STOP'}
      </button>

      {showResetModal && (
        <ConfirmModal
          title={isEstop ? 'Reset E-Stop' : 'Reset Fault'}
          description={isEstop
            ? 'Are you sure the machine is safe to resume? This will reset the emergency stop condition.'
            : 'This will clear the current fault condition and return to IDLE.'}
          confirmLabel="Reset"
          confirmVariant="danger"
          onConfirm={() => { setShowResetModal(false); handleReset(); }}
          onCancel={() => setShowResetModal(false)}
        />
      )}
    </>
  );
}
```

- [ ] **Step 2: Rewrite ConfirmModal.tsx**

Replace `src/app/frontend/src/components/ui/ConfirmModal.tsx`:

```tsx
import { cn } from '../../lib/cn';
import { Button } from './Button';

interface ConfirmModalProps {
  title: string;
  description: string;
  confirmLabel?: string;
  confirmVariant?: 'primary' | 'danger';
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmModal({
  title, description, confirmLabel = 'Confirm', confirmVariant = 'primary',
  onConfirm, onCancel,
}: ConfirmModalProps) {
  return (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60" onClick={onCancel}>
      <div
        className="bg-surface-1 border border-border rounded-xl p-6 w-[90vw] max-w-[400px] shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-text-primary mb-2">{title}</h3>
        <p className="text-[13px] text-text-secondary mb-6 leading-relaxed">{description}</p>
        <div className="flex gap-3 justify-end">
          <Button variant="ghost" onClick={onCancel}>Cancel</Button>
          <Button variant={confirmVariant === 'danger' ? 'danger' : 'primary'} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Rewrite SkeletonLoader.tsx**

Replace `src/app/frontend/src/components/ui/SkeletonLoader.tsx`:

```tsx
import { cn } from '../../lib/cn';

interface SkeletonLoaderProps {
  lines?: number;
  className?: string;
}

export function SkeletonLoader({ lines = 3, className }: SkeletonLoaderProps) {
  return (
    <div className={cn('flex flex-col gap-3', className)}>
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className="h-4 rounded bg-surface-2 animate-skeleton"
          style={{
            width: i === lines - 1 ? '60%' : '100%',
            backgroundImage: 'linear-gradient(90deg, var(--bg-surface-2) 25%, var(--bg-surface-3) 50%, var(--bg-surface-2) 75%)',
            backgroundSize: '200% 100%',
          }}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Verify build**

```bash
cd src/app/frontend && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add src/app/frontend/src/components/ui/EStopButton.tsx \
  src/app/frontend/src/components/ui/ConfirmModal.tsx \
  src/app/frontend/src/components/ui/SkeletonLoader.tsx
git commit -m "feat: rewrite EStopButton, ConfirmModal, SkeletonLoader (Tailwind)"
```

---

### Task 6: Rewrite SliderInput + ConnectionIcon + ConnectionControl

**Files:**
- Rewrite: `src/app/frontend/src/components/ui/SliderInput.tsx`
- Rewrite: `src/app/frontend/src/components/ui/ConnectionIcon.tsx`
- Rewrite: `src/app/frontend/src/components/ui/ConnectionControl.tsx`

- [ ] **Step 1: Rewrite SliderInput.tsx**

Replace `src/app/frontend/src/components/ui/SliderInput.tsx`:

```tsx
import { cn } from '../../lib/cn';

interface SliderInputProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onChange: (v: number) => void;
  disabled?: boolean;
  className?: string;
}

export function SliderInput({ label, value, min, max, step = 1, unit, onChange, disabled, className }: SliderInputProps) {
  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <div className="flex justify-between items-baseline">
        <label className="text-[11px] text-text-tertiary">{label}</label>
        <span className="numeric text-[13px] text-text-primary">
          {value}{unit && <span className="text-[11px] text-text-tertiary ml-1">{unit}</span>}
        </span>
      </div>
      <input
        type="range"
        min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        disabled={disabled}
        className="w-full h-1 bg-surface-3 rounded-full appearance-none cursor-pointer
          [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5
          [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:cursor-pointer
          disabled:opacity-50 disabled:cursor-not-allowed"
      />
    </div>
  );
}
```

- [ ] **Step 2: Rewrite ConnectionIcon.tsx**

Replace `src/app/frontend/src/components/ui/ConnectionIcon.tsx`:

```tsx
import { cn } from '../../lib/cn';

export type ConnStatus = 'connected' | 'disconnected' | 'connecting';

interface ConnectionIconProps {
  label: string;
  status: ConnStatus;
  detail?: string;
}

const dotClass: Record<ConnStatus, string> = {
  connected:    'bg-success',
  disconnected: 'bg-danger',
  connecting:   'bg-warning animate-pulse',
};

export function ConnectionIcon({ label, status, detail }: ConnectionIconProps) {
  return (
    <div className="flex items-center gap-1.5" title={detail ?? status}>
      <div className={cn('w-1.5 h-1.5 rounded-full', dotClass[status])} />
      <span className="text-[11px] text-text-secondary font-medium">{label}</span>
    </div>
  );
}
```

- [ ] **Step 3: Rewrite ConnectionControl.tsx**

Replace `src/app/frontend/src/components/ui/ConnectionControl.tsx`:

```tsx
import { cn } from '../../lib/cn';
import { Button } from './Button';

interface ConnectionControlProps {
  label: string;
  connected: boolean;
  detail?: string;
  onConnect: () => void;
  onDisconnect: () => void;
  connecting?: boolean;
  className?: string;
}

export function ConnectionControl({
  label, connected, detail, onConnect, onDisconnect, connecting, className,
}: ConnectionControlProps) {
  return (
    <div className={cn('flex items-center justify-between py-2', className)}>
      <div className="flex items-center gap-3">
        <div className={cn(
          'w-2 h-2 rounded-full',
          connected ? 'bg-success' : connecting ? 'bg-warning animate-pulse' : 'bg-danger',
        )} />
        <div>
          <div className="text-[13px] text-text-primary font-medium">{label}</div>
          {detail && <div className="text-[11px] text-text-tertiary">{detail}</div>}
        </div>
      </div>
      <Button
        variant={connected ? 'ghost' : 'primary'}
        size="sm"
        loading={connecting}
        onClick={connected ? onDisconnect : onConnect}
      >
        {connected ? 'Disconnect' : 'Connect'}
      </Button>
    </div>
  );
}
```

- [ ] **Step 4: Verify build**

```bash
cd src/app/frontend && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add src/app/frontend/src/components/ui/SliderInput.tsx \
  src/app/frontend/src/components/ui/ConnectionIcon.tsx \
  src/app/frontend/src/components/ui/ConnectionControl.tsx
git commit -m "feat: rewrite SliderInput, ConnectionIcon, ConnectionControl (Tailwind)"
```

---

### Task 7: Rewrite Shell — Header (3-zone grouped chips)

**Files:**
- Rewrite: `src/app/frontend/src/components/layout/Header.tsx` → move to `src/app/frontend/src/components/shell/Header.tsx`

- [ ] **Step 1: Create shell directory and write Header.tsx**

Create `src/app/frontend/src/components/shell/Header.tsx`:

```tsx
import { Menu, Bell } from 'lucide-react';
import { cn } from '../../lib/cn';
import { MotionStatePill } from '../ui/MotionStatePill';
import { ConnectionIcon, type ConnStatus } from '../ui/ConnectionIcon';
import { EStopButton } from '../ui/EStopButton';

interface HeaderProps {
  onToggleSidebar: () => void;
  motionStateNum: number;
  bdStatus: ConnStatus;
  ipcStatus: ConnStatus;
  motorStatus: ConnStatus;
  motorModel: string | null;
  motorDetail: string;
  camStatus: ConnStatus;
  camModel: string | null;
  alarmCount: number;
  onEstopAction?: () => void;
}

export function Header({
  onToggleSidebar, motionStateNum,
  bdStatus, ipcStatus, motorStatus, motorModel, motorDetail,
  camStatus, camModel, alarmCount, onEstopAction,
}: HeaderProps) {
  return (
    <header className="h-14 bg-surface-1 border-b border-border fixed top-0 left-0 right-0 z-[200] flex items-center px-4 gap-3">
      {/* Left: hamburger + title */}
      <div className="flex items-center gap-2 shrink-0">
        <button onClick={onToggleSidebar} className="p-1 text-text-tertiary hover:text-text-secondary">
          <Menu size={20} />
        </button>
        <span className="text-[15px] font-bold text-text-primary tracking-wide whitespace-nowrap">
          Ortho-Bender
        </span>
      </div>

      {/* Center: 3 groups with separators */}
      <div className="flex-1 flex items-center justify-center gap-4 min-w-0 overflow-hidden">
        {/* Group 1: Motion state */}
        <MotionStatePill stateNum={motionStateNum} />

        {/* Separator */}
        <div className="w-px h-5 bg-border-subtle shrink-0" />

        {/* Group 2: Subsystems */}
        <div className="flex items-center gap-2 shrink overflow-hidden">
          <ConnectionIcon label="SYS" status={bdStatus} />
          <ConnectionIcon label="LINK" status={ipcStatus} />
          <ConnectionIcon label={motorModel ?? 'MTR'} status={motorStatus} detail={motorDetail} />
          <ConnectionIcon label="CAM" status={camStatus} detail={camModel ?? undefined} />
        </div>

        {/* Separator */}
        <div className="w-px h-5 bg-border-subtle shrink-0" />

        {/* Group 3: Alarms */}
        <div className="flex items-center gap-1.5 shrink-0">
          <Bell size={14} className="text-text-tertiary" />
          <span className={cn(
            'text-[11px] font-medium',
            alarmCount > 0 ? 'text-warning' : 'text-text-tertiary',
          )}>
            {alarmCount}
          </span>
        </div>
      </div>

      {/* Right: E-STOP */}
      <div className="shrink-0">
        <EStopButton stateNum={motionStateNum} onAction={onEstopAction} />
      </div>
    </header>
  );
}
```

- [ ] **Step 2: Delete old Header.tsx**

```bash
rm src/app/frontend/src/components/layout/Header.tsx
```

- [ ] **Step 3: Verify build**

```bash
cd src/app/frontend && npm run build
```

Note: Build will fail because App.tsx still imports from old path. This is expected — App.tsx is rewritten in Task 9.

- [ ] **Step 4: Commit**

```bash
git add src/app/frontend/src/components/shell/Header.tsx
git rm src/app/frontend/src/components/layout/Header.tsx
git commit -m "feat: rewrite Header with 3-zone grouped chips layout (Tailwind)"
```

---

### Task 8: Rewrite Shell — Sidebar + AlarmBanner

**Files:**
- Rewrite: `src/app/frontend/src/components/layout/Sidebar.tsx` → move to `src/app/frontend/src/components/shell/Sidebar.tsx`
- Rewrite: `src/app/frontend/src/components/layout/AlarmBanner.tsx` → move to `src/app/frontend/src/components/shell/AlarmBanner.tsx`

- [ ] **Step 1: Create Sidebar.tsx**

Create `src/app/frontend/src/components/shell/Sidebar.tsx`:

```tsx
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
```

- [ ] **Step 2: Create AlarmBanner.tsx**

Create `src/app/frontend/src/components/shell/AlarmBanner.tsx`:

```tsx
import { AlertTriangle } from 'lucide-react';
import type { SystemEvent } from '../../hooks/useSystemWs';

interface AlarmBannerProps {
  activeAlarms: number;
  events: SystemEvent[];
}

export function AlarmBanner({ activeAlarms, events }: AlarmBannerProps) {
  if (activeAlarms === 0 && events.length === 0) return null;

  const latestError = events.find((e) => e.type.includes('error') || e.type.includes('fault'));
  if (!latestError && activeAlarms === 0) return null;

  return (
    <div className="bg-danger-soft border-b border-danger/20 px-4 py-2 flex items-center gap-2">
      <AlertTriangle size={14} className="text-danger shrink-0" />
      <span className="text-[12px] text-danger font-medium truncate">
        {latestError?.message ?? `${activeAlarms} active alarm${activeAlarms > 1 ? 's' : ''}`}
      </span>
    </div>
  );
}
```

- [ ] **Step 3: Delete old layout files**

```bash
rm src/app/frontend/src/components/layout/Sidebar.tsx
rm src/app/frontend/src/components/layout/AlarmBanner.tsx
```

- [ ] **Step 4: Commit**

```bash
git add src/app/frontend/src/components/shell/
git rm src/app/frontend/src/components/layout/Sidebar.tsx \
  src/app/frontend/src/components/layout/AlarmBanner.tsx
git commit -m "feat: rewrite Sidebar (accent bar) + AlarmBanner (Tailwind)"
```

---

### Task 9: Rewrite App.tsx Shell + Delete constants.ts

**Files:**
- Rewrite: `src/app/frontend/src/App.tsx`
- Delete: `src/app/frontend/src/constants.ts`

- [ ] **Step 1: Rewrite App.tsx**

Replace `src/app/frontend/src/App.tsx`:

```tsx
/**
 * App.tsx — Ortho-Bender Dashboard: shell + page routing.
 */

import { useEffect, useState } from 'react';
import { Sidebar } from './components/shell/Sidebar';
import { Header } from './components/shell/Header';
import { AlarmBanner } from './components/shell/AlarmBanner';
import { ConnectionPage }  from './pages/ConnectionPage';
import { DashboardPage }   from './pages/DashboardPage';
import { BendingPage }     from './pages/BendingPage';
import { MotorPage }       from './pages/MotorPage';
import { CameraPage }      from './pages/CameraPage';
import { SimulationPage }  from './pages/SimulationPage';
import { SettingsPage }    from './pages/SettingsPage';
import { DiagnosticsPage } from './pages/DiagnosticsPage';
import { DocumentationPage } from './pages/DocumentationPage';
import { systemApi, type SystemStatus } from './api/client';
import { wsApi } from './api/client';
import type { ConnStatus } from './components/ui/ConnectionIcon';
import type { SystemEvent } from './hooks/useSystemWs';
import { cn } from './lib/cn';

export type Page = 'connection' | 'dashboard' | 'bending' | 'motor' | 'camera' | 'simulation' | 'settings' | 'diagnostics' | 'docs';

export default function App() {
  const [currentPage, setCurrentPage] = useState<Page>('dashboard');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768);
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);
  const [systemEvents, setSystemEvents] = useState<SystemEvent[]>([]);
  const [motionStateNum, setMotionStateNum] = useState(0);

  useEffect(() => {
    function onResize() {
      const mobile = window.innerWidth < 768;
      setIsMobile(mobile);
      if (!mobile) setSidebarOpen(false);
    }
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const boardStatus: ConnStatus = sysStatus ? 'connected' : 'disconnected';
  const ipcStatus: ConnStatus = sysStatus?.ipc_connected ? 'connected' : 'disconnected';
  const motorConnStatus: ConnStatus = sysStatus?.motor_connected ? 'connected' : 'disconnected';
  const driverProbe = sysStatus?.driver_probe ?? {};
  const driverTotal = Object.keys(driverProbe).length;
  const driverConnected = Object.values(driverProbe).filter((d) => d.connected).length;
  const motorDetail = driverTotal > 0 ? `${driverConnected}/${driverTotal}` : 'NO';
  const camStatus: ConnStatus = sysStatus?.camera_connected ? 'connected' : 'disconnected';

  const sidebarWidth = sidebarCollapsed ? 56 : 240;

  useEffect(() => {
    function poll() {
      systemApi.status().then((s) => {
        setSysStatus(s);
        setMotionStateNum(s.motion_state);
      }).catch(() => null);
    }
    poll();
    const id = setInterval(poll, 3000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const ws = wsApi.system((msg) => {
      if (msg.type === 'heartbeat') {
        systemApi.status().then((s) => {
          setSysStatus(s);
          setMotionStateNum(s.motion_state);
        }).catch(() => null);
      } else {
        setSystemEvents((prev) => [msg, ...prev.slice(0, 49)]);
      }
    });
    return () => ws.close();
  }, []);

  function handleNavigate(page: Page) {
    setCurrentPage(page);
    if (isMobile) setSidebarOpen(false);
  }

  function handleEstopAction() {
    systemApi.status().then((s) => {
      setSysStatus(s);
      setMotionStateNum(s.motion_state);
    }).catch(() => null);
  }

  function renderPage() {
    switch (currentPage) {
      case 'connection':  return <ConnectionPage />;
      case 'dashboard':   return <DashboardPage onNavigate={handleNavigate} />;
      case 'bending':     return <BendingPage />;
      case 'motor':       return <MotorPage />;
      case 'camera':      return <CameraPage />;
      case 'simulation':  return <SimulationPage />;
      case 'settings':    return <SettingsPage />;
      case 'diagnostics': return <DiagnosticsPage />;
      case 'docs':        return <DocumentationPage />;
    }
  }

  return (
    <div className="bg-canvas min-h-screen text-text-primary">
      <Header
        onToggleSidebar={() => isMobile ? setSidebarOpen((o) => !o) : setSidebarCollapsed((c) => !c)}
        motionStateNum={motionStateNum}
        bdStatus={boardStatus}
        ipcStatus={ipcStatus}
        motorStatus={motorConnStatus}
        motorModel={sysStatus?.motor_model ?? null}
        motorDetail={motorDetail}
        camStatus={camStatus}
        camModel={sysStatus?.camera_model ?? null}
        alarmCount={sysStatus?.active_alarms ?? 0}
        onEstopAction={handleEstopAction}
      />

      {/* Mobile overlay backdrop */}
      {isMobile && sidebarOpen && (
        <div
          onClick={() => setSidebarOpen(false)}
          className="fixed inset-0 bg-black/50 z-[99] top-14"
        />
      )}

      {(!isMobile || sidebarOpen) && (
        <Sidebar
          currentPage={currentPage}
          onNavigate={handleNavigate}
          collapsed={isMobile ? false : sidebarCollapsed}
          onToggleCollapse={() => isMobile ? setSidebarOpen(false) : setSidebarCollapsed((c) => !c)}
        />
      )}

      <div
        className="mt-14 min-h-[calc(100vh-56px)] flex flex-col transition-[margin-left] duration-default"
        style={{ marginLeft: isMobile ? 0 : sidebarWidth }}
      >
        <AlarmBanner activeAlarms={sysStatus?.active_alarms ?? 0} events={systemEvents} />
        <div className="flex-1 overflow-y-auto">
          {renderPage()}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Delete constants.ts**

```bash
rm src/app/frontend/src/constants.ts
```

Note: This will cause build errors in all page files that import from constants.ts. Pages still use old inline styles and will be rewritten in Tasks 10-18. For now, create a minimal shim:

Create `src/app/frontend/src/constants.ts` (temporary shim — will be deleted when all pages are migrated):

```ts
/**
 * DEPRECATED — Use CSS Variables from styles/tokens.css instead.
 * This file exists only as a migration shim. Remove after all pages are rewritten.
 */

export const BG_PRIMARY = '#0B0E13';
export const BG_PANEL = '#131821';
export const BG_SIDEBAR = '#131821';
export const BORDER = 'rgba(255,255,255,0.10)';
export const TEXT_PRIMARY = '#ECEFF4';
export const TEXT_SECONDARY = '#B4BCCC';
export const TEXT_MUTED = '#7A8499';
export const COLOR_SUCCESS = '#4ECB8B';
export const COLOR_SUCCESS_BG = 'rgba(78,203,139,0.12)';
export const COLOR_WARNING = '#F2B441';
export const COLOR_WARNING_BG = 'rgba(242,180,65,0.12)';
export const COLOR_ERROR = '#EF5B5B';
export const COLOR_ERROR_BG = 'rgba(239,91,91,0.12)';
export const COLOR_INFO = '#5DCFE0';
export const COLOR_INFO_BG = 'rgba(93,207,224,0.12)';

export const AXIS_COLORS = ['#5B8DEF', '#F2B441', '#C780E8', '#4ECB8B'] as const;
export const AXIS_NAMES = ['FEED', 'BEND', 'ROTATE', 'LIFT'] as const;
export const AXIS_UNITS = ['mm', '°', '°', '°'] as const;

export const MOTION_STATE_LABELS: Record<number, string> = {
  0: 'IDLE', 1: 'HOMING', 2: 'RUNNING', 3: 'JOGGING', 4: 'STOPPING', 5: 'FAULT', 6: 'ESTOP',
};

export interface WireMaterial {
  id: number; name: string; springback: string; heating: string; speed: string; maxAngle: number;
}
export const WIRE_MATERIALS: WireMaterial[] = [
  { id: 0, name: 'NiTi', springback: 'High (superelastic)', heating: 'Required (Af temp)', speed: '5 mm/s', maxAngle: 90 },
  { id: 1, name: 'SS304', springback: 'Moderate', heating: 'None', speed: '10 mm/s', maxAngle: 90 },
  { id: 2, name: 'Beta-Ti', springback: 'Low-moderate', heating: 'None', speed: '8 mm/s', maxAngle: 90 },
  { id: 3, name: 'CuNiTi', springback: 'High (temp-dep)', heating: 'Thermally activated', speed: '5 mm/s', maxAngle: 85 },
];
export const WIRE_DIAMETERS = [0.356, 0.406, 0.457, 0.508] as const;
export const HISTORY_LEN = 60;
```

- [ ] **Step 3: Remove old layout/ directory if empty**

```bash
rmdir src/app/frontend/src/components/layout/ 2>/dev/null || true
```

- [ ] **Step 4: Verify build**

```bash
cd src/app/frontend && npm run build
```

Expected: Build succeeds. Shell is fully Tailwind. Pages still use shim constants.

- [ ] **Step 5: Commit**

```bash
git add src/app/frontend/src/App.tsx src/app/frontend/src/constants.ts
git commit -m "feat: rewrite App.tsx shell (Tailwind) + deprecate constants.ts as migration shim"
```

---

### Task 10: Rewrite DashboardPage (KPI Strip + 2x2 Grid)

**Files:**
- Rewrite: `src/app/frontend/src/pages/DashboardPage.tsx`
- Create: `src/app/frontend/src/components/domain/KpiStrip.tsx`
- Create: `src/app/frontend/src/components/domain/AxisStatusRow.tsx`

- [ ] **Step 1: Create KpiStrip.tsx**

Create `src/app/frontend/src/components/domain/KpiStrip.tsx`:

```tsx
import { cn } from '../../lib/cn';
import { Card } from '../ui/Card';
import { formatTemp, formatUptime } from '../../lib/format';

interface KpiStripProps {
  cpuTemp: number | null;
  uptimeS: number;
  bendCycles: number;
  lastRun: string | null;
}

export function KpiStrip({ cpuTemp, uptimeS, bendCycles, lastRun }: KpiStripProps) {
  const items = [
    { label: 'CPU TEMP', value: cpuTemp != null ? cpuTemp.toFixed(1) : 'N/A', unit: '°C' },
    { label: 'UPTIME', value: formatUptime(uptimeS), unit: null },
    { label: 'BEND CYCLES', value: String(bendCycles), unit: null },
    { label: 'LAST RUN', value: lastRun ?? '—', unit: null },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {items.map((item) => (
        <Card key={item.label} className="px-4 py-3">
          <div className="text-[10px] text-text-tertiary uppercase tracking-widest mb-1">{item.label}</div>
          <div className="numeric text-2xl font-bold text-text-primary">
            {item.value}
            {item.unit && <span className="text-[12px] text-text-tertiary ml-1">{item.unit}</span>}
          </div>
        </Card>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create AxisStatusRow.tsx**

Create `src/app/frontend/src/components/domain/AxisStatusRow.tsx`:

```tsx
import { cn } from '../../lib/cn';
import { StatusBadge } from '../ui/StatusBadge';

const CHANNEL_CLASSES = ['bg-ch-feed', 'bg-ch-bend', 'bg-ch-rotate', 'bg-ch-lift'] as const;
const CHANNEL_TEXT    = ['text-ch-feed', 'text-ch-bend', 'text-ch-rotate', 'text-ch-lift'] as const;
const AXIS_NAMES = ['FEED', 'BEND', 'ROTATE', 'LIFT'] as const;
const AXIS_UNITS = ['mm', '°', '°', '°'] as const;

interface AxisStatusRowProps {
  axis: number;
  position?: number;
  velocity?: number;
  drvStatus?: number;
  connected: boolean;
}

export function AxisStatusRow({ axis, position, velocity, drvStatus, connected }: AxisStatusRowProps) {
  return (
    <div className={cn('flex items-center gap-2', !connected && 'opacity-50')}>
      <div className={cn('w-[3px] h-4 rounded-sm', CHANNEL_CLASSES[axis])} />
      <span className={cn('text-[12px] font-semibold w-14', CHANNEL_TEXT[axis])}>{AXIS_NAMES[axis]}</span>
      <span className="numeric text-[12px] text-text-primary flex-1">
        {connected ? `${position?.toFixed(3)} ${AXIS_UNITS[axis]}` : `— ${AXIS_UNITS[axis]}`}
      </span>
      <span className="numeric text-[12px] text-text-primary w-16 text-right">
        {connected ? velocity?.toFixed(2) : '—'}
      </span>
      <div className="w-20 text-right">
        {connected
          ? <StatusBadge variant={drvStatus === 0 ? 'success' : 'error'} label={drvStatus === 0 ? 'Normal' : 'Fault'} />
          : <StatusBadge variant="neutral" label="No Driver" />
        }
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Rewrite DashboardPage.tsx**

Replace `src/app/frontend/src/pages/DashboardPage.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Bell } from 'lucide-react';
import { motorApi, systemApi, type MotorStatus, type SystemStatus } from '../api/client';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ConfirmModal } from '../components/ui/ConfirmModal';
import { SkeletonLoader } from '../components/ui/SkeletonLoader';
import { EmptyState } from '../components/ui/EmptyState';
import { Button } from '../components/ui/Button';
import { Card, CardTitle } from '../components/ui/Card';
import { KpiStrip } from '../components/domain/KpiStrip';
import { AxisStatusRow } from '../components/domain/AxisStatusRow';
import { useMotorWs } from '../hooks/useMotorWs';
import { useSystemWs, type SystemEvent } from '../hooks/useSystemWs';
import type { Page } from '../App';

interface DashboardPageProps {
  onNavigate: (page: Page) => void;
}

function getSeverity(type: string): 'error' | 'warning' | 'info' {
  if (type.includes('error') || type.includes('fault')) return 'error';
  if (type.includes('warn')) return 'warning';
  return 'info';
}

export function DashboardPage({ onNavigate }: DashboardPageProps) {
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);
  const [staticMotor, setStaticMotor] = useState<MotorStatus | null>(null);
  const [motorError, setMotorError] = useState(false);
  const [showHomeModal, setShowHomeModal] = useState(false);
  const [showSystemCheckModal, setShowSystemCheckModal] = useState(false);
  const [loadingAction, setLoadingAction] = useState<string | null>(null);

  const liveMotor = useMotorWs();
  const systemEvents = useSystemWs();
  const motorStatus = liveMotor ?? staticMotor;

  useEffect(() => {
    function pollSys() { systemApi.status().then(setSysStatus).catch(() => null); }
    function pollMotor() {
      motorApi.status().then((s) => { setStaticMotor(s); setMotorError(false); })
        .catch(() => setMotorError(true));
    }
    pollSys(); pollMotor();
    const sysId = setInterval(pollSys, 3000);
    const motId = setInterval(pollMotor, 2000);
    return () => { clearInterval(sysId); clearInterval(motId); };
  }, []);

  async function homeAll() {
    setLoadingAction('home');
    try { await motorApi.home(0); } catch { /* ignore */ }
    finally { setLoadingAction(null); setShowHomeModal(false); }
  }

  async function resetFault() {
    setLoadingAction('reset');
    try { await motorApi.reset(); } catch { /* ignore */ }
    finally { setLoadingAction(null); }
  }

  const isFault = (motorStatus?.state ?? 0) === 5;
  const motorConnected = sysStatus?.motor_connected ?? false;

  return (
    <div className="p-4 max-w-[1100px] mx-auto">
      <h2 className="text-lg font-semibold text-text-primary mb-4">Dashboard</h2>

      {/* KPI Strip */}
      <div className="mb-4">
        {sysStatus ? (
          <KpiStrip
            cpuTemp={sysStatus.cpu_temp_c}
            uptimeS={sysStatus.uptime_s}
            bendCycles={0}
            lastRun={null}
          />
        ) : (
          <SkeletonLoader lines={2} />
        )}
      </div>

      {/* 2x2 Card Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

        {/* System Health */}
        <Card>
          <div className="flex justify-between items-center mb-3">
            <CardTitle>System Health</CardTitle>
            {sysStatus && (
              <span className="text-[11px] text-success font-medium">
                {sysStatus.ipc_connected && sysStatus.camera_connected ? 'All nominal' : 'Issues detected'}
              </span>
            )}
          </div>
          {!sysStatus ? <SkeletonLoader lines={4} /> : (
            <div className="flex flex-col gap-2.5">
              <div className="flex gap-1.5 flex-wrap">
                <StatusBadge variant={sysStatus.ipc_connected ? 'success' : 'error'} label="LINK" />
                <StatusBadge variant={sysStatus.m7_heartbeat_ok ? 'success' : 'error'} label="Controller" />
                <StatusBadge variant={sysStatus.camera_connected ? 'success' : 'error'} label="CAM" />
              </div>
              {sysStatus.driver_probe && Object.keys(sysStatus.driver_probe).length > 0 && (
                <div>
                  <span className="text-[11px] text-text-tertiary block mb-1">Motor Drivers</span>
                  <div className="flex gap-1.5 flex-wrap">
                    {Object.values(sysStatus.driver_probe).map((dp) => (
                      <StatusBadge
                        key={dp.driver}
                        variant={dp.connected ? 'success' : 'error'}
                        label={dp.connected ? dp.chip : dp.driver}
                      />
                    ))}
                  </div>
                </div>
              )}
              <div className="text-[11px] text-text-tertiary">SDK {sysStatus.sdk_version}</div>
            </div>
          )}
        </Card>

        {/* Motor Readiness */}
        <Card>
          <div className="flex justify-between items-center mb-3">
            <CardTitle>Motor Readiness</CardTitle>
            {motorConnected
              ? <span className="text-[11px] text-success font-medium">Online</span>
              : <span className="text-[11px] text-warning font-medium">Offline</span>
            }
          </div>
          {!motorStatus && !motorError ? <SkeletonLoader lines={4} /> : (
            <div className="flex flex-col gap-1.5">
              {motorConnected && motorStatus ? (
                motorStatus.axes.map((ax) => (
                  <AxisStatusRow
                    key={ax.axis}
                    axis={ax.axis}
                    position={ax.position}
                    velocity={ax.velocity}
                    drvStatus={ax.drv_status}
                    connected
                  />
                ))
              ) : (
                [0, 1, 2, 3].map((i) => (
                  <AxisStatusRow key={i} axis={i} connected={false} />
                ))
              )}
            </div>
          )}
        </Card>

        {/* Quick Actions */}
        <Card>
          <CardTitle className="mb-3">Quick Actions</CardTitle>
          <div className="grid grid-cols-2 gap-2">
            <Button variant="primary" onClick={() => onNavigate('bending')}>
              Start Bending
            </Button>
            <Button
              variant="secondary"
              loading={loadingAction === 'home'}
              onClick={() => setShowHomeModal(true)}
            >
              Home All
            </Button>
            <Button variant="secondary" onClick={() => onNavigate('camera')}>
              Camera
            </Button>
            <Button
              variant="secondary"
              disabled={!isFault}
              loading={loadingAction === 'reset'}
              onClick={resetFault}
              className={isFault ? 'bg-warning-soft text-warning border-warning/30' : ''}
            >
              Reset Fault
            </Button>
            <Button
              variant="secondary"
              className="col-span-2"
              onClick={() => setShowSystemCheckModal(true)}
            >
              System Check
            </Button>
          </div>
        </Card>

        {/* Alarm History */}
        <Card>
          <div className="flex justify-between items-center mb-3">
            <CardTitle>Alarm History</CardTitle>
            <button className="text-[11px] text-text-tertiary hover:text-text-secondary">View All</button>
          </div>
          {systemEvents.length === 0 ? (
            <EmptyState
              icon={<Bell size={32} />}
              message="No active alarms"
              hint="System events will appear here"
            />
          ) : (
            <div className="flex flex-col gap-1.5 max-h-[200px] overflow-y-auto">
              {systemEvents.slice(0, 10).map((ev, i) => (
                <div key={i} className="flex items-start gap-2 p-1.5 bg-canvas rounded">
                  <StatusBadge variant={getSeverity(ev.type)} label={getSeverity(ev.type).toUpperCase()} />
                  <span className="text-[12px] text-text-secondary flex-1">{ev.message}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {showHomeModal && (
        <ConfirmModal
          title="Home All Axes"
          description="This will move all axes to their home positions. Ensure no wire is loaded."
          confirmLabel="Home All"
          onConfirm={homeAll}
          onCancel={() => setShowHomeModal(false)}
        />
      )}
      {showSystemCheckModal && (
        <ConfirmModal
          title="System Check"
          description="Running connection check to all subsystems..."
          confirmLabel="OK"
          onConfirm={() => { setShowSystemCheckModal(false); systemApi.status().then(setSysStatus).catch(() => null); }}
          onCancel={() => setShowSystemCheckModal(false)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Verify build and test in browser**

```bash
cd src/app/frontend && npm run build
```

Start dev server: `npm run dev` — open in browser, verify Dashboard renders with new design.

- [ ] **Step 5: Commit**

```bash
git add src/app/frontend/src/pages/DashboardPage.tsx \
  src/app/frontend/src/components/domain/KpiStrip.tsx \
  src/app/frontend/src/components/domain/AxisStatusRow.tsx
git commit -m "feat: rewrite DashboardPage with KPI strip + 2x2 card grid (Tailwind)"
```

---

**Sprint 1 continues with Tasks 11-16 (remaining pages). Due to plan size limits, these follow the same pattern as Task 10 — each page is a self-contained rewrite importing from the new component library. The remaining Sprint 1 tasks are:**

### Task 11: Rewrite SettingsPage
### Task 12: Rewrite SimulationPage (placeholder)
### Task 13: Sprint 1 — Remove constants.ts shim + final audit

After Task 13, all components and the shell use Tailwind. Pages not yet rewritten (Connection, Motor, Bending, Camera, Diagnostics, Documentation) continue using the deprecated constants shim until Sprint 3.

**Sprint 1 merge point: merge `ui/premium-redesign` → `feature/motor-test-bench`.**

---

## Sprint 2: Oscilloscope + Diagnostics

### Task 14: OscilloscopeBuffer (RingBuffer with Float64Array)

**Files:**
- Create: `src/app/frontend/src/components/charts/OscilloscopeBuffer.ts`
- Create: `src/app/frontend/src/components/charts/__tests__/OscilloscopeBuffer.test.ts`

- [ ] **Step 1: Write failing tests**

Create `src/app/frontend/src/components/charts/__tests__/OscilloscopeBuffer.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { OscilloscopeBuffer } from '../OscilloscopeBuffer';

describe('OscilloscopeBuffer', () => {
  it('starts empty', () => {
    const buf = new OscilloscopeBuffer(100, 2);
    const [xs, y0, y1] = buf.fillWindow(10, 10);
    expect(xs.length).toBe(0);
    expect(y0.length).toBe(0);
    expect(y1.length).toBe(0);
  });

  it('stores pushed data', () => {
    const buf = new OscilloscopeBuffer(100, 2);
    buf.push(1.0, [100, 200]);
    buf.push(2.0, [150, 250]);
    const [xs, y0, y1] = buf.fillWindow(3, 5);
    expect(xs.length).toBe(2);
    expect(xs[0]).toBe(1.0);
    expect(xs[1]).toBe(2.0);
    expect(y0[0]).toBe(100);
    expect(y1[1]).toBe(250);
  });

  it('wraps around at capacity', () => {
    const buf = new OscilloscopeBuffer(5, 1);
    for (let i = 0; i < 8; i++) buf.push(i, [i * 10]);
    // Should contain timestamps 3,4,5,6,7 (last 5)
    const [xs, y0] = buf.fillWindow(10, 20);
    expect(xs.length).toBe(5);
    expect(xs[0]).toBe(3);
    expect(xs[4]).toBe(7);
    expect(y0[0]).toBe(30);
    expect(y0[4]).toBe(70);
  });

  it('windows correctly', () => {
    const buf = new OscilloscopeBuffer(100, 1);
    for (let i = 0; i < 50; i++) buf.push(i, [i]);
    // Window: now=49, span=10 → timestamps 39..49
    const [xs] = buf.fillWindow(49, 10);
    expect(xs.length).toBe(10);
    expect(xs[0]).toBe(40);
    expect(xs[9]).toBe(49);
  });

  it('returns subarray views (zero copy)', () => {
    const buf = new OscilloscopeBuffer(100, 1);
    buf.push(1, [10]);
    buf.push(2, [20]);
    const result1 = buf.fillWindow(3, 5);
    const result2 = buf.fillWindow(3, 5);
    // Should reuse same underlying buffer
    expect(result1[0].buffer).toBe(result2[0].buffer);
  });
});
```

- [ ] **Step 2: Install vitest and run tests to verify they fail**

```bash
cd src/app/frontend && npm install -D vitest
npx vitest run src/components/charts/__tests__/OscilloscopeBuffer.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement OscilloscopeBuffer**

Create `src/app/frontend/src/components/charts/OscilloscopeBuffer.ts`:

```ts
export class OscilloscopeBuffer {
  private xs: Float64Array;
  private ys: Float64Array[];
  private writeIdx = 0;
  private filled = 0;
  private displayXs: Float64Array;
  private displayYs: Float64Array[];

  constructor(public readonly capacity: number, channels: number) {
    this.xs = new Float64Array(capacity);
    this.ys = Array.from({ length: channels }, () => new Float64Array(capacity));
    this.displayXs = new Float64Array(capacity);
    this.displayYs = Array.from({ length: channels }, () => new Float64Array(capacity));
  }

  push(t: number, values: number[]): void {
    this.xs[this.writeIdx] = t;
    for (let c = 0; c < this.ys.length; c++) {
      this.ys[c][this.writeIdx] = values[c] ?? 0;
    }
    this.writeIdx = (this.writeIdx + 1) % this.capacity;
    if (this.filled < this.capacity) this.filled++;
  }

  fillWindow(now: number, span: number): readonly Float64Array[] {
    const cutoff = now - span;
    let outIdx = 0;
    const start = this.filled < this.capacity ? 0 : this.writeIdx;

    for (let i = 0; i < this.filled; i++) {
      const idx = (start + i) % this.capacity;
      if (this.xs[idx] >= cutoff) {
        this.displayXs[outIdx] = this.xs[idx];
        for (let c = 0; c < this.ys.length; c++) {
          this.displayYs[c][outIdx] = this.ys[c][idx];
        }
        outIdx++;
      }
    }

    return [
      this.displayXs.subarray(0, outIdx),
      ...this.displayYs.map((y) => y.subarray(0, outIdx)),
    ];
  }

  clear(): void {
    this.writeIdx = 0;
    this.filled = 0;
  }

  get length(): number {
    return this.filled;
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd src/app/frontend && npx vitest run src/components/charts/__tests__/OscilloscopeBuffer.test.ts
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/frontend/src/components/charts/OscilloscopeBuffer.ts \
  src/app/frontend/src/components/charts/__tests__/
git commit -m "feat: add OscilloscopeBuffer RingBuffer with zero-copy Float64Array"
```

---

### Task 15: uPlot Oscilloscope Wrapper

**Files:**
- Create: `src/app/frontend/src/components/charts/Oscilloscope.tsx`
- Create: `src/app/frontend/src/components/charts/OscilloscopeControls.tsx`
- Create: `src/app/frontend/src/components/domain/ChannelLegend.tsx`

- [ ] **Step 1: Install uPlot**

```bash
cd src/app/frontend && npm install uplot@^1.6
```

- [ ] **Step 2: Create Oscilloscope.tsx**

Create `src/app/frontend/src/components/charts/Oscilloscope.tsx`:

```tsx
import { useEffect, useRef } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import type { OscilloscopeBuffer } from './OscilloscopeBuffer';

interface OscilloscopeProps {
  buffer: OscilloscopeBuffer;
  windowSpan: number;
  yMin?: number;
  yMax?: number;
  yAuto?: boolean;
  channels: { label: string; color: string; visible: boolean }[];
  threshold?: number;
  paused?: boolean;
  height?: number;
}

export function Oscilloscope({
  buffer, windowSpan, yMin = 0, yMax = 1023, yAuto = false,
  channels, threshold, paused = false, height = 480,
}: OscilloscopeProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const uplotRef = useRef<uPlot | null>(null);
  const rafRef = useRef<number>();
  const pausedRef = useRef(paused);

  pausedRef.current = paused;

  useEffect(() => {
    if (!containerRef.current) return;

    const series: uPlot.Series[] = [
      { label: 'Time' },
      ...channels.map((ch) => ({
        label: ch.label,
        stroke: ch.color,
        width: 1.5,
        points: { show: false },
        show: ch.visible,
      })),
    ];

    const opts: uPlot.Options = {
      width: containerRef.current.clientWidth,
      height,
      pxAlign: false,
      cursor: { drag: { x: false, y: false } },
      scales: {
        x: {
          time: false,
          range: () => {
            const now = performance.now() / 1000;
            return [now - windowSpan, now];
          },
        },
        y: yAuto ? {} : { range: [yMin, yMax] },
      },
      axes: [
        {
          stroke: '#7A8499',
          grid: { stroke: 'rgba(255,255,255,0.06)', width: 1 },
          ticks: { stroke: 'rgba(255,255,255,0.06)', width: 1 },
          font: '11px system-ui',
          values: (_, ticks) => ticks.map((t) => {
            const rel = t - performance.now() / 1000;
            return `${rel.toFixed(0)}s`;
          }),
        },
        {
          stroke: '#7A8499',
          grid: { stroke: 'rgba(255,255,255,0.06)', width: 1 },
          ticks: { stroke: 'rgba(255,255,255,0.06)', width: 1 },
          font: '11px system-ui',
        },
      ],
      series,
      plugins: threshold != null ? [thresholdPlugin(threshold)] : [],
    };

    const initData = buffer.fillWindow(performance.now() / 1000, windowSpan);
    uplotRef.current = new uPlot(opts, initData as uPlot.AlignedData, containerRef.current);

    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && uplotRef.current) uplotRef.current.setSize({ width: w, height });
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      uplotRef.current?.destroy();
      uplotRef.current = null;
    };
  }, [height]);

  // Update channel visibility
  useEffect(() => {
    if (!uplotRef.current) return;
    channels.forEach((ch, i) => {
      uplotRef.current!.setSeries(i + 1, { show: ch.visible });
    });
  }, [channels]);

  // Animation loop
  useEffect(() => {
    const tick = () => {
      if (!pausedRef.current && uplotRef.current) {
        const now = performance.now() / 1000;
        const data = buffer.fillWindow(now, windowSpan);
        uplotRef.current.setData(data as uPlot.AlignedData, false);
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [windowSpan]);

  return <div ref={containerRef} className="w-full" />;
}

function thresholdPlugin(threshold: number): uPlot.Plugin {
  return {
    hooks: {
      draw: [(u: uPlot) => {
        const ctx = u.ctx;
        const y = u.valToPos(threshold, 'y', true);
        ctx.save();
        ctx.strokeStyle = 'var(--danger)';
        ctx.lineWidth = 1;
        ctx.setLineDash([5, 5]);
        ctx.beginPath();
        ctx.moveTo(u.bbox.left, y);
        ctx.lineTo(u.bbox.left + u.bbox.width, y);
        ctx.stroke();
        ctx.restore();
      }],
    },
  };
}
```

- [ ] **Step 3: Create OscilloscopeControls.tsx**

Create `src/app/frontend/src/components/charts/OscilloscopeControls.tsx`:

```tsx
import { Pause, Play, Trash2, Download } from 'lucide-react';
import { Button } from '../ui/Button';
import { cn } from '../../lib/cn';

interface OscilloscopeControlsProps {
  windowSpan: number;
  onWindowSpanChange: (s: number) => void;
  yMode: 'auto' | 'manual';
  onYModeChange: (m: 'auto' | 'manual') => void;
  paused: boolean;
  onTogglePause: () => void;
  onClear: () => void;
  onExportCsv?: () => void;
  onExportPng?: () => void;
}

const WINDOW_OPTIONS = [5, 10, 30, 60, 300];

export function OscilloscopeControls({
  windowSpan, onWindowSpanChange, yMode, onYModeChange,
  paused, onTogglePause, onClear, onExportCsv, onExportPng,
}: OscilloscopeControlsProps) {
  return (
    <div className="flex items-center gap-3 flex-wrap">
      {/* Window span */}
      <div className="flex items-center gap-1">
        <span className="text-[11px] text-text-tertiary mr-1">Window</span>
        {WINDOW_OPTIONS.map((s) => (
          <button
            key={s}
            onClick={() => onWindowSpanChange(s)}
            className={cn(
              'px-2 py-1 rounded text-[11px] font-medium transition-colors duration-fast',
              windowSpan === s
                ? 'bg-accent-soft text-accent'
                : 'text-text-tertiary hover:text-text-secondary hover:bg-surface-2',
            )}
          >
            {s < 60 ? `${s}s` : `${s / 60}m`}
          </button>
        ))}
      </div>

      {/* Y-scale */}
      <div className="flex items-center gap-1">
        <span className="text-[11px] text-text-tertiary mr-1">Y-Scale</span>
        {(['auto', 'manual'] as const).map((m) => (
          <button
            key={m}
            onClick={() => onYModeChange(m)}
            className={cn(
              'px-2 py-1 rounded text-[11px] font-medium capitalize transition-colors duration-fast',
              yMode === m
                ? 'bg-accent-soft text-accent'
                : 'text-text-tertiary hover:text-text-secondary hover:bg-surface-2',
            )}
          >
            {m}
          </button>
        ))}
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Actions */}
      <Button variant="ghost" size="sm" onClick={onTogglePause}>
        {paused ? <Play size={14} /> : <Pause size={14} />}
        {paused ? 'Resume' : 'Pause'}
      </Button>
      <Button variant="ghost" size="sm" onClick={onClear}>
        <Trash2 size={14} /> Clear
      </Button>
      {onExportCsv && (
        <Button variant="ghost" size="sm" onClick={onExportCsv}>
          <Download size={14} /> CSV
        </Button>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Create ChannelLegend.tsx**

Create `src/app/frontend/src/components/domain/ChannelLegend.tsx`:

```tsx
import { cn } from '../../lib/cn';

interface Channel {
  label: string;
  color: string;
  visible: boolean;
  value?: number;
}

interface ChannelLegendProps {
  channels: Channel[];
  onToggle: (index: number) => void;
}

export function ChannelLegend({ channels, onToggle }: ChannelLegendProps) {
  return (
    <div className="flex items-center gap-3 flex-wrap">
      {channels.map((ch, i) => (
        <button
          key={ch.label}
          onClick={() => onToggle(i)}
          className={cn(
            'flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-medium transition-opacity',
            ch.visible ? 'opacity-100' : 'opacity-40',
          )}
        >
          <div className="w-2.5 h-2.5 rounded-sm" style={{ background: ch.color }} />
          <span className="text-text-secondary">{ch.label}</span>
          {ch.value != null && (
            <span className="numeric text-text-primary ml-1">{ch.value}</span>
          )}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Verify build**

```bash
cd src/app/frontend && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add src/app/frontend/src/components/charts/Oscilloscope.tsx \
  src/app/frontend/src/components/charts/OscilloscopeControls.tsx \
  src/app/frontend/src/components/domain/ChannelLegend.tsx \
  src/app/frontend/package.json src/app/frontend/package-lock.json
git commit -m "feat: add uPlot Oscilloscope wrapper + controls + channel legend"
```

---

### Task 16: useDiagWs Hook (Binary WebSocket → Buffer)

**Files:**
- Create: `src/app/frontend/src/hooks/useDiagWs.ts`

- [ ] **Step 1: Create useDiagWs.ts**

Create `src/app/frontend/src/hooks/useDiagWs.ts`:

```ts
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
  }, [enabled, channelKeys.join(',')]);
}
```

- [ ] **Step 2: Commit**

```bash
git add src/app/frontend/src/hooks/useDiagWs.ts
git commit -m "feat: add useDiagWs hook for binary WS → OscilloscopeBuffer pipe"
```

---

### Task 17: Rewrite DiagnosticsPage (Oscilloscope Main Content)

**Files:**
- Rewrite: `src/app/frontend/src/pages/DiagnosticsPage.tsx`
- Delete: `src/app/frontend/src/components/StallGuardChart.tsx`

- [ ] **Step 1: Rewrite DiagnosticsPage.tsx**

Replace `src/app/frontend/src/pages/DiagnosticsPage.tsx` with the oscilloscope as main content, toolbar for SPI/Register/Dump, channel legend with live values, and slide-out register inspector. Full implementation uses `OscilloscopeBuffer`, `Oscilloscope`, `OscilloscopeControls`, `ChannelLegend`, `useDiagWs`, `Card`, `Button`, `StatusBadge`, `EmptyState`, and `RegisterInspector`.

The page structure:
- Toolbar: SPI Test button, Register Inspector toggle, Register Dump button
- Oscilloscope: full width, 480px height
- Controls: window span, Y-scale, pause/resume, clear, export
- Channel legend: per-channel toggle with live SG value
- Stats panel: current / avg / peak per channel
- Slide-out RegisterInspector panel (right side, 360px)

*(Full code: ~300 lines — follows the same Tailwind pattern as DashboardPage. Uses `useState` for channel visibility, window span, Y-mode, pause state. Creates `OscilloscopeBuffer(3600, 4)` in a `useRef`. Connects via `useDiagWs`.)*

- [ ] **Step 2: Delete old StallGuardChart.tsx**

```bash
rm src/app/frontend/src/components/StallGuardChart.tsx
```

- [ ] **Step 3: Verify build and test in browser**

```bash
cd src/app/frontend && npm run build && npm run dev
```

Open Diagnostics page — verify oscilloscope renders with fixed X-axis window, no flicker.

- [ ] **Step 4: Commit**

```bash
git add src/app/frontend/src/pages/DiagnosticsPage.tsx
git rm src/app/frontend/src/components/StallGuardChart.tsx
git commit -m "feat: rewrite DiagnosticsPage with uPlot oscilloscope (Tailwind)"
```

---

**Sprint 2 continues with Task 18 (Backend MessagePack for diag WebSocket) — adds `msgpack` to Python backend and binary frame option to the diag router. Sprint 2 merge point after Task 18.**

---

## Sprint 3: Remaining Pages + Polish

### Task 19: Rewrite ConnectionPage
### Task 20: Rewrite MotorPage
### Task 21: Rewrite BendingPage
### Task 22: Rewrite CameraPage
### Task 23: Rewrite DocumentationPage
### Task 24: Rewrite SettingsPage + SimulationPage
### Task 25: Delete constants.ts shim + SystemStatus.tsx + CameraView.tsx + MotorControl.tsx
### Task 26: Final consistency audit + build verification

**Tasks 19-24** follow the identical pattern as Task 10 (DashboardPage):
1. Replace inline styles with Tailwind classes
2. Import from new component library (Card, Button, StatusBadge, EmptyState, etc.)
3. Use CSS Variable tokens (no hardcoded hex values)
4. Use `.numeric` class for all data values
5. Build and verify in browser
6. Commit

**Task 25** removes:
- `src/app/frontend/src/constants.ts` (the migration shim — all imports should be gone)
- `src/app/frontend/src/components/SystemStatus.tsx` (absorbed into DashboardPage)
- `src/app/frontend/src/components/CameraView.tsx` (absorbed into CameraPage)
- `src/app/frontend/src/components/MotorControl.tsx` (absorbed into MotorPage)

**Task 26** runs:
1. `grep -rn '#[0-9a-fA-F]\{6\}' src/` — must find 0 hardcoded hex colors
2. `grep -rn "style={{" src/` — should find 0 (or minimal inline styles for dynamic values only)
3. `npm run build` — must succeed with no errors
4. Visual walkthrough of all 9 pages in browser
5. Final commit and merge `ui/premium-redesign` → `feature/motor-test-bench`

---

## Summary

| Sprint | Tasks | Key Deliverables |
|--------|-------|-----------------|
| 1 | 1-13 | Tailwind setup, tokens, all UI components, Header/Sidebar/Shell, DashboardPage |
| 2 | 14-18 | RingBuffer, uPlot oscilloscope, useDiagWs, DiagnosticsPage, MessagePack WS |
| 3 | 19-26 | All remaining pages, cleanup, consistency audit |

**Total: 26 tasks, ~10-13 working days.**
