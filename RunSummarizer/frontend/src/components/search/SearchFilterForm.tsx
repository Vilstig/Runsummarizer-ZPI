import React from 'react';
import {
  Controller,
  FormProvider,
  get,
  useForm,
  useWatch,
  type FieldErrors,
} from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { ChevronDown, RotateCcw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { RangeField } from './RangeField';
import {
  ACTIVITY_RANGE_FIELDS,
  ALL,
  DETAIL_FIELDS,
  DETAIL_RANGE_FIELDS,
  PERIOD_OPTIONS,
  RACE_PRESETS,
  RUN_TYPE_OPTIONS,
  defaultSearchValues,
  emptyDetails,
  searchFormSchema,
  selectedRunType,
  type ActivityRangeField,
  type SearchFormValues,
} from '@/schemas/search';
import { RunType, RUN_TYPE_DISPLAY } from '@/types/enums';
import { RUN_TYPE_COLORS } from '@/utils/colors';
import { PROVIDER_DISPLAY, PROVIDER_ORDER } from '@/utils/providers';
import { cn } from '@/lib/utils';

interface FilterSectionProps {
  id: string;
  title: string;
  hint?: string;
  open: boolean;
  onToggle: () => void;
  highlighted?: boolean;
  children: React.ReactNode;
}

/** A titled block of filters that folds away; its inputs stay mounted while folded. */
const FilterSection: React.FC<FilterSectionProps> = ({
  id,
  title,
  hint,
  open,
  onToggle,
  highlighted,
  children,
}) => (
  <section
    className={cn(
      'rounded-xl border bg-background/40',
      highlighted ? 'border-primary/40' : 'border-border'
    )}
  >
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      aria-controls={id}
      className="flex w-full min-h-[44px] items-center justify-between gap-3 rounded-xl px-3.5 py-2.5 text-left touch-manipulation focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-primary"
    >
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-foreground">{title}</span>
        {hint && !open && (
          <span className="block truncate text-xs text-muted-foreground">{hint}</span>
        )}
      </span>
      <ChevronDown
        className={cn(
          'h-4 w-4 shrink-0 text-muted-foreground transition-transform',
          open && 'rotate-180'
        )}
      />
    </button>
    <div id={id} hidden={!open} className="space-y-4 px-3.5 pb-3.5">
      {children}
    </div>
  </section>
);

const fieldLabelClass = 'text-xs font-semibold text-foreground';
const controlClass = 'h-11 sm:h-9 text-sm sm:text-xs';

const hasErrors = (errors: FieldErrors<SearchFormValues>, names: string[]) =>
  names.some((name) => get(errors, name) !== undefined);

const MORE_FILTER_NAMES = ['source', ...Object.keys(ACTIVITY_RANGE_FIELDS)];

const moreFiltersSet = (values: SearchFormValues) =>
  values.source !== ALL ||
  (Object.keys(ACTIVITY_RANGE_FIELDS) as ActivityRangeField[]).some(
    (field) => values[field].min.trim() || values[field].max.trim()
  );

export interface SearchFilterFormProps {
  defaultValues: SearchFormValues;
  onSearch: (values: SearchFormValues) => void;
  onReset: () => void;
  isSearching?: boolean;
}

export const SearchFilterForm: React.FC<SearchFilterFormProps> = ({
  defaultValues,
  onSearch,
  onReset,
  isSearching,
}) => {
  const form = useForm<SearchFormValues>({
    resolver: zodResolver(searchFormSchema),
    defaultValues,
  });
  const {
    control,
    register,
    handleSubmit,
    setValue,
    clearErrors,
    formState: { errors },
  } = form;

  const [detailsOpen, setDetailsOpen] = React.useState(true);
  const [moreOpen, setMoreOpen] = React.useState(() => moreFiltersSet(defaultValues));

  const trainingType = useWatch({ control, name: 'trainingType' });
  const period = useWatch({ control, name: 'period' });
  const runType = selectedRunType({ ...defaultValues, trainingType });
  const detailFields = runType !== null ? DETAIL_FIELDS[runType] : [];

  // Open folded sections holding errors so the first invalid input can take focus.
  const handleInvalid = (invalid: FieldErrors<SearchFormValues>) => {
    if (invalid.details) setDetailsOpen(true);
    if (hasErrors(invalid, MORE_FILTER_NAMES)) setMoreOpen(true);
  };

  const handleTypeChange = (value: string, onChange: (value: string) => void) => {
    onChange(value);
    // Each type shows different fields; hidden values are cleared so they can't come back unseen.
    setValue('details', emptyDetails());
    const defaults = defaultSearchValues();
    setValue('source', defaults.source);
    for (const field of Object.keys(ACTIVITY_RANGE_FIELDS) as ActivityRangeField[]) {
      setValue(field, defaults[field]);
    }
    clearErrors(['details', 'source', ...(Object.keys(ACTIVITY_RANGE_FIELDS) as ActivityRangeField[])]);
    setDetailsOpen(true);
    setMoreOpen(false);
  };

  const repDistanceError: string | undefined =
    errors.details?.repDistance?.message ?? errors.details?.repTolerance?.message;

  return (
    <FormProvider {...form}>
      <form
        noValidate
        onSubmit={handleSubmit(onSearch, handleInvalid)}
        aria-label="Search filters"
        className="space-y-4 rounded-2xl border border-border bg-card p-3.5 sm:p-4 shadow-xs"
      >
        {/* Training type */}
        <div className="space-y-1.5">
          <label htmlFor="search-training-type" className={fieldLabelClass}>
            Training type
          </label>
          <Controller
            control={control}
            name="trainingType"
            render={({ field }) => (
              <Select
                value={field.value}
                onValueChange={(value) => handleTypeChange(value, field.onChange)}
              >
                <SelectTrigger id="search-training-type" className={controlClass}>
                  <SelectValue placeholder="All types" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All types</SelectItem>
                  {RUN_TYPE_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      <span className="flex items-center gap-2">
                        <span
                          className={cn(
                            'h-2 w-2 rounded-full shrink-0',
                            RUN_TYPE_COLORS[Number(option.value)]?.dot
                          )}
                        />
                        {option.label}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        </div>

        {/* Type-specific filters */}
        {runType !== null && (
          <FilterSection
            id="search-type-details"
            title={`${RUN_TYPE_DISPLAY[runType]} details`}
            hint="Optional filters for this type"
            open={detailsOpen}
            onToggle={() => setDetailsOpen((open) => !open)}
            highlighted
          >
            {runType === RunType.RACE && (
              <div className="space-y-1.5">
                <span className={fieldLabelClass}>Race distance</span>
                <div className="flex flex-wrap gap-2">
                  {RACE_PRESETS.map((preset) => (
                    <Button
                      key={preset.label}
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        setValue(
                          'details.distance',
                          { min: preset.km, max: preset.km },
                          { shouldValidate: form.formState.isSubmitted }
                        )
                      }
                      className="min-h-[44px] sm:min-h-[32px] rounded-full px-3.5 touch-manipulation"
                    >
                      {preset.label}
                    </Button>
                  ))}
                </div>
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-1 gap-4">
              {detailFields.map((field) =>
                field === 'repDistance' ? (
                  <fieldset key={field} className="space-y-1.5 min-w-0">
                    <legend className={cn(fieldLabelClass, 'mb-1.5')}>
                      Rep distance{' '}
                      <span className="font-normal text-muted-foreground">(m, ± %)</span>
                    </legend>
                    <div className="grid grid-cols-2 gap-2">
                      <Input
                        aria-label="Rep distance in metres"
                        aria-invalid={!!errors.details?.repDistance}
                        aria-describedby={repDistanceError ? 'search-rep-distance-error' : undefined}
                        inputMode="decimal"
                        autoComplete="off"
                        placeholder="1000"
                        className={cn(controlClass, 'tabular-nums aria-[invalid=true]:border-destructive')}
                        {...register('details.repDistance')}
                      />
                      <div className="relative">
                        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm sm:text-xs text-muted-foreground">
                          ±
                        </span>
                        <Input
                          aria-label="Rep distance tolerance in percent"
                          aria-invalid={!!errors.details?.repTolerance}
                          aria-describedby={repDistanceError ? 'search-rep-distance-error' : undefined}
                          inputMode="decimal"
                          autoComplete="off"
                          placeholder="5"
                          className={cn(controlClass, 'pl-7 pr-8 tabular-nums aria-[invalid=true]:border-destructive')}
                          {...register('details.repTolerance')}
                        />
                        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm sm:text-xs text-muted-foreground">
                          %
                        </span>
                      </div>
                    </div>
                    {repDistanceError && (
                      <p id="search-rep-distance-error" className="text-xs text-destructive">
                        {repDistanceError}
                      </p>
                    )}
                  </fieldset>
                ) : (
                  <RangeField
                    key={field}
                    name={`details.${field}`}
                    meta={DETAIL_RANGE_FIELDS[field]}
                  />
                )
              )}
            </div>
          </FilterSection>
        )}

        {/* Date range */}
        <div className="space-y-1.5">
          <label htmlFor="search-period" className={fieldLabelClass}>
            Date
          </label>
          <Controller
            control={control}
            name="period"
            render={({ field }) => (
              <Select
                value={field.value}
                onValueChange={(value) => {
                  field.onChange(value);
                  clearErrors(['after', 'to']);
                }}
              >
                <SelectTrigger id="search-period" className={controlClass}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PERIOD_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
          {period === 'custom' && (
            <div className="grid grid-cols-2 gap-2 pt-1">
              <div className="space-y-1 min-w-0">
                <label htmlFor="search-after" className="text-xs text-muted-foreground">
                  From
                </label>
                <Input
                  id="search-after"
                  type="date"
                  className={controlClass}
                  {...register('after')}
                />
              </div>
              <div className="space-y-1 min-w-0">
                <label htmlFor="search-to" className="text-xs text-muted-foreground">
                  To
                </label>
                <Input
                  id="search-to"
                  type="date"
                  aria-invalid={!!errors.to}
                  aria-describedby={errors.to ? 'search-to-error' : undefined}
                  className={cn(controlClass, 'aria-[invalid=true]:border-destructive')}
                  {...register('to')}
                />
              </div>
            </div>
          )}
          {period === 'custom' && errors.to && (
            <p id="search-to-error" className="text-xs text-destructive">
              {errors.to.message}
            </p>
          )}
        </div>

        {/* Activity-wide filters, for all types only */}
        {runType === null && (
          <FilterSection
            id="search-more-filters"
            title="More filters"
            hint="Source, distance, duration, pace, heart rate"
            open={moreOpen}
            onToggle={() => setMoreOpen((open) => !open)}
          >
            <div className="space-y-1.5">
              <label htmlFor="search-source" className={fieldLabelClass}>
                Source
              </label>
              <Controller
                control={control}
                name="source"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="search-source" className={controlClass}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ALL}>All sources</SelectItem>
                      {PROVIDER_ORDER.map((provider) => (
                        <SelectItem key={provider} value={provider}>
                          {PROVIDER_DISPLAY[provider]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-1 gap-4">
              {(Object.keys(ACTIVITY_RANGE_FIELDS) as ActivityRangeField[]).map((field) => (
                <RangeField key={field} name={field} meta={ACTIVITY_RANGE_FIELDS[field]} />
              ))}
            </div>
          </FilterSection>
        )}

        {/* Actions */}
        <div className="flex items-center gap-2 pt-1">
          <Button
            type="button"
            variant="outline"
            onClick={onReset}
            className="min-h-[44px] sm:min-h-[36px] touch-manipulation"
          >
            <RotateCcw />
            Reset
          </Button>
          <Button
            type="submit"
            disabled={isSearching}
            className="flex-1 min-h-[44px] sm:min-h-[36px] text-sm touch-manipulation"
          >
            <Search />
            Search
          </Button>
        </div>
      </form>
    </FormProvider>
  );
};
