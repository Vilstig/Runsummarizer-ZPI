import { z } from 'zod';
import { Sex } from '@/types/enums';

export const userProfileSchema = z.object({
  age: z.coerce.number().min(5).max(99).optional().nullable(),
  sex: z.nativeEnum(Sex).optional().nullable(),
  height_cm: z.coerce.number().min(50).max(240).optional().nullable(),
  max_hr: z.coerce.number().min(0).max(256).optional().nullable(),
});

export type UserProfileFormValues = z.infer<typeof userProfileSchema>;

export const heartRateZonesSchema = z
  .object({
    zone1_bpm: z.coerce.number().min(0).max(256),
    zone2_bpm: z.coerce.number().min(0).max(256),
    zone3_bpm: z.coerce.number().min(0).max(256),
    zone4_bpm: z.coerce.number().min(0).max(256),
    zone5_bpm: z.coerce.number().min(0).max(256),
  })
  .superRefine((data, ctx) => {
    const zones = [
      { val: data.zone1_bpm, field: 'zone1_bpm' as const, label: 'Zone 1' },
      { val: data.zone2_bpm, field: 'zone2_bpm' as const, label: 'Zone 2' },
      { val: data.zone3_bpm, field: 'zone3_bpm' as const, label: 'Zone 3' },
      { val: data.zone4_bpm, field: 'zone4_bpm' as const, label: 'Zone 4' },
      { val: data.zone5_bpm, field: 'zone5_bpm' as const, label: 'Zone 5' },
    ];

    for (let i = 1; i < zones.length; i++) {
      const prev = zones[i - 1];
      const curr = zones[i];
      if (prev && curr && curr.val <= prev.val) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `${curr.label} must be greater than ${prev.label}`,
          path: [curr.field],
        });
      }
    }
  });

export type HeartRateZonesFormValues = z.infer<typeof heartRateZonesSchema>;

export const combinedProfileSettingsSchema = z
  .object({
    age: z.coerce.number().min(5).max(99).optional().nullable(),
    sex: z.nativeEnum(Sex).optional().nullable(),
    height_cm: z.coerce.number().min(50).max(240).optional().nullable(),
    max_hr: z.coerce.number().min(0).max(256).optional().nullable(),
    zone1_bpm: z.coerce.number().min(0).max(256).optional().nullable(),
    zone2_bpm: z.coerce.number().min(0).max(256).optional().nullable(),
    zone3_bpm: z.coerce.number().min(0).max(256).optional().nullable(),
    zone4_bpm: z.coerce.number().min(0).max(256).optional().nullable(),
    zone5_bpm: z.coerce.number().min(0).max(256).optional().nullable(),
  })
  .superRefine((data, ctx) => {
    const zoneVals = [
      data.zone1_bpm,
      data.zone2_bpm,
      data.zone3_bpm,
      data.zone4_bpm,
      data.zone5_bpm,
    ];
    const hasAnyZone = zoneVals.some((z) => z != null);

    if (hasAnyZone) {
      const fieldNames = [
        'zone1_bpm',
        'zone2_bpm',
        'zone3_bpm',
        'zone4_bpm',
        'zone5_bpm',
      ] as const;

      for (let i = 0; i < 5; i++) {
        const field = fieldNames[i];
        if (field && zoneVals[i] == null) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: 'All 5 heart rate zones must be specified together',
            path: [field],
          });
          return;
        }
      }

      for (let i = 1; i < 5; i++) {
        const field = fieldNames[i];
        const prev = zoneVals[i - 1];
        const curr = zoneVals[i];
        if (field && prev != null && curr != null && curr <= prev) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: `Zone ${i + 1} must be strictly greater than Zone ${i}`,
            path: [field],
          });
        }
      }

      if (data.max_hr != null && data.zone5_bpm != null && data.max_hr <= data.zone5_bpm) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'Max HR must be greater than Zone 5 lower bound',
          path: ['max_hr'],
        });
      }
    }
  });

export type CombinedProfileSettingsFormValues = z.infer<
  typeof combinedProfileSettingsSchema
>;