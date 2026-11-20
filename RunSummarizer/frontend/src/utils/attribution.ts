import type { Activity, ProcessedData } from '@/types/api';
import { Provider } from '@/types/enums';

/** The fields the attribution reads; `deviceName` may be absent */
export type AttributedActivity = Pick<Activity, 'source'> & {
  processed_data: Partial<Pick<ProcessedData, 'deviceName'>>;
};

/** Shown next to lap types, summaries and estimates computed from Garmin activities */
export const GARMIN_DERIVED_DATA_NOTE = 'Insights derived in part from Garmin device-sourced data';

/** Whether an activity `source` is Garmin, in any letter case */
export const isGarminSource = (source: string | null | undefined): boolean =>
  source?.toLowerCase() === Provider.GARMIN;

export const isGarminActivity = (activity: AttributedActivity): boolean =>
  isGarminSource(activity.source);

/** 'Garmin {deviceName}', or 'Garmin' when the device is unknown. */
export const garminDeviceLabel = (deviceName: string | null | undefined): string => {
  const name = deviceName?.trim();
  if (!name) return 'Garmin';
  return /^garmin\b/i.test(name) ? name : `Garmin ${name}`;
};

/**
 * The distinct device labels of the Garmin activities in `activities`, in order of first
 * appearance. A bare 'Garmin' is listed only when no Garmin activity names its device.
 */
export const garminAttributionLabels = (
  activities: readonly AttributedActivity[]
): string[] => {
  const labels = new Set<string>();
  let unnamed = false;
  for (const activity of activities) {
    if (!isGarminActivity(activity)) continue;
    if (activity.processed_data.deviceName?.trim()) {
      labels.add(garminDeviceLabel(activity.processed_data.deviceName));
    } else {
      unnamed = true;
    }
  }
  if (labels.size === 0 && unnamed) labels.add(garminDeviceLabel(null));
  return [...labels];
};

/**
 * `text` with the activity's Garmin attribution appended, for text that leaves the app
 * (copied or shared); text of other providers' activities is returned unchanged.
 */
export const withGarminAttribution = (
  text: string,
  activity: AttributedActivity,
  { derived = false }: { derived?: boolean } = {}
): string => {
  if (!isGarminActivity(activity)) return text;
  const label = garminDeviceLabel(activity.processed_data.deviceName);
  return `${text}\n\n${derived ? `${label}. ${GARMIN_DERIVED_DATA_NOTE}.` : label}`;
};
