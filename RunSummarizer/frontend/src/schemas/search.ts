import { z } from 'zod';
import { addDays, format, parseISO, subMonths } from 'date-fns';
import { Provider, RunType, RUN_TYPE_DISPLAY } from '@/types/enums';
import type {
  ActivitySearchFilters,
  ActivitySort,
  NumberRange,
  SegmentCriteria,
} from '@/types/api';
import { formatDate } from '@/utils/formatters';
import { PROVIDER_DISPLAY } from '@/utils/providers';

/**
 * Activity search form: every input is kept as typed (a string) and parsed once,
 * by `buildSearchFilters`, which both validates the form and builds the request body.
 */

const rangeSchema = z.object({ min: z.string(), max: z.string() });

export type RangeValues = z.infer<typeof rangeSchema>;

export const PERIOD_OPTIONS = [
  { value: '1m', label: 'Last month', months: 1 },
  { value: '3m', label: 'Last 3 months', months: 3 },
  { value: '6m', label: 'Last 6 months', months: 6 },
  { value: 'all', label: 'Whole history', months: null },
  { value: 'custom', label: 'Custom dates', months: null },
] as const;

export type Period = (typeof PERIOD_OPTIONS)[number]['value'];

const PERIOD_VALUES = PERIOD_OPTIONS.map((option) => option.value) as [Period, ...Period[]];

const searchFormObject = z.object({
  period: z.enum(PERIOD_VALUES),
  after: z.string(), // 'custom' period only: first day included, yyyy-MM-dd
  to: z.string(), // 'custom' period only: last day included, yyyy-MM-dd
  source: z.enum(['all', Provider.STRAVA, Provider.GARMIN, Provider.INTERVALS]),
  trainingType: z.string(), // 'all' or a RunType id
  distance: rangeSchema, // km
  duration: rangeSchema, // [h:]mm:ss
  pace: rangeSchema, // m:ss per km
  avgHr: rangeSchema, // bpm
  details: z.object({
    distance: rangeSchema,
    duration: rangeSchema,
    pace: rangeSchema,
    avgHr: rangeSchema,
    repCount: rangeSchema,
    repDistance: z.string(), // m
    repTolerance: z.string(), // %
    avgRepDuration: rangeSchema,
    avgRecovery: rangeSchema,
  }),
});

export type SearchFormValues = z.infer<typeof searchFormObject>;
export type DetailValues = SearchFormValues['details'];

export const ALL = 'all';
const DEFAULT_REP_TOLERANCE = '5';

const emptyRange = (): RangeValues => ({ min: '', max: '' });

export const emptyDetails = (): DetailValues => ({
  distance: emptyRange(),
  duration: emptyRange(),
  pace: emptyRange(),
  avgHr: emptyRange(),
  repCount: emptyRange(),
  repDistance: '',
  repTolerance: DEFAULT_REP_TOLERANCE,
  avgRepDuration: emptyRange(),
  avgRecovery: emptyRange(),
});

export const defaultSearchValues = (): SearchFormValues => ({
  period: ALL,
  after: '',
  to: '',
  source: ALL,
  trainingType: ALL,
  distance: emptyRange(),
  duration: emptyRange(),
  pace: emptyRange(),
  avgHr: emptyRange(),
  details: emptyDetails(),
});

// ---------------------------------------------------------------------------
// Fields
// ---------------------------------------------------------------------------

export type RangeKind = 'km' | 'duration' | 'pace' | 'bpm' | 'count';

export interface RangeFieldMeta {
  label: string;
  kind: RangeKind;
  examples: [string, string]; // valid min and max inputs, shown as placeholders
  unit?: string; // shown instead of the kind's unit
}

export type ActivityRangeField = 'distance' | 'duration' | 'pace' | 'avgHr';
export type DetailRangeField =
  | ActivityRangeField
  | 'repCount'
  | 'avgRepDuration'
  | 'avgRecovery';
export type DetailField = DetailRangeField | 'repDistance';

export const ACTIVITY_RANGE_FIELDS: Record<ActivityRangeField, RangeFieldMeta> = {
  distance: { label: 'Distance', kind: 'km', examples: ['5', '21.1'] },
  duration: {
    label: 'Duration',
    kind: 'duration',
    examples: ['30:00', '1:30:00'],
    unit: 'h:mm:ss',
  },
  pace: { label: 'Pace', kind: 'pace', examples: ['3:30', '5:30'] },
  avgHr: { label: 'Avg HR', kind: 'bpm', examples: ['130', '165'] },
};

