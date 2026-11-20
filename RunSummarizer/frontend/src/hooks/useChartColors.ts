import { useTheme } from './useTheme';

export interface ChartColors {
  /** Strava Blaze Orange for active telemetry lines, bars, and markers. */
  primary: string;
  /** High-contrast orange meeting WCAG standards for text. */
  primaryText: string;
  tickFill: string;
  axisStroke: string;
  gridStroke: string;
  cardFill: string;
  foreground: string;
  tooltipBg: string;
  tooltipBorder: string;
}

const DARK: ChartColors = {
  primary: '#fc5200',
  primaryText: '#ff7438',
  tickFill: '#94a3b8',
  axisStroke: '#1e2638',
  gridStroke: '#1e2638',
  cardFill: '#111622',
  foreground: '#f8fafc',
  tooltipBg: '#111622',
  tooltipBorder: '#1e2638',
};

const LIGHT: ChartColors = {
  primary: '#fc5200',
  primaryText: '#fc5200',
  tickFill: '#64748b',
  axisStroke: '#e2e8f0',
  gridStroke: '#e2e8f0',
  cardFill: '#ffffff',
  foreground: '#0f172a',
  tooltipBg: '#ffffff',
  tooltipBorder: '#e2e8f0',
};

/**
 * Theme-aware colors for Recharts, which needs literal values rather than
 * CSS classes. Mirrors the tokens in index.css.
 */
export const useChartColors = (): ChartColors & { isDark: boolean } => {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';
  return { ...(isDark ? DARK : LIGHT), isDark };
};
