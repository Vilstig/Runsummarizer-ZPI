import { format, parseISO } from 'date-fns';

/**
 * Converts running speed (meters/second) to running pace (seconds/km).
 * Returns null if speed is invalid or zero.
 */
export const speedToPaceSeconds = (speedMs: number | null | undefined): number | null => {
  if (speedMs == null || speedMs <= 0) return null;
  const secondsPerKm = 1000 / speedMs;
  if (!isFinite(secondsPerKm) || secondsPerKm > 3600) return null;
  return Math.round(secondsPerKm);
};

/**
 * Formats running pace in seconds/km to 'mm:ss /km' or 'mm:ss'.
 */
export const formatPaceSeconds = (
  seconds: number | null | undefined,
  includeUnit = true
): string => {
  if (seconds == null || seconds <= 0) return includeUnit ? '--:-- /km' : '--:--';
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.floor(seconds % 60);
  const formatted = `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
  return includeUnit ? `${formatted} /km` : formatted;
};

/**
 * Formats running speed (meters/second) to running pace (mm:ss /km).
 * Returns '--:-- /km' if speed is null, undefined, or <= 0.
 */
export const formatPace = (speedMs: number | null | undefined): string => {
  const paceSecs = speedToPaceSeconds(speedMs);
  return formatPaceSeconds(paceSecs, true);
};

/**
 * Formats duration in seconds to standard 'hh:mm:ss' or 'mm:ss'.
 */
export const formatDuration = (seconds: number | null | undefined): string => {
  if (seconds == null || seconds < 0) return '--:--';

  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  if (hrs > 0) {
    return `${hrs}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }
  return `${mins}:${secs.toString().padStart(2, '0')}`;
};

/**
 * Formats duration in seconds to standard ISO 8601 duration string, e.g. 'PT1H23M45S'.
 */
export const formatIsoDuration = (seconds: number | null | undefined): string => {
  if (seconds == null || seconds < 0) return 'PT0S';
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  let result = 'PT';
  if (hrs > 0) result += `${hrs}H`;
  if (mins > 0 || hrs > 0) result += `${mins}M`;
  result += `${secs}S`;
  return result;
};

/**
 * Formats distance in meters to kilometers with 2 decimals, e.g. '10.05 km'.
 */
export const formatDistance = (meters: number | null | undefined): string => {
  if (meters == null || meters < 0) return '-- km';
  const km = meters / 1000;
  return `${km.toFixed(2)} km`;
};

/**
 * Formats cardiovascular heart rate value to 'XXX bpm'.
 */
export const formatHeartRate = (bpm: number | null | undefined): string => {
  if (bpm == null || bpm <= 0) return '-- bpm';
  return `${Math.round(bpm)} bpm`;
};

/**
 * Formats running cadence (strides or steps per minute).
 */
export const formatCadence = (spm: number | null | undefined): string => {
  if (spm == null || spm <= 0) return '-- spm';
  return `${Math.round(spm)} spm`;
};

/**
 * Formats elevation gain or loss in meters, e.g. '+120 m'.
 */
export const formatElevation = (meters: number | null | undefined): string => {
  if (meters == null) return '-- m';
  const rounded = Math.round(meters);
  const sign = rounded > 0 ? '+' : '';
  return `${sign}${rounded} m`;
};

/**
 * Formats ISO date string to readable calendar date, e.g. 'Oct 15, 2026'.
 */
export const formatDate = (isoString: string | null | undefined): string => {
  if (!isoString) return '--';
  try {
    const date = parseISO(isoString);
    return format(date, 'MMM d, yyyy');
  } catch {
    return isoString;
  }
};

/**
 * Formats ISO date string to readable date and time, e.g. 'Oct 15, 2026, 17:53'.
 */
export const formatDateTime = (isoString: string | null | undefined): string => {
  if (!isoString) return '--';
  try {
    const date = parseISO(isoString);
    return format(date, 'MMM d, yyyy, HH:mm');
  } catch {
    return isoString;
  }
};