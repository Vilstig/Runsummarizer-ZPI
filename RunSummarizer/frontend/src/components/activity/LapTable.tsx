import React, { useState } from 'react';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Check, Edit3, RotateCcw } from 'lucide-react';
import type { LapResponse } from '@/types/api';
import { LapType, LAP_TYPE_DISPLAY } from '@/types/enums';
import { LAP_TYPE_COLORS } from '@/utils/colors';
import {
  formatDistance,
  formatDuration,
  formatElevation,
  formatHeartRate,
  formatPace,
} from '@/utils/formatters';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { cn } from '@/lib/utils';

const lapFormSchema = z.object({
  laps: z.array(
    z.object({
      lapIndex: z.number(),
      typeId: z.nativeEnum(LapType),
    })
  ),
});

type LapFormValues = z.infer<typeof lapFormSchema>;

export interface LapTableProps {
  laps: LapResponse[];
  onSave?: (updatedLaps: { lapIndex: number; typeId: LapType }[]) => void;
  onReset?: () => void;
  isSaving?: boolean;
  isResetting?: boolean;
  editable?: boolean;
}

export const LapTable: React.FC<LapTableProps> = ({
  laps,
  onSave,
  onReset,
  isSaving = false,
  isResetting = false,
  editable = true,
}) => {
  const [isEditing, setIsEditing] = useState(false);

  const defaultValues: LapFormValues = React.useMemo(() => {
    return {
      laps: laps.map((lap, index) => ({
        lapIndex: lap.lapIndex != null ? lap.lapIndex : index,
        typeId: lap.typeId != null ? (lap.typeId as LapType) : LapType.RUN,
      })),
    };
  }, [laps]);

  const {
    control,
    handleSubmit,
    reset,
    formState: { isDirty },
  } = useForm<LapFormValues>({
    resolver: zodResolver(lapFormSchema),
    defaultValues,
  });

  React.useEffect(() => {
    reset(defaultValues);
  }, [defaultValues, reset]);

  const onSubmit = (data: LapFormValues) => {
    if (onSave) {
      onSave(data.laps);
    }
    setIsEditing(false);
  };

  const cancelEdit = () => {
    reset(defaultValues);
    setIsEditing(false);
  };

  const hasEditedLaps = laps.some((l) => l.version > 0);

  if (!laps || laps.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border bg-card p-8 text-center text-sm text-muted-foreground">
        No lap splits recorded for this workout.
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      {editable && (
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="text-xs text-muted-foreground">
            {isEditing
              ? 'Select lap classifications below and click Save to regenerate the workout summary.'
              : 'Classify reps, recovery intervals, or rest laps to improve automated workout insights.'}
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {hasEditedLaps && onReset && !isEditing && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={onReset}
                disabled={isResetting}
                className="min-h-[44px] sm:min-h-[32px] text-xs text-muted-foreground rounded-md border-border hover:border-[#FC5200]"
              >
                <RotateCcw className="h-3.5 w-3.5 mr-1" />
                {isResetting ? 'Resetting...' : 'Reset to Original Laps'}
              </Button>
            )}

            {!isEditing ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setIsEditing(true)}
                className="min-h-[44px] sm:min-h-[32px] text-xs rounded-md border-border hover:border-[#FC5200] hover:bg-muted font-semibold"
              >
                <Edit3 className="h-3.5 w-3.5 mr-1 text-[#FC5200]" />
                Edit Lap Types
              </Button>
            ) : (
              <>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={cancelEdit}
                  disabled={isSaving}
                  className="min-h-[44px] sm:min-h-[32px] text-xs rounded-sm border-border"
                >
                  <RotateCcw className="h-3.5 w-3.5 mr-1" />
                  Cancel
                </Button>
                <Button
                  type="submit"
                  size="sm"
                  disabled={isSaving || !isDirty}
                  className="min-h-[44px] sm:min-h-[32px] text-xs rounded-sm font-semibold"
                >
                  {isSaving ? (
                    <LoadingSpinner size="sm" className="p-0 mr-1" />
                  ) : (
                    <Check className="h-3.5 w-3.5 mr-1" />
                  )}
                  Save & Regenerate
                </Button>
              </>
            )}
          </div>
        </div>
      )}

      {/* MOBILE VIEW (360px–430px screens): Responsive Lap Cards with Tabular Numerals */}
      <div className="space-y-2 md:hidden">
        {laps.map((lap, index) => {
          const currentTypeId = lap.typeId != null ? lap.typeId : LapType.RUN;
          const typeColor =
            LAP_TYPE_COLORS[currentTypeId as LapType] || LAP_TYPE_COLORS[LapType.RUN];

          return (
            <div
              key={lap.lapIndex ?? index}
              className="rounded-md border border-border bg-card p-3 shadow-xs space-y-2"
            >
              {/* Header row: Lap #, Edited badge, and current Type */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-md bg-muted text-xs tabular-nums font-bold text-foreground">
                    #{index + 1}
                  </span>
                  {lap.version > 0 && (
                    <span className="text-xs font-semibold text-amber-700 dark:text-amber-400 bg-amber-400/10 px-1.5 py-0.5 rounded border border-amber-400/20">
                      Edited
                    </span>
                  )}
                </div>

                {!isEditing ? (
                  <span
                    className={cn(
                      'inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 text-xs font-semibold border',
                      typeColor.bg,
                      typeColor.text,
                      typeColor.border
                    )}
                  >
                    <span className={cn('h-1.5 w-1.5 rounded-full', typeColor.dot)} />
                    {lap.typeDisplay || LAP_TYPE_DISPLAY[currentTypeId as LapType] || 'Run'}
                  </span>
                ) : null}
              </div>

              {/* In Edit mode on mobile: Touch-friendly Chip Selector (≥ 44px) */}
              {isEditing ? (
                <div className="pt-1 pb-1">
                  <Controller
                    control={control}
                    name={`laps.${index}.typeId`}
                    render={({ field }) => (
                      <div className="grid grid-cols-3 gap-1.5">
                        {[LapType.RUN, LapType.RECOVERY, LapType.REST].map((type) => {
                          const isSelected = field.value === type;
                          const chipColor = LAP_TYPE_COLORS[type];
                          return (
                            <button
                              key={type}
                              type="button"
                              aria-pressed={isSelected}
                              aria-label={`Lap ${index + 1} type: ${LAP_TYPE_DISPLAY[type]}`}
                              onClick={() => field.onChange(type)}
                              className={cn(
                                'flex min-h-[44px] items-center justify-center rounded-sm border text-xs font-medium transition-all duration-150 ease-out active:scale-95 cursor-pointer select-none',
                                isSelected
                                  ? `${chipColor.bg} ${chipColor.text} ${chipColor.border} font-bold ring-1 ring-[#FC5200]`
                                  : 'border-border bg-muted/60 text-muted-foreground hover:bg-muted'
                              )}
                            >
                              <span
                                className={cn('h-1.5 w-1.5 rounded-full mr-1.5', chipColor.dot)}
                              />
                              {LAP_TYPE_DISPLAY[type]}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  />
                </div>
              ) : null}

              {/* Metrics grid with tabular numerals */}
              <div className="grid grid-cols-4 gap-2 pt-1 border-t border-border text-xs">
                <div>
                  <span className="text-xs uppercase font-semibold text-muted-foreground block">
                    Dist
                  </span>
                  <span className="font-bold tabular-nums text-foreground">
                    {formatDistance(lap.distance)}
                  </span>
                </div>

                <div>
                  <span className="text-xs uppercase font-semibold text-muted-foreground block">
                    Pace
                  </span>
                  <span className="font-semibold tabular-nums text-primary">
                    {formatPace(lap.speed)}
                  </span>
                </div>

                <div>
                  <span className="text-xs uppercase font-semibold text-muted-foreground block">
                    Time
                  </span>
                  <span className="tabular-nums text-muted-foreground">
                    {formatDuration(lap.duration)}
                  </span>
                </div>

                <div>
                  <span className="text-xs uppercase font-semibold text-muted-foreground block">
                    Avg HR
                  </span>
                  <span className="font-medium tabular-nums text-foreground">
                    {lap.avgHr ? `${Math.round(lap.avgHr)}` : '--'}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* DESKTOP VIEW (md:): Clean, Full-fidelity Data Table with tabular-nums */}
      <div className="hidden md:block overflow-x-auto rounded-xl border border-border bg-card shadow-xs">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-muted/60 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            <tr>
              <th scope="col" className="px-4 py-3 text-center w-12">
                #
              </th>
              <th scope="col" className="px-4 py-3 min-w-[140px]">
                Type
              </th>
              <th scope="col" className="px-4 py-3">
                Distance
              </th>
              <th scope="col" className="px-4 py-3">
                Time
              </th>
              <th scope="col" className="px-4 py-3">
                Pace
              </th>
              <th scope="col" className="px-4 py-3">
                Avg HR
              </th>
              <th scope="col" className="px-4 py-3">
                Max HR
              </th>
              <th scope="col" className="px-4 py-3 text-right">
                Elevation
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {laps.map((lap, index) => {
              const currentTypeId = lap.typeId != null ? lap.typeId : LapType.RUN;
              const typeColor =
                LAP_TYPE_COLORS[currentTypeId as LapType] || LAP_TYPE_COLORS[LapType.RUN];

              return (
                <tr
                  key={lap.lapIndex ?? index}
                  className="transition-colors hover:bg-muted/40"
                >
                  <td className="px-4 py-3 text-center text-xs tabular-nums text-muted-foreground">
                    <span className="inline-flex items-center gap-1">
                      {index + 1}
                      {lap.version > 0 && (
                        <span className="h-1.5 w-1.5 rounded-full bg-[#F59E0B]" title="Edited" />
                      )}
                    </span>
                  </td>

                  <td className="px-4 py-3">
                    {isEditing ? (
                      <Controller
                        control={control}
                        name={`laps.${index}.typeId`}
                        render={({ field }) => (
                          <Select
                            value={String(field.value)}
                            onValueChange={(val) => field.onChange(Number(val))}
                          >
                            <SelectTrigger className="h-8 text-xs min-w-[120px] rounded-sm">
                              <SelectValue placeholder="Select type" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value={String(LapType.RUN)}>
                                {LAP_TYPE_DISPLAY[LapType.RUN]}
                              </SelectItem>
                              <SelectItem value={String(LapType.RECOVERY)}>
                                {LAP_TYPE_DISPLAY[LapType.RECOVERY]}
                              </SelectItem>
                              <SelectItem value={String(LapType.REST)}>
                                {LAP_TYPE_DISPLAY[LapType.REST]}
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        )}
                      />
                    ) : (
                      <span
                        className={cn(
                          'inline-flex items-center gap-1.5 rounded-sm px-2.5 py-0.5 text-xs font-semibold border',
                          typeColor.bg,
                          typeColor.text,
                          typeColor.border
                        )}
                      >
                        <span className={cn('h-1.5 w-1.5 rounded-full', typeColor.dot)} />
                        {lap.typeDisplay ||
                          LAP_TYPE_DISPLAY[currentTypeId as LapType] ||
                          'Run'}
                      </span>
                    )}
                  </td>

                  <td className="px-4 py-3 font-medium tabular-nums">
                    {formatDistance(lap.distance)}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground tabular-nums text-xs">
                    {formatDuration(lap.duration)}
                  </td>
                  <td className="px-4 py-3 font-semibold tabular-nums text-primary">
                    {formatPace(lap.speed)}
                  </td>
                  <td className="px-4 py-3 text-foreground font-medium tabular-nums">
                    {formatHeartRate(lap.avgHr)}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground tabular-nums">
                    {formatHeartRate(lap.maxHr)}
                  </td>
                  <td className="px-4 py-3 text-right text-xs text-muted-foreground tabular-nums">
                    {formatElevation(lap.elevationGain)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </form>
  );
};