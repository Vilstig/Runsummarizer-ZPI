import { AxiosError, type InternalAxiosRequestConfig, type AxiosResponse } from 'axios';
import { MOCK_PROVIDERS, mockStorage } from './mockStorage';
import type { Provider } from '@/types/enums';
import { PROVIDER_DISPLAY } from '@/utils/providers';

/**
 * Artificial realistic network delay (120ms - 200ms)
 * Allows micro-interactions, page skeletons, and loading transitions to render cleanly.
 */
const delay = (ms = 150) => new Promise((resolve) => setTimeout(resolve, ms));

export async function handleMockRequest(
  config: InternalAxiosRequestConfig
): Promise<AxiosResponse | null> {
  const url = config.url || '';
  const method = (config.method || 'get').toLowerCase();

  // Normalize path without query string or baseURL
  let fullPath = url;
  if (config.baseURL && !url.startsWith('http://') && !url.startsWith('https://')) {
    try {
      fullPath = new URL(url, config.baseURL).pathname;
    } catch {
      fullPath = url;
    }
  } else if (url.startsWith('http://') || url.startsWith('https://')) {
    try {
      fullPath = new URL(url).pathname;
    } catch {
      fullPath = url;
    }
  }
  const cleanPath: string = fullPath.split('?')[0] || '';

  // Helper to format mock Axios response
  const respond = async (data: unknown, status = 200): Promise<AxiosResponse> => {
    await delay();
    const response: AxiosResponse = {
      data,
      status,
      statusText: status < 400 ? 'OK' : 'Error',
      headers: {},
      config,
      request: {},
    };
    if (status >= 400) {
      throw new AxiosError(
        `Request failed with status code ${status}`,
        AxiosError.ERR_BAD_REQUEST,
        config,
        response.request,
        response
      );
    }
    return response;
  };

  const mockProvider = (value: string | undefined): Provider | null =>
    MOCK_PROVIDERS.find((provider) => provider === value) ?? null;

  // Parse payload safely
  const payload =
    typeof config.data === 'string'
      ? (() => {
          try {
            return JSON.parse(config.data);
          } catch {
            return null;
          }
        })()
      : config.data;

  // 1. GET /api/v1/activities
  if (method === 'get' && cleanPath === '/api/v1/activities') {
    const params = config.params || {};
    const activities = mockStorage.getActivities(params);
    return respond(activities);
  }

  // GET /api/v1/activities/weekly-summary (before the single-activity route, which would
  // read 'weekly-summary' as an id)
  if (method === 'get' && cleanPath === '/api/v1/activities/weekly-summary') {
    const params = config.params || {};
    const weeks = Number(params.weeks) || 12;
    return respond(mockStorage.getWeeklySummary(weeks, params.date));
  }

  // 2. Laps Reset: POST /api/v1/activities/:id/laps/reset
  const lapsResetMatch = cleanPath.match(/^\/api\/v1\/activities\/([^/]+)\/laps\/reset$/);
  if (method === 'post' && lapsResetMatch && lapsResetMatch[1]) {
    const id = lapsResetMatch[1];
    const act = mockStorage.resetActivityLaps(id);
    return respond(act || { error: 'Activity not found' }, act ? 200 : 404);
  }

  // 3. Laps Update: PATCH /api/v1/activities/:id/laps
  const lapsUpdateMatch = cleanPath.match(/^\/api\/v1\/activities\/([^/]+)\/laps$/);
  if (method === 'patch' && lapsUpdateMatch && lapsUpdateMatch[1]) {
    const id = lapsUpdateMatch[1];
    const laps = payload?.laps || [];
    const act = mockStorage.updateActivityLaps(id, laps);
    return respond(act || { error: 'Activity not found' }, act ? 200 : 404);
  }

  // 4. Laps List: GET /api/v1/activities/:id/laps
  if (method === 'get' && lapsUpdateMatch && lapsUpdateMatch[1]) {
    const id = lapsUpdateMatch[1];
    const laps = mockStorage.getActivityLaps(id);
    return respond(laps);
  }

  // 5. Streams: GET /api/v1/activities/:id/streams
  const streamsMatch = cleanPath.match(/^\/api\/v1\/activities\/([^/]+)\/streams$/);
  if (method === 'get' && streamsMatch) {
    return respond({
      time: [],
      distance: [],
      heartrate: [],
      velocity: [],
      altitude: [],
    });
  }

  // 6. Summary Reset: POST /api/v1/activities/:id/summary/reset
  const summaryResetMatch = cleanPath.match(/^\/api\/v1\/activities\/([^/]+)\/summary\/reset$/);
  if (method === 'post' && summaryResetMatch && summaryResetMatch[1]) {
    const id = summaryResetMatch[1];
    const act = mockStorage.resetActivitySummary(id);
    return respond(act || { error: 'Activity not found' }, act ? 200 : 404);
  }

  // 7. Summary Edit: PATCH /api/v1/activities/:id/summary
  const summaryEditMatch = cleanPath.match(/^\/api\/v1\/activities\/([^/]+)\/summary$/);
  if (method === 'patch' && summaryEditMatch && summaryEditMatch[1]) {
    const id = summaryEditMatch[1];
    const text = payload?.text || '';
    const act = mockStorage.editActivitySummary(id, text);
    return respond(act || { error: 'Activity not found' }, act ? 200 : 404);
  }

  // 8. Segments: PUT /api/v1/activities/:id/segments
  const segmentsMatch = cleanPath.match(/^\/api\/v1\/activities\/([^/]+)\/segments$/);
  if (method === 'put' && segmentsMatch && segmentsMatch[1]) {
    const id = segmentsMatch[1];
    const act = mockStorage.getActivity(id);
    return respond(act || { error: 'Activity not found' }, act ? 200 : 404);
  }

  // 9. Single Activity: GET or DELETE /api/v1/activities/:id
  const singleActivityMatch = cleanPath.match(/^\/api\/v1\/activities\/([^/]+)$/);
  if (singleActivityMatch && singleActivityMatch[1]) {
    const id = singleActivityMatch[1];
    if (method === 'get') {
      const act = mockStorage.getActivity(id);
      return respond(act || { error: 'Activity not found' }, act ? 200 : 404);
    }
    if (method === 'delete') {
      mockStorage.deleteActivity(id);
      return respond({ success: true });
    }
  }

  // 10. User Profile: GET / PUT /api/v1/users/me/profile
  if (cleanPath === '/api/v1/users/me/profile') {
    if (method === 'get') {
      return respond(mockStorage.getProfile());
    }
    if (method === 'put') {
      return respond(mockStorage.updateProfile(payload));
    }
  }

  // 11. User HR Zones: GET / PUT /api/v1/users/me/hr-zones
  if (cleanPath === '/api/v1/users/me/hr-zones') {
    if (method === 'get') {
      return respond(mockStorage.getHrZones());
    }
    if (method === 'put') {
      return respond(mockStorage.updateHrZones(payload));
    }
  }

  // 12. Sync Status: GET /api/v1/sync/:provider/status
  const syncStatusMatch = cleanPath.match(/^\/api\/v1\/sync\/([^/]+)\/status$/);
  if (method === 'get' && syncStatusMatch) {
    if (!mockProvider(syncStatusMatch[1])) {
      return respond({ detail: 'Provider not supported' }, 404);
    }
    return respond(mockStorage.getSyncStatus());
  }

  // 13. Trigger Sync: POST /api/v1/sync/:provider
  const syncMatch = cleanPath.match(/^\/api\/v1\/sync\/([^/]+)$/);
  if (method === 'post' && syncMatch) {
    const provider = mockProvider(syncMatch[1]);
    if (!provider) {
      return respond({ detail: 'Provider not supported' }, 404);
    }
    if (!mockStorage.canSync(provider)) {
      return respond(
        {
          detail: `${PROVIDER_DISPLAY[provider]} can't be synced. New activities arrive on their own.`,
          code: 'sync_not_supported',
        },
        409
      );
    }
    if (mockStorage.getConnectedProvider() !== provider) {
      return respond({ detail: `${provider} not connected` }, 409);
    }
    return respond(mockStorage.triggerSync(), 202);
  }

  // 14. Providers: GET /api/v1/providers
  if (method === 'get' && cleanPath === '/api/v1/providers') {
    return respond(mockStorage.getProviders());
  }

  // 15. Provider Connect: GET /api/v1/providers/:provider/connect
  const connectMatch = cleanPath.match(/^\/api\/v1\/providers\/([^/]+)\/connect$/);
  if (method === 'get' && connectMatch) {
    const provider = mockProvider(connectMatch[1]);
    if (!provider) {
      return respond({ detail: 'Provider not supported' }, 404);
    }
    const connected = mockStorage.getConnectedProvider();
    if (connected && connected !== provider) {
      return respond({ detail: 'Disconnect the connected provider first' }, 409);
    }
    mockStorage.setConnectedProvider(provider);
    return respond({
      authorize_url: `/oauth/callback?provider=${provider}&mock=true`,
    });
  }

  // 16. Provider Disconnect: DELETE /api/v1/providers/:provider/connection
  const disconnectMatch = cleanPath.match(/^\/api\/v1\/providers\/([^/]+)\/connection$/);
  if (method === 'delete' && disconnectMatch) {
    const provider = mockProvider(disconnectMatch[1]);
    if (!provider) {
      return respond({ detail: 'Provider not supported' }, 404);
    }
    if (mockStorage.getConnectedProvider() === provider) {
      mockStorage.setConnectedProvider(null);
    }
    return respond(null, 204);
  }

  // Not handled by mock adapter — let it pass through to the network
  return null;
}
