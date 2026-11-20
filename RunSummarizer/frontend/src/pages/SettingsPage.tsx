import React from 'react';
import { useSearchParams } from 'react-router-dom';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useClerk, UserProfile } from '@clerk/clerk-react';
import {
  Heart,
  Info,
  Laptop,
  LogOut,
  Moon,
  Palette,
  RefreshCw,
  Save,
  ShieldCheck,
  Sun,
  User,
  Zap,
} from 'lucide-react';
import {
  combinedProfileSettingsSchema,
  type CombinedProfileSettingsFormValues,
} from '@/schemas/profile';
import {
  useProfile,
  useUpdateProfile,
  useHeartRateZones,
  useUpdateHeartRateZones,
} from '@/hooks/useProfile';
import {
  useConnectProvider,
  useDisconnectProvider,
  useProviders,
} from '@/hooks/useProviders';
import { useSyncStatus, useTriggerSync } from '@/hooks/useSyncPolling';
import { useTheme, type Theme } from '@/hooks/useTheme';
import { Provider, Sex, SyncState } from '@/types/enums';
import { SyncStatusBadge } from '@/components/common/SyncStatusBadge';
import { ProviderCard } from '@/components/settings/ProviderCard';
import { ConfirmModal } from '@/components/common/ConfirmModal';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { PROVIDER_CONNECT_NAME, providerCanSync } from '@/utils/providers';
import { cn } from '@/lib/utils';

export type SettingsTab = 'integrations' | 'appearance' | 'biometrics' | 'account';

const SETTINGS_TABS: { id: SettingsTab; label: string; icon: React.ElementType }[] = [
  { id: 'integrations', label: 'Integrations & Sync', icon: Zap },
  { id: 'appearance', label: 'Appearance', icon: Palette },
  { id: 'biometrics', label: 'Biometrics & Zones', icon: User },
  { id: 'account', label: 'Manage Account', icon: ShieldCheck },
];

const HR_ZONE_FIELDS = [
  { name: 'zone1_bpm' as const, label: 'Zone 1 (Recovery)', placeholder: '110' },
  { name: 'zone2_bpm' as const, label: 'Zone 2 (Aerobic Base)', placeholder: '135' },
  { name: 'zone3_bpm' as const, label: 'Zone 3 (Tempo)', placeholder: '152' },
  { name: 'zone4_bpm' as const, label: 'Zone 4 (Threshold)', placeholder: '168' },
  { name: 'zone5_bpm' as const, label: 'Zone 5 (Maximal)', placeholder: '182' },
];