export const DETAIL_RANGE_FIELDS: Record<DetailRangeField, RangeFieldMeta> = {
  ...ACTIVITY_RANGE_FIELDS,
  distance: { label: 'Distance', kind: 'km', examples: ['3', '10'] },
  duration: {
    label: 'Duration',
    kind: 'duration',
    examples: ['10:00', '45:00'],
    unit: 'h:mm:ss',
  },
  repCount: { label: 'Reps', kind: 'count', examples: ['4', '10'], unit: '' },
  avgRepDuration: { label: 'Avg rep time', kind: 'duration', examples: ['1:00', '4:00'] },
  avgRecovery: { label: 'Avg recovery', kind: 'duration', examples: ['0:45', '2:00'] },
};

/** The segment figures the backend stores for each run type, in form order. */
export const DETAIL_FIELDS: Record<RunType, readonly DetailField[]> = {
  [RunType.EASY]: ['distance', 'duration', 'pace', 'avgHr'],
  [RunType.SHORT_INTERVALS]: ['repDistance', 'repCount', 'pace', 'avgRepDuration', 'avgRecovery'],
  [RunType.LONG_INTERVALS]: ['distance', 'duration', 'pace'],
  [RunType.TEMPO]: ['distance', 'duration', 'pace', 'avgHr'],
  [RunType.RACE]: ['distance', 'duration', 'pace', 'avgHr'],
  [RunType.TIME_INTERVALS]: ['avgRepDuration', 'repCount', 'repDistance', 'pace', 'avgRecovery'],
  [RunType.PROGRESSION_RUN]: ['distance', 'duration', 'pace', 'avgHr'],
};

/** Race distances the backend snaps races to, km. */
export const RACE_PRESETS: { label: string; km: string }[] = [
  { label: '5K', km: '5' },
  { label: '10K', km: '10' },
  { label: 'Half', km: '21.1' },
  { label: 'Marathon', km: '42.2' },
];

export const RUN_TYPE_OPTIONS = (Object.values(RunType).filter(
  (value) => typeof value === 'number'
) as RunType[]).map((runType) => ({
  value: String(runType),
  label: RUN_TYPE_DISPLAY[runType],
}));

export const selectedRunType = (values: SearchFormValues): RunType | null => {
  if (!WHOLE.test(values.trainingType)) return null;
  const id = Number(values.trainingType);
  return id in RUN_TYPE_DISPLAY ? (id as RunType) : null;
};

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------

const DECIMAL = /^\d+([.,]\d+)?$/;
const WHOLE = /^\d+$/;
const CLOCK = /^(?:(\d+):)?(\d+):([0-5]\d)$/;

const parseDecimal = (raw: string): number | null =>
  DECIMAL.test(raw) ? Number(raw.replace(',', '.')) : null;

const parseWhole = (raw: string): number | null => (WHOLE.test(raw) ? Number(raw) : null);

/** Seconds from 'm:ss' or 'h:mm:ss'; null when malformed. */
export const parseClock = (raw: string): number | null => {
  const match = CLOCK.exec(raw);
  if (!match) return null;
  const [, hours, minutes, seconds] = match;
  if (hours !== undefined && Number(minutes) > 59) return null;
  return Number(hours ?? 0) * 3600 + Number(minutes) * 60 + Number(seconds);
};

interface KindSpec {
  unit: string;
  parse: (raw: string) => number | null; // the API value: m, s, s/km, bpm or a count
  invalid: string;
  ends: [string, string];
  order: string;
  inputMode: 'decimal' | 'numeric' | 'text';
}

export const KIND_SPECS: Record<RangeKind, KindSpec> = {
  km: {
    unit: 'km',
    parse: (raw) => {
      const km = parseDecimal(raw);
      return km === null ? null : Math.round(km * 1000);
    },
    invalid: 'Enter a distance in km, like 10.5',
    ends: ['Min', 'Max'],
    order: "Min can't be more than max",
    inputMode: 'decimal',
  },
  duration: {
    unit: 'm:ss',
    parse: parseClock,
    invalid: 'Use m:ss or h:mm:ss, like 45:00',
    ends: ['Min', 'Max'],
    order: "Min can't be more than max",
    inputMode: 'text',
  },
  pace: {
    unit: 'min/km',
    parse: (raw) => {
      const seconds = parseClock(raw);
      return seconds === null || seconds === 0 ? null : seconds;
    },
    invalid: 'Use m:ss above 0:00, like 4:30',
    ends: ['Fastest', 'Slowest'],
    order: "Fastest can't be slower than slowest",
    inputMode: 'text',
  },
  bpm: {
    unit: 'bpm',
    parse: parseWhole,
    invalid: 'Enter a whole number, like 150',
    ends: ['Min', 'Max'],
    order: "Min can't be more than max",
    inputMode: 'numeric',
  },
  count: {
    unit: 'reps',
    parse: parseWhole,
    invalid: 'Enter a whole number, like 6',
    ends: ['Min', 'Max'],
    order: "Min can't be more than max",
    inputMode: 'numeric',
  },
};

