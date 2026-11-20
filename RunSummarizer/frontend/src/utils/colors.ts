import { LapType, RunType, SegmentRole } from '@/types/enums';

export interface ColorScheme {
  bg: string;
  text: string;
  border: string;
  dot: string;
}

/**
 * Disciplined 60-30-10 Athletic Palette
 * Monochromatic high-contrast base for standard telemetry and categories.
 * Strava Orange (#FC5200) strictly reserved for key work intervals and race efforts.
 */
const NEUTRAL_BADGE: ColorScheme = {
  bg: 'bg-muted/80 text-foreground',
  text: 'text-foreground font-semibold',
  border: 'border-border',
  dot: 'bg-muted-foreground',
};

const ACCENT_ORANGE_BADGE: ColorScheme = {
  bg: 'bg-[#FC5200]/10 text-[#FC5200] dark:text-[#FF7438]',
  text: 'text-[#FC5200] dark:text-[#FF7438] font-bold',
  border: 'border-[#FC5200]/30',
  dot: 'bg-[#FC5200]',
};

export const RUN_TYPE_COLORS: Record<number, ColorScheme> = {
  [RunType.EASY]: NEUTRAL_BADGE,
  [RunType.TEMPO]: NEUTRAL_BADGE,
  [RunType.SHORT_INTERVALS]: NEUTRAL_BADGE,
  [RunType.TIME_INTERVALS]: NEUTRAL_BADGE,
  [RunType.PROGRESSION_RUN]: NEUTRAL_BADGE,
  [RunType.LONG_INTERVALS]: ACCENT_ORANGE_BADGE,
  [RunType.RACE]: ACCENT_ORANGE_BADGE,
};

export const DEFAULT_RUN_TYPE_COLOR: ColorScheme = NEUTRAL_BADGE;

export const LAP_TYPE_COLORS: Record<LapType, ColorScheme> = {
  [LapType.RUN]: ACCENT_ORANGE_BADGE,
  [LapType.RECOVERY]: {
    bg: 'bg-muted/60 text-muted-foreground',
    text: 'text-muted-foreground font-medium',
    border: 'border-border',
    dot: 'bg-muted-foreground/60',
  },
  [LapType.REST]: {
    bg: 'bg-muted/40 text-muted-foreground',
    text: 'text-muted-foreground font-normal',
    border: 'border-border',
    dot: 'bg-muted-foreground/40',
  },
};

export const SEGMENT_ROLE_COLORS: Record<SegmentRole, ColorScheme> = {
  [SegmentRole.WORK]: ACCENT_ORANGE_BADGE,
  [SegmentRole.PREAMBLE]: {
    bg: 'bg-muted/60 text-muted-foreground',
    text: 'text-muted-foreground font-medium',
    border: 'border-border',
    dot: 'bg-muted-foreground/60',
  },
  [SegmentRole.EPILOGUE]: {
    bg: 'bg-muted/60 text-muted-foreground',
    text: 'text-muted-foreground font-medium',
    border: 'border-border',
    dot: 'bg-muted-foreground/60',
  },
  [SegmentRole.BREAK]: {
    bg: 'bg-muted/40 text-muted-foreground',
    text: 'text-muted-foreground font-normal',
    border: 'border-border',
    dot: 'bg-muted-foreground/40',
  },
};
