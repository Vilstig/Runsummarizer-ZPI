import { z } from 'zod';
import { LapType, TextPolicy } from '@/types/enums';

export const lapEditSchema = z.object({
  lapIndex: z.number(),
  typeId: z.nativeEnum(LapType).optional().nullable(),
  distance: z.coerce.number().positive().max(50000).optional().nullable(),
});

export const updateLapsSchema = z.object({
  laps: z.array(lapEditSchema).min(1, 'At least 1 lap is required'),
  textPolicy: z.nativeEnum(TextPolicy).optional().nullable(),
});

export type LapEditFormValues = z.infer<typeof lapEditSchema>;
export type UpdateLapsFormValues = z.infer<typeof updateLapsSchema>;