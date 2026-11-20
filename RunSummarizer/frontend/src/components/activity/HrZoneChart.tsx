import React from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import type { HeartRateZoneResponse } from '@/types/api';
import { formatDuration } from '@/utils/formatters';
import { cn } from '@/lib/utils';
import { useChartColors } from '@/hooks/useChartColors';

export interface HrZoneChartProps {
  zones?: HeartRateZoneResponse[] | null;
  className?: string;
}

/**
 * Garmin 5-Zone Physiological Scale
 * Z1 Recovery (Slate), Z2 Base (Cyan), Z3 Tempo (Green), Z4 Threshold (Orange), Z5 Max (Red)
 */
const ZONE_CONFIG: Record<
  number,
  { name: string; shortName: string; color: string }
> = {
  1: { name: 'Z1 Recovery', shortName: 'Z1', color: '#94a3b8' },
  2: { name: 'Z2 Aerobic', shortName: 'Z2', color: '#00b2ff' },
  3: { name: 'Z3 Tempo', shortName: 'Z3', color: '#10b981' },
  4: { name: 'Z4 Threshold', shortName: 'Z4', color: '#fc5200' },
  5: { name: 'Z5 Max Effort', shortName: 'Z5', color: '#ef4444' },
};

export const HrZoneChart: React.FC<HrZoneChartProps> = ({ zones, className }) => {
  const { tickFill, tooltipBg, tooltipBorder } = useChartColors();

  const data = React.useMemo(() => {
    if (!zones || !Array.isArray(zones)) return [];

    return zones.map((item) => {
      const cfg = ZONE_CONFIG[item.zone] || {
        name: `Zone ${item.zone}`,
        shortName: `Z${item.zone}`,
        color: '#fc5200',
      };

      const bpmRange =
        item.minBpm != null && item.maxBpm != null
          ? `${item.minBpm}–${item.maxBpm} bpm`
          : item.minBpm != null
          ? `>${item.minBpm} bpm`
          : item.maxBpm != null
          ? `<${item.maxBpm} bpm`
          : '';

      return {
        zone: item.zone,
        name: cfg.name,
        shortName: cfg.shortName,
        time: item.time || 0,
        bpmRange,
        color: cfg.color,
      };
    });
  }, [zones]);

  const totalTime = data.reduce((acc, curr) => acc + curr.time, 0);

  if (!zones || zones.length === 0 || totalTime <= 0) {
    return (
      <div
        role="region"
        aria-label="No heart rate zone distribution recorded"
        className="flex h-60 items-center justify-center rounded-xl border border-dashed border-border bg-card/40 p-6 text-center text-xs text-muted-foreground"
      >
        No heart rate zone distribution recorded for this activity.
      </div>
    );
  }

  return (
    <div
      role="region"
      aria-label="Heart Rate Zones Distribution Chart"
      className={cn('rounded-xl border border-border bg-card p-4 sm:p-5 shadow-xs', className)}
    >
      <div className="flex items-center justify-between pb-3 border-b border-border mb-3">
        <div>
          <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            Garmin 5-Zone Gauge
          </span>
          <h4 className="text-sm sm:text-base font-extrabold text-foreground">Heart Rate Zones</h4>
        </div>
        <span className="text-xs tabular-nums font-mono font-bold text-foreground bg-muted px-2.5 py-1 rounded-md">
          {formatDuration(totalTime)}
        </span>
      </div>

      <div className="h-60 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            layout="vertical"
            data={data}
            margin={{ top: 5, right: 20, left: 0, bottom: 5 }}
          >
            <XAxis
              type="number"
              hide
              domain={[0, 'dataMax']}
            />
            <YAxis
              type="category"
              dataKey="shortName"
              axisLine={false}
              tickLine={false}
              tick={{ fontSize: 11, fill: tickFill, fontWeight: 700 }}
              width={35}
            />
            <Tooltip
              cursor={{ fill: 'currentColor', opacity: 0.05 }}
              content={({ active, payload }) => {
                if (active && payload && payload.length > 0 && payload[0]?.payload) {
                  const d = payload[0].payload;
                  const pct = totalTime > 0 ? Math.round((d.time / totalTime) * 100) : 0;
                  return (
                    <div
                      style={{
                        backgroundColor: tooltipBg,
                        borderColor: tooltipBorder,
                      }}
                      className="rounded-lg border p-2.5 text-xs shadow-lg space-y-1"
                    >
                      <div className="flex items-center gap-2">
                        <span
                          className="h-2 w-2 rounded-full"
                          style={{ backgroundColor: d.color }}
                        />
                        <span className="font-bold text-foreground">{d.name}</span>
                      </div>
                      {d.bpmRange && (
                        <p className="text-[11px] text-muted-foreground font-mono">{d.bpmRange}</p>
                      )}
                      <p className="font-mono tabular-nums font-semibold text-foreground">
                        {formatDuration(d.time)} ({pct}%)
                      </p>
                    </div>
                  );
                }
                return null;
              }}
            />
            <Bar
              dataKey="time"
              radius={[0, 4, 4, 0]}
              animationDuration={800}
            >
              {data.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