// ---------------------------------------------------------------------------
// Validation and request
// ---------------------------------------------------------------------------

export interface SearchIssue {
  path: string[];
  message: string;
}

const readRange = (
  range: RangeValues,
  kind: RangeKind,
  path: string[],
  issues: SearchIssue[]
): NumberRange | undefined => {
  const spec = KIND_SPECS[kind];
  const read = (end: 'min' | 'max'): number | null | undefined => {
    const raw = range[end].trim();
    if (!raw) return undefined;
    const value = spec.parse(raw);
    if (value === null) issues.push({ path: [...path, end], message: spec.invalid });
    return value;
  };

  const min = read('min');
  const max = read('max');
  if (min === null || max === null) return undefined;
  if (min !== undefined && max !== undefined && min > max) {
    issues.push({ path: [...path, 'max'], message: spec.order });
    return undefined;
  }
  if (min === undefined && max === undefined) return undefined;
  return {
    ...(min !== undefined && { min }),
    ...(max !== undefined && { max }),
  };
};

const readDetails = (
  runType: RunType,
  details: DetailValues,
  issues: SearchIssue[]
): SegmentCriteria | undefined => {
  const criteria: SegmentCriteria = {};

  for (const field of DETAIL_FIELDS[runType]) {
    if (field === 'repDistance') {
      const rawDistance = details.repDistance.trim();
      if (!rawDistance) continue;
      const value = parseDecimal(rawDistance);
      if (value === null || value === 0) {
        issues.push({
          path: ['details', 'repDistance'],
          message: 'Enter a distance in metres above 0, like 1000',
        });
      }
      const rawTolerance = details.repTolerance.trim() || DEFAULT_REP_TOLERANCE;
      const tolerance = parseDecimal(rawTolerance);
      if (tolerance === null || tolerance > 100) {
        issues.push({
          path: ['details', 'repTolerance'],
          message: 'Enter a tolerance from 0 to 100 %',
        });
      }
      if (value && tolerance !== null && tolerance <= 100) {
        criteria.repDistance = { value, tolerance: tolerance / 100 };
      }
      continue;
    }

    const range = readRange(
      details[field],
      DETAIL_RANGE_FIELDS[field].kind,
      ['details', field],
      issues
    );
    if (range) criteria[field] = range;
  }

  return Object.keys(criteria).length > 0
    ? { runTypes: [runType], ...criteria }
    : undefined;
};

const readPeriod = (
  values: SearchFormValues,
  today: Date,
  filters: ActivitySearchFilters,
  issues: SearchIssue[]
) => {
  const months = PERIOD_OPTIONS.find((option) => option.value === values.period)?.months;
  if (months) {
    filters.after = format(subMonths(today, months), 'yyyy-MM-dd');
    return;
  }
  if (values.period !== 'custom') return;

  if (values.after) filters.after = values.after;
  if (values.to) {
    // The API's 'before' is the first day excluded; the form's 'to' is the last day included.
    filters.before = format(addDays(parseISO(values.to), 1), 'yyyy-MM-dd');
    if (values.after && values.to < values.after) {
      issues.push({ path: ['to'], message: "End date can't be before start date" });
    }
  }
};

/**
 * The request filters the form describes, and what's wrong with it, by field path.
 * Preset periods count back from `today`.
 */
export const buildSearchFilters = (
  values: SearchFormValues,
  today: Date = new Date()
): { filters: ActivitySearchFilters; issues: SearchIssue[] } => {
  const issues: SearchIssue[] = [];
  const filters: ActivitySearchFilters = {};

  readPeriod(values, today, filters, issues);

  // A chosen type filters on its own figures only; the activity-wide ones apply to all types.
  const runType = selectedRunType(values);
  if (runType !== null) {
    filters.trainingTypes = [runType];
    const criteria = readDetails(runType, values.details, issues);
    if (criteria) filters.segments = [criteria];
  } else {
    if (values.source !== ALL) filters.sources = [values.source];
    for (const field of Object.keys(ACTIVITY_RANGE_FIELDS) as ActivityRangeField[]) {
      const range = readRange(values[field], ACTIVITY_RANGE_FIELDS[field].kind, [field], issues);
      if (range) filters[field] = range;
    }
  }

  return { filters, issues };
};

export const searchFormSchema = searchFormObject.superRefine((values, ctx) => {
  for (const issue of buildSearchFilters(values).issues) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: issue.message, path: issue.path });
  }
});

// ---------------------------------------------------------------------------
// Sorting
// ---------------------------------------------------------------------------

