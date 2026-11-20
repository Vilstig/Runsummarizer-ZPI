import React from 'react';
import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
  CartesianGrid,
} from 'recharts';
import type { LapResponse } from '@/types/api';
import { formatPace, formatPaceSeconds } from '@/utils/formatters';
import { useChartColors } from '@/hooks/useChartColors';
import { cn } from '@/lib/utils';

export interface PaceHrChartProps {
  laps: LapResponse[];
  className?: string;
}

export const PaceHrChart: React.FC<PaceHrChartProps> = ({ laps, className }) => {
  const {
    isDark,
    primaryText,
    cardFill,
    axisStroke,
    tickFill,
    gridStroke,
    tooltipBg,
    tooltipBorder,
  } = useChartColors();

  const chartData = React.useMemo(() => {
    return laps.map((lap, index) => {
      // Speed in m/s -> pace in seconds per km
      const paceSecs =
        lap.speed && lap.speed > 0 ? Math.round(1000 / lap.speed) : null;

      const idx = lap.lapIndex != null ? lap.lapIndex + 1 : index + 1;

      return {
        lapIndex: `L${idx}`,
        lapFull: `Lap ${idx}`,
        paceSecs,
        avgHr: lap.avgHr ? Math.round(lap.avgHr) : null,
        maxHr: lap.maxHr ? Math.round(lap.maxHr) : null,
        speed: lap.speed,
      };
    });
  }, [laps]);

  const hasData = chartData.some((d) => d.paceSecs !== null || d.avgHr !== null);

  if (!hasData) {
    return (
      <div
        role="region"
        aria-label="No lap data available"
        className="flex h-60 items-center justify-center rounded-xl border border-dashed border-border bg-card/40 p-6 text-center text-xs text-muted-foreground"
      >
        No lap pace or heart rate data for this workout.
      </div>
    );
  }

  // Calculate reasonable domain for pace (in seconds)
  const validPaces = chartData
    .map((d) => d.paceSecs)
    .filter((p): p is number => p !== null && p > 120 && p < 900);

  const minPace = validPaces.length ? Math.max(120, Math.min(...validPaces) - 15) : 200;
  const maxPace = validPaces.length ? Math.min(900, Math.max(...validPaces) + 15) : 420;

  return (
    <div
      role="region"
      aria-label="Lap Pace and Heart Rate Dynamics Chart"
      className={cn('rounded-xl border border-border bg-card p-3.5 sm:p-4 shadow-xs', className)}
    >
      <div className="flex items-center justify-between pb-3 border-b border-border mb-3">
        <div>
          <h4 className="text-sm font-semibold text-foreground">
            Lap Pace & Heart Rate
          </h4>
          <p className="text-xs text-muted-foreground">
            Pace per lap (higher = faster) with heart rate
          </p>
        </div>
      </div>

      <div className="h-60 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={chartData}
            margin={{ top: 10, right: 8, left: -4, bottom: 0 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              opacity={isDark ? 0.15 : 0.6}
              stroke={gridStroke}
            />

            <XAxis
              dataKey="lapIndex"
              tick={{ fontSize: 10, fill: tickFill }}
              stroke={axisStroke}
              interval={chartData.length > 15 ? 1 : 0}
            />

            {/* Left Y-axis: Pace (seconds) - Inverted standard: faster on top */}
            <YAxis
              yAxisId="pace"
              domain={[minPace, maxPace]}
              reversed={true}
              tickFormatter={(sec) => formatPaceSeconds(sec, false)}
              tick={{ fontSize: 10, fill: tickFill }}
              stroke={axisStroke}
              width={38}
            />

            {/* Right Y-axis: Heart rate (bpm) */}
            <YAxis
              yAxisId="hr"
              orientation="right"
              domain={['dataMin - 5', 'dataMax + 5']}
              tickFormatter={(bpm) => `${bpm}`}
              tick={{ fontSize: 10, fill: primaryText }}
              stroke={axisStroke}
              width={28}
            />

            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload || !payload.length || !payload[0]?.payload) return null;
                const d = payload[0].payload;
                return (
                  <div
                    style={{ backgroundColor: tooltipBg, borderColor: tooltipBorder }}
                    className="rounded-lg border p-2.5 text-xs shadow-lg space-y-1"
                  >
                    <div className="font-bold text-foreground">{d.lapFull}</div>
                    <div className="text-foreground/90 font-medium">
                      Pace:{' '}
                      <span className="font-semibold text-primary tabular-nums">
                        {formatPace(d.speed)}
                      </span>
                    </div>
                    {d.avgHr && (
                      <div className="text-primary font-medium">
                        Avg HR:{' '}
                        <span className="font-semibold tabular-nums">
                          {d.avgHr} bpm
                        </span>
                      </div>
                    )}
                    {d.maxHr && (
                      <div className="text-muted-foreground">
                        Max HR:{' '}
                        <span className="tabular-nums">{d.maxHr} bpm</span>
                      </div>
                    )}
                  </div>
                );
              }}
            />

            <Legend
              verticalAlign="top"
              height={24}
              formatter={(value) => (
                <span className="text-xs font-medium text-muted-foreground mr-2">
                  {value === 'paceSecs' ? 'Pace (inverted)' : 'Avg HR'}
                </span>
              )}
            />

            {/* Pace represented as smooth Garmin Athletic Cyan curve */}
            <Area
              yAxisId="pace"
              type="monotone"
              dataKey="paceSecs"
              stroke="#00b2ff"
              strokeWidth={2}
              fill="#00b2ff"
              fillOpacity={isDark ? 0.2 : 0.1}
            />

            {/* Heart rate represented as prominent Strava Blaze Orange line */}
            <Line
              yAxisId="hr"
              type="monotone"
              dataKey="avgHr"
              stroke="#fc5200"
              strokeWidth={2.5}
              dot={{ r: 2.5, fill: '#fc5200' }}
              activeDot={{ r: 4.5, fill: cardFill, stroke: '#fc5200', strokeWidth: 2 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
