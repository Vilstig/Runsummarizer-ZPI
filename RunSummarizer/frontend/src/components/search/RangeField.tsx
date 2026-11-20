import React from 'react';
import { get, useFormContext, type FieldPath } from 'react-hook-form';
import { Input } from '@/components/ui/input';
import { KIND_SPECS, type RangeFieldMeta, type SearchFormValues } from '@/schemas/search';

export interface RangeFieldProps {
  /** Path of the field's `{ min, max }` in the form, e.g. 'distance' or 'details.pace'. */
  name: FieldPath<SearchFormValues>;
  meta: RangeFieldMeta;
}

export const RangeField: React.FC<RangeFieldProps> = ({ name, meta }) => {
  const {
    register,
    formState: { errors },
  } = useFormContext<SearchFormValues>();
  const spec = KIND_SPECS[meta.kind];
  const unit = meta.unit ?? spec.unit;
  const id = `search-${name.replace('.', '-')}`;
  const minError: string | undefined = get(errors, `${name}.min`)?.message;
  const maxError: string | undefined = get(errors, `${name}.max`)?.message;
  const error = minError ?? maxError;

  const inputClass =
    'h-11 sm:h-9 text-sm sm:text-xs tabular-nums aria-[invalid=true]:border-destructive aria-[invalid=true]:focus-visible:ring-destructive';

  return (
    <fieldset className="space-y-1.5 min-w-0" aria-describedby={error ? `${id}-error` : undefined}>
      <legend className="text-xs font-semibold text-foreground mb-1.5">
        {meta.label}
        {unit && <span className="font-normal text-muted-foreground"> ({unit})</span>}
      </legend>
      <div className="grid grid-cols-2 gap-2">
        {([['min', 0], ['max', 1]] as const).map(([end, index]) => (
          <Input
            key={end}
            id={`${id}-${end}`}
            aria-label={`${meta.label}, ${spec.ends[index].toLowerCase()}`}
            aria-invalid={end === 'min' ? !!minError : !!maxError}
            aria-describedby={error ? `${id}-error` : undefined}
            inputMode={spec.inputMode}
            autoComplete="off"
            placeholder={`${spec.ends[index]} ${meta.examples[index]}`}
            className={inputClass}
            {...register(`${name}.${end}` as FieldPath<SearchFormValues>)}
          />
        ))}
      </div>
      {error && (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {error}
        </p>
      )}
    </fieldset>
  );
};
