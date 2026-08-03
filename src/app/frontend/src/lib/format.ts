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
