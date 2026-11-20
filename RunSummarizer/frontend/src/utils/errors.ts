import axios from 'axios';
import { toast } from 'sonner';

/** The HTTP status of an Axios error, or `undefined` for anything else. */
export const getApiErrorStatus = (error: unknown): number | undefined =>
  axios.isAxiosError(error) ? error.response?.status : undefined;

/** Seconds from a 503's `Retry-After` header, when the response exposes one. */
const getRetryAfterSeconds = (error: unknown): number | null => {
  if (!axios.isAxiosError(error) || error.response?.status !== 503) return null;
  const seconds = Number(error.response.headers?.['retry-after']);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
};

const formatWait = (seconds: number): string =>
  seconds < 60 ? `${Math.ceil(seconds)} s` : `${Math.ceil(seconds / 60)} min`;

/**
 * Extracts a human-readable error message from an unknown API or Axios error.
 */
export const getApiErrorMessage = (error: unknown, fallbackMessage: string): string => {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') {
      const retryAfter = getRetryAfterSeconds(error);
      return retryAfter === null ? detail : `${detail} Retry in about ${formatWait(retryAfter)}.`;
    }
    // FastAPI validation errors: [{ loc, msg, type }, ...]
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (typeof item?.msg === 'string' ? item.msg : null))
        .filter(Boolean);
      if (messages.length > 0) {
        return messages.join('; ');
      }
    }
    if (detail && typeof detail === 'object') {
      return JSON.stringify(detail);
    }
    if (error.message) {
      return error.message;
    }
  } else if (error instanceof Error) {
    return error.message;
  }

  return fallbackMessage;
};

/**
 * Dispatches an error toast with the extracted error message.
 */
export const handleApiError = (error: unknown, fallbackMessage: string): void => {
  const message = getApiErrorMessage(error, fallbackMessage);
  toast.error(message);
};
