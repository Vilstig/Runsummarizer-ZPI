import type {
  Activity,
  LapResponse,
  ProviderStatus,
  SyncStartedResponse,
  UserHeartRateZones,
  UserProfile,
  WeekTotalsDto,
  WeeklySummaryResponse,
} from '@/types/api';
import { addWeeks, differenceInCalendarWeeks, format, parseISO, startOfWeek } from 'date-fns';
import type { GetActivitiesParams } from '@/api/activities';
import { Provider, SyncState, LAP_TYPE_DISPLAY, LapType } from '@/types/enums';
import {
  generateInitialActivities,
  initialMockHrZones,
  initialMockProfile,
} from './mockData';

const STORAGE_KEY_ACTIVITIES = 'runsummarizer_mock_activities_v3';
const STORAGE_KEY_PROFILE = 'runsummarizer_mock_profile_v1';
const STORAGE_KEY_HR_ZONES = 'runsummarizer_mock_hr_zones_v1';
const STORAGE_KEY_CONNECTED_PROVIDER = 'runsummarizer_mock_connected_provider_v1';

// Providers the mock backend lists, in the backend's registry order
export const MOCK_PROVIDERS: Provider[] = [Provider.STRAVA, Provider.GARMIN, Provider.INTERVALS];

// Push-only providers: no sync endpoint, runs arrive by webhook
const MOCK_PUSH_ONLY: ReadonlySet<Provider> = new Set([Provider.GARMIN]);

class MockStorage {
  private syncState: SyncState = SyncState.IDLE;
  private syncTimer: NodeJS.Timeout | null = null;

  private load<T>(key: string, fallback: () => T): T {
    try {
      if (typeof window === 'undefined') return fallback();
      const raw = localStorage.getItem(key);
      if (!raw) {
        const initial = fallback();
        this.save(key, initial);
        return initial;
      }
      return JSON.parse(raw) as T;
    } catch {
      return fallback();
    }
  }

  private save<T>(key: string, data: T): void {
    try {
      if (typeof window !== 'undefined') {
        localStorage.setItem(key, JSON.stringify(data));
      }
    } catch {
      // Storage quota or private mode
    }
  }

  // --- ACTIVITIES ---

  getActivities(params: GetActivitiesParams = {}): Activity[] {
    const list = this.load<Activity[]>(STORAGE_KEY_ACTIVITIES, generateInitialActivities);

    let filtered = [...list];

    // Filter by source
    if (params.source && (params.source as string) !== 'all') {
      filtered = filtered.filter(
        (a) => a.source.toLowerCase() === params.source?.toLowerCase()
      );
    }

    // Filter by after date (inclusive or greater)
    if (params.after) {
      const afterTime = new Date(params.after).getTime();
      filtered = filtered.filter((a) => {
        if (!a.processed_data.startTimeLocal) return false;
        return new Date(a.processed_data.startTimeLocal).getTime() >= afterTime;
      });
    }

    // Filter by before date (inclusive or less)
    if (params.before) {
      const beforeTime = new Date(params.before).getTime();
      filtered = filtered.filter((a) => {
        if (!a.processed_data.startTimeLocal) return false;
        return new Date(a.processed_data.startTimeLocal).getTime() <= beforeTime;
      });
    }

    // Sort descending (newest first)
    filtered.sort((a, b) => {
      const tA = a.processed_data.startTimeLocal ? new Date(a.processed_data.startTimeLocal).getTime() : 0;
      const tB = b.processed_data.startTimeLocal ? new Date(b.processed_data.startTimeLocal).getTime() : 0;
      return tB - tA;
    });

    // Pagination
    const skip = params.skip ?? 0;
    const limit = params.limit ?? 50;

    return filtered.slice(skip, skip + limit);
  }

  /**
   * Totals of the last `weeks` Monday-based weeks, oldest first, ending with the week of
   * `date` (yyyy-MM-dd; today when absent), as `GET /activities/weekly-summary` returns them.
   */
  getWeeklySummary(weeks: number, date?: string): WeeklySummaryResponse {
    const list = this.load<Activity[]>(STORAGE_KEY_ACTIVITIES, generateInitialActivities);
    const lastWeekStart = startOfWeek(date ? parseISO(date) : new Date(), { weekStartsOn: 1 });
    const totals: WeekTotalsDto[] = Array.from({ length: weeks }, (_, i) => ({
      weekStart: format(addWeeks(lastWeekStart, i - (weeks - 1)), 'yyyy-MM-dd'),
      distance: 0,
      duration: 0,
      elevationGain: 0,
    }));

    for (const activity of list) {
      const { startTimeLocal, distance, duration, elevationGain } = activity.processed_data;
      if (!startTimeLocal) continue;
      const weeksAgo = differenceInCalendarWeeks(lastWeekStart, parseISO(startTimeLocal), {
        weekStartsOn: 1,
      });
      const week = totals[weeks - 1 - weeksAgo];
      if (!week) continue;
      week.distance += distance || 0;
      week.duration += duration || 0;
      week.elevationGain += elevationGain || 0;
    }

    return { weeks: totals };
  }

  getActivity(id: string): Activity | null {
    const list = this.load<Activity[]>(STORAGE_KEY_ACTIVITIES, generateInitialActivities);
    return list.find((a) => a.activityId === id) ?? null;
  }

  getActivityLaps(id: string): LapResponse[] {
    const act = this.getActivity(id);
    return act?.processed_data.laps || [];
  }

