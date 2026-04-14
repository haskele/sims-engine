/**
 * Format a number as currency (USD)
 */
export function formatCurrency(value, decimals = 0) {
  if (value == null || isNaN(value)) return '--';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

/**
 * Format a number as a percentage
 */
export function formatPercent(value, decimals = 1) {
  if (value == null || isNaN(value)) return '--';
  return `${(value * 100).toFixed(decimals)}%`;
}

/**
 * Format a percentage already in 0-100 form
 */
export function formatPct(value, decimals = 1) {
  if (value == null || isNaN(value)) return '--';
  return `${Number(value).toFixed(decimals)}%`;
}

/**
 * Format a decimal number
 */
export function formatDecimal(value, decimals = 1) {
  if (value == null || isNaN(value)) return '--';
  return Number(value).toFixed(decimals);
}

/**
 * Format DFS salary (e.g., $5,400)
 */
export function formatSalary(value) {
  if (value == null || isNaN(value)) return '--';
  return `$${Number(value).toLocaleString()}`;
}

/**
 * Format a large number compactly (e.g., 1.2K, 45K, 1.5M)
 */
export function formatCompact(value) {
  if (value == null || isNaN(value)) return '--';
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}K`;
  return value.toString();
}

/**
 * Format time as HH:MM AM/PM
 */
export function formatTime(dateStr) {
  if (!dateStr) return '--';
  const d = new Date(dateStr);
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

/**
 * Format a signed number with + prefix for positive
 */
export function formatSigned(value, decimals = 1) {
  if (value == null || isNaN(value)) return '--';
  const num = Number(value).toFixed(decimals);
  return value > 0 ? `+${num}` : num;
}
