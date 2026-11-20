import axios from 'axios';
import { handleMockRequest } from '@/mock/mockAdapter';

export const isMockEnabled = import.meta.env.VITE_USE_MOCK === 'true';

type TokenGetter = () => Promise<string | null>;
let tokenGetter: TokenGetter | null = null;

/**
 * Registers an active auth token getter (e.g. from Clerk's useAuth hook).
 */
export const setAuthTokenGetter = (getter: TokenGetter | null): void => {
  tokenGetter = getter;
};

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
});

if (isMockEnabled) {
  const defaultAdapter = axios.getAdapter(axios.defaults.adapter || ['xhr', 'fetch']);
  apiClient.defaults.adapter = async (config) => {
    const mockRes = await handleMockRequest(config);
    if (mockRes) {
      return mockRes;
    }
    return defaultAdapter(config);
  };
}

apiClient.interceptors.request.use(async (config) => {
  try {
    let token: string | null = null;
    if (tokenGetter) {
      token = await tokenGetter();
    } else if (typeof window !== 'undefined' && window.Clerk?.session?.getToken) {
      token = (await window.Clerk.session.getToken()) ?? null;
    }

    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  } catch {
    // No token available — proceed without auth header
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      console.warn('[API] Unauthorized request (401)');
    }
    return Promise.reject(error);
  }
);

export default apiClient;