export const SORT_OPTIONS: { value: string; label: string; sort: ActivitySort }[] = [
  { value: 'startTime-desc', label: 'Newest first', sort: { by: 'startTime', order: 'desc' } },
  { value: 'startTime-asc', label: 'Oldest first', sort: { by: 'startTime', order: 'asc' } },
  { value: 'distance-desc', label: 'Longest distance', sort: { by: 'distance', order: 'desc' } },
  { value: 'duration-desc', label: 'Longest time', sort: { by: 'duration', order: 'desc' } },
  { value: 'pace-asc', label: 'Fastest pace', sort: { by: 'pace', order: 'asc' } },
];

// ---------------------------------------------------------------------------
// URL state
// ---------------------------------------------------------------------------

/** `value` without the leaves equal to `fallback`'s; undefined when nothing is left. */
const compact = (value: unknown, fallback: unknown): unknown => {
  if (typeof value === 'object' && value !== null) {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) {
      const kept = compact(item, (fallback as Record<string, unknown>)[key]);
      if (kept !== undefined) out[key] = kept;
    }
    return Object.keys(out).length > 0 ? out : undefined;
  }
  return value === fallback ? undefined : value;
};

/** `fallback` with each string leaf replaced by `raw`'s, where `raw` has a string there. */
const overlay = (fallback: unknown, raw: unknown): unknown => {
  if (typeof fallback === 'string') return typeof raw === 'string' ? raw : fallback;
  const source = typeof raw === 'object' && raw !== null ? (raw as Record<string, unknown>) : {};
  return Object.fromEntries(
    Object.entries(fallback as Record<string, unknown>).map(([key, item]) => [
      key,
      overlay(item, source[key]),
    ])
  );
};

export const encodeSearch = (values: SearchFormValues): string =>
  JSON.stringify(compact(values, defaultSearchValues()) ?? {});

/** The form values in a `q` URL param; null when there is none or it's unreadable. */
export const decodeSearch = (raw: string | null): SearchFormValues | null => {
  if (raw === null) return null;
  try {
    const parsed = searchFormObject.safeParse(overlay(defaultSearchValues(), JSON.parse(raw)));
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
};

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

const describeRange = (label: string, range: RangeValues, kind: RangeKind): string | null => {
  const min = range.min.trim();
  const max = range.max.trim();
  const unit = kind === 'pace' ? '/km' : kind === 'km' ? 'km' : kind === 'bpm' ? 'bpm' : '';
  const suffix = unit ? ` ${unit}` : '';
  if (kind === 'count') {
    if (min && max) return `${min}–${max} reps`;
    if (min) return `${min}+ reps`;
    if (max) return `Up to ${max} reps`;
    return null;
  }
  if (kind === 'pace' && !(min && max)) {
    if (min) return `${label} ${min}${suffix} or slower`;
    if (max) return `${label} ${max}${suffix} or faster`;
  }
  if (min && max) return `${label} ${min}–${max}${suffix}`;
  if (min) return `${label} from ${min}${suffix}`;
  if (max) return `${label} up to ${max}${suffix}`;
  return null;
};

/** Short labels of the filters set in `values`, for the collapsed form. */
export const describeSearch = (values: SearchFormValues): string[] => {
  const labels: string[] = [];
  const runType = selectedRunType(values);
  labels.push(runType !== null ? RUN_TYPE_DISPLAY[runType] : 'All types');

  if (values.period !== 'custom') {
    const option = PERIOD_OPTIONS.find((item) => item.value === values.period);
    if (option?.months) labels.push(option.label);
  } else if (values.after && values.to) {
    labels.push(`${formatDate(values.after)} – ${formatDate(values.to)}`);
  } else if (values.after) {
    labels.push(`From ${formatDate(values.after)}`);
  } else if (values.to) {
    labels.push(`Until ${formatDate(values.to)}`);
  }

  if (runType === null) {
    if (values.source !== ALL) {
      labels.push(PROVIDER_DISPLAY[values.source]);
    }
    for (const field of Object.keys(ACTIVITY_RANGE_FIELDS) as ActivityRangeField[]) {
      const meta = ACTIVITY_RANGE_FIELDS[field];
      const label = describeRange(meta.label, values[field], meta.kind);
      if (label) labels.push(label);
    }
  } else {
    for (const field of DETAIL_FIELDS[runType]) {
      if (field === 'repDistance') {
        const distance = values.details.repDistance.trim();
        if (distance) {
          const tolerance = values.details.repTolerance.trim() || DEFAULT_REP_TOLERANCE;
          labels.push(`Reps of ${distance} m ±${tolerance}%`);
        }
        continue;
      }
      const meta = DETAIL_RANGE_FIELDS[field];
      const label = describeRange(meta.label, values.details[field], meta.kind);
      if (label) labels.push(label);
    }
  }

  return labels;
};
