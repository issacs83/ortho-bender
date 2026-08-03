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
