import { Provider } from '@/types/enums';
import type { ProviderStatus } from '@/types/api';

export const PROVIDER_DISPLAY: Record<Provider, string> = {
  [Provider.STRAVA]: 'Strava',
  [Provider.GARMIN]: 'Garmin',
  [Provider.INTERVALS]: 'Intervals.icu',
};

/** The provider's app or service as named in connect, disconnect and reconnect UI. */
export const PROVIDER_CONNECT_NAME: Record<Provider, string> = {
  [Provider.STRAVA]: 'Strava',
  [Provider.GARMIN]: 'Garmin Connect',
  [Provider.INTERVALS]: 'Intervals.icu',
};

/** Every provider, in the backend registry's order; used for source filters. */
export const PROVIDER_ORDER: readonly Provider[] = [
  Provider.STRAVA,
  Provider.GARMIN,
  Provider.INTERVALS,
];

/** Whether `POST /sync/{provider}` is available; a status without `can_sync` counts as syncable. */
export const providerCanSync = (status: Pick<ProviderStatus, 'can_sync'>): boolean =>
  status.can_sync !== false;

const PROVIDER_VALUES = new Set<string>(Object.values(Provider));

export const isProvider = (value: unknown): value is Provider =>
  typeof value === 'string' && PROVIDER_VALUES.has(value);

/** The `error` query parameter the backend's OAuth callback redirects with. */
export type OAuthCallbackError =
  | 'declined'
  | 'authorization_failed'
  | 'state_mismatch'
  | 'another_provider_connected'
  | 'account_taken'
  | 'provider_unavailable'
  | 'failed';

const OAUTH_CALLBACK_MESSAGES: Record<OAuthCallbackError, (name: string) => string> = {
  declined: (name) => `You cancelled connecting ${name}.`,
  authorization_failed: (name) =>
    `${name} didn't accept the authorization. Try connecting again.`,
  state_mismatch: () => 'The connect link expired. Try connecting again.',
  another_provider_connected: (name) =>
    `Another provider is connected. Disconnect it first, then connect ${name}.`,
  account_taken: (name) =>
    `This ${name} account is already linked to another RunSummarizer account.`,
  provider_unavailable: (name) => `${name} isn't responding. Try again later.`,
  failed: (name) => `Connecting ${name} failed. Try again.`,
};

/** The message for an OAuth callback `error` code; unknown codes get the `failed` text. */
export const oauthCallbackErrorMessage = (error: string, provider: Provider): string => {
  const message =
    OAUTH_CALLBACK_MESSAGES[error as OAuthCallbackError] ?? OAUTH_CALLBACK_MESSAGES.failed;
  return message(PROVIDER_CONNECT_NAME[provider]);
};