  updateActivityLaps(
    id: string,
    lapsToUpdate: { lapIndex: number; typeId?: LapType | null }[]
  ): Activity | null {
    const list = this.load<Activity[]>(STORAGE_KEY_ACTIVITIES, generateInitialActivities);
    const act = list.find((a) => a.activityId === id);
    if (!act) return null;

    lapsToUpdate.forEach((update) => {
      const lap = act.processed_data.laps.find((l) => l.lapIndex === update.lapIndex);
      if (lap && update.typeId != null) {
        lap.typeId = update.typeId;
        lap.typeDisplay = LAP_TYPE_DISPLAY[update.typeId] || 'Run';
        lap.typeName = lap.typeDisplay.toLowerCase();
        lap.version = (lap.version || 0) + 1;
      }
    });

    this.save(STORAGE_KEY_ACTIVITIES, list);
    return act;
  }

  resetActivityLaps(id: string): Activity | null {
    const initialList = generateInitialActivities();
    const cleanAct = initialList.find((a) => a.activityId === id);
    if (!cleanAct) return null;

    const list = this.load<Activity[]>(STORAGE_KEY_ACTIVITIES, generateInitialActivities);
    const idx = list.findIndex((a) => a.activityId === id);
    if (idx !== -1 && list[idx]) {
      list[idx].processed_data.laps = cleanAct.processed_data.laps;
      this.save(STORAGE_KEY_ACTIVITIES, list);
      return list[idx] ?? null;
    }
    return null;
  }

  editActivitySummary(id: string, text: string): Activity | null {
    const list = this.load<Activity[]>(STORAGE_KEY_ACTIVITIES, generateInitialActivities);
    const act = list.find((a) => a.activityId === id);
    if (!act) return null;

    act.summary = text;
    act.summaryTextEdited = true;
    this.save(STORAGE_KEY_ACTIVITIES, list);
    return act;
  }

  resetActivitySummary(id: string): Activity | null {
    const initialList = generateInitialActivities();
    const cleanAct = initialList.find((a) => a.activityId === id);
    if (!cleanAct) return null;

    const list = this.load<Activity[]>(STORAGE_KEY_ACTIVITIES, generateInitialActivities);
    const act = list.find((a) => a.activityId === id);
    if (!act) return null;

    act.summary = cleanAct.summary;
    act.summaryTextEdited = false;
    this.save(STORAGE_KEY_ACTIVITIES, list);
    return act;
  }

  deleteActivity(id: string): void {
    const list = this.load<Activity[]>(STORAGE_KEY_ACTIVITIES, generateInitialActivities);
    const filtered = list.filter((a) => a.activityId !== id);
    this.save(STORAGE_KEY_ACTIVITIES, filtered);
  }

  // --- USER PROFILE & HR ZONES ---

  getProfile(): UserProfile {
    return this.load<UserProfile>(STORAGE_KEY_PROFILE, () => initialMockProfile);
  }

  updateProfile(profile: Partial<UserProfile>): UserProfile {
    const current = this.getProfile();
    const updated = { ...current, ...profile };
    this.save(STORAGE_KEY_PROFILE, updated);
    return updated;
  }

  getHrZones(): UserHeartRateZones {
    return this.load<UserHeartRateZones>(STORAGE_KEY_HR_ZONES, () => initialMockHrZones);
  }

  updateHrZones(zones: UserHeartRateZones): UserHeartRateZones {
    this.save(STORAGE_KEY_HR_ZONES, zones);
    return zones;
  }

  // --- SYNC STATUS ---

  getSyncStatus(): { state: SyncState } {
    return { state: this.syncState };
  }

  // --- PROVIDERS ---

  getConnectedProvider(): Provider | null {
    return this.load<Provider | null>(STORAGE_KEY_CONNECTED_PROVIDER, () => Provider.GARMIN);
  }

  setConnectedProvider(provider: Provider | null): void {
    this.save(STORAGE_KEY_CONNECTED_PROVIDER, provider);
  }

  getProviders(): ProviderStatus[] {
    const connected = this.getConnectedProvider();
    return MOCK_PROVIDERS.map((provider) => ({
      provider,
      configured: true,
      connected: provider === connected,
      sync_state: provider === connected ? this.syncState : SyncState.IDLE,
      can_sync: this.canSync(provider),
    }));
  }

  canSync(provider: Provider): boolean {
    return !MOCK_PUSH_ONLY.has(provider);
  }

  triggerSync(): SyncStartedResponse {
    this.syncState = SyncState.SYNCING;
    if (this.syncTimer) clearTimeout(this.syncTimer);

    // After 2.5 seconds, simulate sync completion and revert to IDLE
    this.syncTimer = setTimeout(() => {
      this.syncState = SyncState.IDLE;
    }, 2500);

    return { queued: 3, requested: false };
  }

  // --- RESET ALL MOCK DATA ---

  resetAll(): void {
    if (typeof window !== 'undefined') {
      localStorage.removeItem(STORAGE_KEY_ACTIVITIES);
      localStorage.removeItem(STORAGE_KEY_PROFILE);
      localStorage.removeItem(STORAGE_KEY_HR_ZONES);
      localStorage.removeItem(STORAGE_KEY_CONNECTED_PROVIDER);
    }
    this.syncState = SyncState.IDLE;
  }
}

export const mockStorage = new MockStorage();
