import React from 'react';
import { RunType, RUN_TYPE_DISPLAY } from '@/types/enums';
import { DEFAULT_RUN_TYPE_COLOR, RUN_TYPE_COLORS } from '@/utils/colors';
import { cn } from '@/lib/utils';

export interface RunTypeBadgeProps {
  typeId?: number | null;
  typeName?: string | null;
  className?: string;
  size?: 'sm' | 'md';
}

export const RunTypeBadge: React.FC<RunTypeBadgeProps> = ({
  typeId,
  typeName,
  className,
  size = 'sm',
}) => {
  const colors =
    typeId != null && typeId in RUN_TYPE_COLORS
      ? RUN_TYPE_COLORS[typeId] ?? DEFAULT_RUN_TYPE_COLOR
      : DEFAULT_RUN_TYPE_COLOR;

  const display =
    typeId != null && typeId in RUN_TYPE_DISPLAY
      ? RUN_TYPE_DISPLAY[typeId as RunType]
      : typeName || 'Unclassified';

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-sm border font-semibold select-none tracking-tight transition-all duration-150',
        colors.bg,
        colors.text,
        colors.border,
        size === 'sm' ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs',
        className
      )}
    >
      <span className={cn('h-1.5 w-1.5 rounded-full shrink-0', colors.dot)} />
      {display}
    </span>
  );
};