export const SettingsPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const currentTabParam = searchParams.get('tab');
  const activeTab: SettingsTab =
    currentTabParam === 'appearance' ||
    currentTabParam === 'biometrics' ||
    currentTabParam === 'account'
      ? currentTabParam
      : 'integrations';

  const { signOut } = useClerk();
  const { theme, setTheme, resolvedTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';

  const [signOutModalOpen, setSignOutModalOpen] = React.useState(false);
  const [disconnectProviderTarget, setDisconnectProviderTarget] =
    React.useState<Provider | null>(null);
  const [syncLimit, setSyncLimit] = React.useState<number>(50);

  const { data: profile, isLoading: loadingProfile } = useProfile();
  const { data: hrZones, isLoading: loadingHrZones } = useHeartRateZones();
  const { mutate: updateProfile, isPending: savingProfile } = useUpdateProfile();
  const { mutate: updateHrZones, isPending: savingHrZones } = useUpdateHeartRateZones();
  const { mutate: disconnectProviderMut, isPending: disconnecting } = useDisconnectProvider();

  const {
    data: providers,
    isLoading: loadingProviders,
    isError: providersFailed,
  } = useProviders();
  const connectedProvider = providers?.find((p) => p.connected)?.provider ?? null;
  const {
    mutate: connectProvider,
    isPending: connecting,
    variables: connectingProvider,
  } = useConnectProvider();

  const { data: syncStatus } = useSyncStatus(connectedProvider);
  const { mutate: triggerSync, isPending: isSyncing } = useTriggerSync();
  const syncBusy = isSyncing || syncStatus?.state === SyncState.SYNCING;

  const isSaving = savingProfile || savingHrZones;

  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors, isDirty },
  } = useForm<CombinedProfileSettingsFormValues>({
    resolver: zodResolver(combinedProfileSettingsSchema),
    defaultValues: {
      age: null,
      sex: null,
      height_cm: null,
      max_hr: null,
      zone1_bpm: null,
      zone2_bpm: null,
      zone3_bpm: null,
      zone4_bpm: null,
      zone5_bpm: null,
    },
  });

  // Prepopulate form when profile and HR zones data arrive
  React.useEffect(() => {
    if (profile || hrZones) {
      reset({
        age: profile?.age ?? null,
        sex: profile?.sex ?? null,
        height_cm: profile?.height_cm ?? null,
        max_hr: profile?.max_hr ?? null,
        zone1_bpm: hrZones?.zone1_bpm ?? null,
        zone2_bpm: hrZones?.zone2_bpm ?? null,
        zone3_bpm: hrZones?.zone3_bpm ?? null,
        zone4_bpm: hrZones?.zone4_bpm ?? null,
        zone5_bpm: hrZones?.zone5_bpm ?? null,
      });
    }
  }, [profile, hrZones, reset]);

  const onProfileSubmit = (data: CombinedProfileSettingsFormValues) => {
    // 1. Update Biometrics
    updateProfile({
      age: data.age ?? null,
      sex: data.sex ?? null,
      height_cm: data.height_cm ?? null,
      max_hr: data.max_hr ?? null,
    });

    // 2. Update HR Zones if provided
    if (
      data.zone1_bpm != null &&
      data.zone2_bpm != null &&
      data.zone3_bpm != null &&
      data.zone4_bpm != null &&
      data.zone5_bpm != null
    ) {
      updateHrZones({
        zone1_bpm: data.zone1_bpm,
        zone2_bpm: data.zone2_bpm,
        zone3_bpm: data.zone3_bpm,
        zone4_bpm: data.zone4_bpm,
        zone5_bpm: data.zone5_bpm,
      });
    }
  };

  const handleDisconnectConfirm = () => {
    if (!disconnectProviderTarget) return;
    disconnectProviderMut(disconnectProviderTarget, {
      onSuccess: () => setDisconnectProviderTarget(null),
    });
  };

  const handleTriggerManualSync = () => {
    if (!connectedProvider) return;
    triggerSync({ provider: connectedProvider, params: { limit: syncLimit } });
  };

  const handleTabChange = (tab: SettingsTab) => {
    setSearchParams({ tab });
  };

  return (
    <div className="space-y-6 sm:space-y-8 pb-16">
      {/* Page Header */}
      <div>
        <h1 className="text-xl sm:text-3xl font-bold tracking-tight text-foreground">
          Settings
        </h1>
        <p className="hidden sm:block text-sm text-muted-foreground mt-0.5">
          Connections, appearance, heart rate zones and account
        </p>
      </div>

      {/* Categorized Tab Bar (Mobile scrollable, desktop 4-grid) */}
      <div
        role="tablist"
        aria-label="Settings sections"
        className="flex items-center gap-1.5 overflow-x-auto no-scrollbar sm:grid sm:grid-cols-4 p-1.5 rounded-2xl bg-muted/60 border border-border"
      >
        {SETTINGS_TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;

          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => handleTabChange(tab.id)}
              className={cn(
                'flex min-h-[44px] items-center justify-center gap-2 px-3.5 py-2.5 rounded-sm text-xs sm:text-sm font-semibold transition-all duration-150 active:scale-[0.97] whitespace-nowrap touch-manipulation cursor-pointer flex-1 sm:flex-initial focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-hidden',
                isActive
                  ? 'bg-primary/10 text-primary border border-primary/25'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted'
              )}
            >
              <Icon
                className={cn(
                  'h-4 w-4 shrink-0 transition-colors',
                  isActive ? 'text-primary' : 'text-muted-foreground'
                )}
              />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* TAB 1: INTEGRATIONS & SYNC */}
      {activeTab === 'integrations' && (
        <section className="space-y-5">
          <div className="rounded-md border border-border bg-card p-4 sm:p-6 space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-border">
              <div className="flex items-center gap-2.5">
                <div className="rounded-sm bg-primary/10 text-primary p-2">
                  <Zap className="h-5 w-5 fill-current" />
                </div>
                <div>
                  <h2 className="text-sm sm:text-base font-semibold text-foreground">
                    Connected Fitness Providers
                  </h2>
                  <p className="text-xs text-muted-foreground">
                    Connect Strava, Garmin Connect or Intervals.icu to import your runs
                  </p>
                </div>
              </div>

              {connectedProvider && (
                <SyncStatusBadge
                  state={syncStatus?.state}
                  providerName={PROVIDER_CONNECT_NAME[connectedProvider]}
                />
              )}
            </div>

            {loadingProviders ? (
              <div className="flex h-32 items-center justify-center">
                <LoadingSpinner size="md" label="Loading providers..." />
              </div>
            ) : providersFailed ? (
              <p className="text-xs text-destructive">
                Couldn't load your fitness providers. Refresh the page to try again.
              </p>
            ) : !providers || providers.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No fitness providers are available right now.
              </p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {providers.map((status) => (
                  <ProviderCard
                    key={status.provider}
                    status={status}
                    blockedBy={
                      connectedProvider && connectedProvider !== status.provider
                        ? connectedProvider
                        : null
                    }
                    connecting={connecting && connectingProvider === status.provider}
                    onConnect={() => connectProvider(status.provider)}
                    onDisconnect={() => setDisconnectProviderTarget(status.provider)}
                  >
                    {providerCanSync(status) ? (
                      <div className="flex items-center gap-2 pt-2 border-t border-border/60">
                        <Select
                          value={String(syncLimit)}
                          onValueChange={(val) => setSyncLimit(Number(val))}
                        >
                          <SelectTrigger className="w-[110px] h-9 text-xs font-semibold">
                            <SelectValue placeholder="Limit" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="20">Last 20</SelectItem>
                            <SelectItem value="50">Last 50</SelectItem>
                            <SelectItem value="100">Last 100</SelectItem>
                          </SelectContent>
                        </Select>

                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={handleTriggerManualSync}
                          disabled={syncBusy}
                          className="min-h-[44px] sm:min-h-[36px] flex-1 text-xs touch-manipulation font-medium"
                        >
                          <RefreshCw
                            className={cn('h-3.5 w-3.5 mr-1.5', syncBusy && 'animate-spin')}
                          />
                          Trigger Sync
                        </Button>
                      </div>
                    ) : (
                      <p className="flex items-start gap-2 pt-3 border-t border-border/60 text-xs text-muted-foreground leading-relaxed">
                        <Info className="h-4 w-4 shrink-0 mt-px" />
                        <span>
                          New runs arrive on their own after your watch syncs with{' '}
                          {PROVIDER_CONNECT_NAME[status.provider]}. Runs recorded before you
                          connected aren't imported.
                        </span>
                      </p>
                    )}
                  </ProviderCard>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {/* TAB 2: APPEARANCE & THEME */}
      {activeTab === 'appearance' && (
        <section className="space-y-5">
          <div className="rounded-md border border-border bg-card p-4 sm:p-6 space-y-4">
            <div className="flex items-center gap-2.5 pb-3 border-b border-border">
              <div className="rounded-sm bg-primary/10 text-primary p-2">
                <Palette className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-sm sm:text-base font-semibold text-foreground">
                  Appearance & Theme Mode
                </h2>
                <p className="text-xs text-muted-foreground">
                  Select your interface color scheme
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {[
                {
                  id: 'light' as Theme,
                  label: 'Light Mode',
                  desc: 'High-contrast clean athletic canvas',
                  icon: Sun,
                },
                {
                  id: 'dark' as Theme,
                  label: 'Dark Mode',
                  desc: 'Deep carbon cockpit with orange highlights',
                  icon: Moon,
                },
                {
                  id: 'system' as Theme,
                  label: 'System Theme',
                  desc: 'Syncs with device operating system',
                  icon: Laptop,
                },
              ].map((mode) => {
                const Icon = mode.icon;
                const isSelected = theme === mode.id;

                return (
                  <button
                    key={mode.id}
                    type="button"
                    onClick={() => setTheme(mode.id)}
                    className={cn(
                      'group flex min-h-[56px] items-center gap-3.5 rounded-sm border p-3.5 text-left transition-all duration-150 active:scale-[0.98] touch-manipulation cursor-pointer',
                      isSelected
                        ? 'border-primary bg-primary/5'
                        : 'border-border bg-muted/40 hover:border-border hover:bg-muted/80'
                    )}
                  >
                    <div
                      className={cn(
                        'flex h-10 w-10 shrink-0 items-center justify-center rounded-sm transition-colors',
                        isSelected
                          ? 'bg-primary text-primary-foreground font-bold'
                          : 'bg-background text-muted-foreground group-hover:text-foreground'
                      )}
                    >
                      <Icon className="h-5 w-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between">
                        <span
                          className={cn(
                            'text-sm font-semibold block leading-tight',
                            isSelected ? 'text-primary' : 'text-foreground'
                          )}
                        >
                          {mode.label}
                        </span>
                        {isSelected && (
                          <span className="h-2 w-2 rounded-sm bg-primary shrink-0" />
                        )}
                      </div>
                      <span className="text-xs text-muted-foreground block mt-0.5 truncate">
                        {mode.desc}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </section>
      )}

      {/* TAB 3: BIOMETRICS & ZONES */}
      {activeTab === 'biometrics' && (
        <section className="space-y-5">
          <div className="rounded-md border border-border bg-card p-4 sm:p-6">
            <div className="flex items-center gap-2.5 pb-3 border-b border-border mb-5 sm:mb-6">
              <div className="rounded-sm bg-primary/10 text-primary p-2">
                <User className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-sm sm:text-base font-semibold text-foreground">
                  Heart Rate & Zones
                </h2>
                <p className="text-xs text-muted-foreground">
                  Used for race predictions and workout summaries
                </p>
              </div>
            </div>

            {loadingProfile || loadingHrZones ? (
              <div className="flex h-44 items-center justify-center">
                <LoadingSpinner size="md" label="Loading your profile..." />
              </div>
            ) : (
              <form onSubmit={handleSubmit(onProfileSubmit)} className="space-y-6">
                {/* General Biometrics */}
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-foreground">
                      Age (years)
                    </label>
                    <Input
                      type="number"
                      {...register('age')}
                      placeholder="e.g. 28"
                      className="min-h-[44px] sm:min-h-[36px]"
                    />
                    {errors.age && (
                      <p className="text-xs text-destructive">
                        {errors.age.message}
                      </p>
                    )}
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-foreground">
                      Sex
                    </label>
                    <Controller
                      control={control}
                      name="sex"
                      render={({ field }) => (
                        <Select
                          value={field.value || 'none'}
                          onValueChange={(val) =>
                            field.onChange(val === 'none' ? null : (val as Sex))
                          }
                        >
                          <SelectTrigger className="min-h-[44px] sm:min-h-[36px]">
                            <SelectValue placeholder="Not Specified" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="none">Not Specified</SelectItem>
                            <SelectItem value={Sex.MALE}>Male</SelectItem>
                            <SelectItem value={Sex.FEMALE}>Female</SelectItem>
                          </SelectContent>
                        </Select>
                      )}
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-foreground">
                      Height (cm)
                    </label>
                    <Input
                      type="number"
                      step="0.5"
                      {...register('height_cm')}
                      placeholder="e.g. 178"
                      className="min-h-[44px] sm:min-h-[36px]"
                    />
                    {errors.height_cm && (
                      <p className="text-xs text-destructive">
                        {errors.height_cm.message}
                      </p>
                    )}
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-xs font-semibold text-foreground">
                      Max Heart Rate (bpm)
                    </label>
                    <Input
                      type="number"
                      {...register('max_hr')}
                      placeholder="e.g. 192"
                      className="min-h-[44px] sm:min-h-[36px]"
                    />
                    {errors.max_hr && (
                      <p className="text-xs text-destructive">
                        {errors.max_hr.message}
                      </p>
                    )}
                  </div>
                </div>

                {/* Custom Heart Rate Zones (BPM lower bounds) */}
                <div className="pt-4 border-t border-border space-y-3">
                  <div>
                    <h3 className="text-sm font-semibold text-foreground flex items-center gap-1.5">
                      <Heart className="h-4 w-4 text-red-500 fill-red-500" />
                      Custom Heart Rate Zones (Lower Bounds in BPM)
                    </h3>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Must strictly increase: Zone 1 &lt; Zone 2 &lt; Zone 3 &lt; Zone 4 &lt; Zone 5
                    </p>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-5 gap-3">
                    {HR_ZONE_FIELDS.map((zone) => (
                      <div key={zone.name} className="space-y-1">
                        <label className="text-xs font-medium text-muted-foreground">
                          {zone.label}
                        </label>
                        <Input
                          type="number"
                          {...register(zone.name)}
                          placeholder={zone.placeholder}
                          className="min-h-[44px] sm:min-h-[36px]"
                        />
                        {errors[zone.name] && (
                          <p className="text-xs text-destructive">
                            {errors[zone.name]?.message}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                {/* Save Button */}
                <div className="flex justify-end pt-4 border-t border-border">
                  <Button
                    type="submit"
                    size="default"
                    disabled={isSaving || !isDirty}
                    className="w-full sm:w-auto min-h-[44px] touch-manipulation font-semibold rounded-sm active:scale-[0.97] transition-all duration-150"
                  >
                    {isSaving ? (
                      <LoadingSpinner size="sm" className="p-0 mr-1.5" />
                    ) : (
                      <Save className="h-4 w-4 mr-1.5" />
                    )}
                    Save Biometrics & Zones
                  </Button>
                </div>
              </form>
            )}
          </div>
        </section>
      )}

      {/* TAB 4: MANAGE ACCOUNT & SECURITY */}
      {activeTab === 'account' && (
        <section className="space-y-5">
          <div className="rounded-md border border-border bg-card p-4 sm:p-6 space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-border">
              <div className="flex items-center gap-2.5">
                <div className="rounded-sm bg-primary/10 text-primary p-2">
                  <ShieldCheck className="h-5 w-5" />
                </div>
                <div>
                  <h2 className="text-sm sm:text-base font-semibold text-foreground">
                    Manage Account & Security
                  </h2>
                  <p className="text-xs text-muted-foreground">
                    Authentication credentials, profile security, connected accounts, and active sessions
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setSignOutModalOpen(true)}
                  className="min-h-[38px] text-xs touch-manipulation border-destructive/30 text-destructive hover:bg-destructive/10 gap-1.5 cursor-pointer rounded-sm active:scale-[0.97] transition-all duration-150"
                >
                  <LogOut className="h-3.5 w-3.5" />
                  <span>Sign Out</span>
                </Button>
              </div>
            </div>

            {/* Embedded Clerk UserProfile component with brand palette */}
            <div className="w-full flex justify-center py-1">
              <div className="w-full overflow-hidden rounded-sm border border-border bg-card">
                <UserProfile
                  routing="hash"
                  appearance={{
                    variables: {
                      colorPrimary: '#FC5200',
                      colorBackground: isDark ? '#111622' : '#FFFFFF',
                      colorText: isDark ? '#F8FAFC' : '#0F172A',
                      colorTextSecondary: isDark ? '#94A3B8' : '#475569',
                      colorInputBackground: isDark ? '#090B10' : '#F8FAFC',
                      colorBorder: isDark ? '#232B3E' : '#CBD5E1',
                      borderRadius: '0.375rem',
                    },
                    elements: {
                      rootBox: 'w-full shadow-none',
                      cardBox: 'w-full shadow-none border-0',
                      card: 'w-full border-0 shadow-none bg-transparent',
                      navbar: 'border-r border-border bg-card',
                      navbarButton:
                        'text-muted-foreground hover:text-foreground hover:bg-muted data-[active=true]:text-primary data-[active=true]:font-semibold',
                      headerTitle: 'text-foreground font-semibold',
                      headerSubtitle: 'text-muted-foreground',
                      profileSectionTitleText: 'text-foreground font-semibold',
                      profileSectionPrimaryButton: 'text-primary hover:text-primary/80',
                      formButtonPrimary:
                        'bg-primary hover:bg-[#E04900] text-primary-foreground font-medium rounded-sm',
                      formFieldLabel: 'text-foreground font-medium',
                      formFieldInput: 'bg-background border-input text-foreground rounded-sm',
                      userPreviewMainIdentifier: 'text-foreground font-semibold',
                      userPreviewSecondaryIdentifier: 'text-muted-foreground',
                      breadcrumbsItem: 'text-muted-foreground hover:text-foreground',
                      breadcrumbsItem__active: 'text-foreground font-semibold',
                    },
                  }}
                />
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Disconnect Provider Confirmation Modal */}
      <ConfirmModal
        open={Boolean(disconnectProviderTarget)}
        onOpenChange={(open) => !open && setDisconnectProviderTarget(null)}
        title={`Disconnect ${disconnectProviderTarget ? PROVIDER_CONNECT_NAME[disconnectProviderTarget] : ''}`}
        description="Are you sure you want to disconnect this provider? New workouts will not be imported until you connect a provider again. Imported workouts are kept."
        confirmLabel="Disconnect"
        variant="destructive"
        loading={disconnecting}
        onConfirm={handleDisconnectConfirm}
      />

      {/* Sign Out Confirmation Modal */}
      <ConfirmModal
        open={signOutModalOpen}
        onOpenChange={setSignOutModalOpen}
        title="Sign Out of Session"
        description="Are you sure you want to sign out of RunSummarizer? You will need to sign in again to access your workouts."
        confirmLabel="Sign Out"
        variant="default"
        onConfirm={() => {
          signOut({ redirectUrl: '/sign-in' });
        }}
      />
    </div>
  );
};

export default SettingsPage;