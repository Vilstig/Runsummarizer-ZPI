import React from 'react';
import { useParams, useNavigate, useLocation, Link } from 'react-router-dom';
import {
  ArrowLeft,
  Calendar,
  Compass,
  Heart,
  HeartPulse,
  Mountain,
  Pencil,
  RotateCcw,
  Timer,
  Trash2,
  Zap,
} from 'lucide-react';
import {
  useActivity,
  useDeleteActivity,
  useEditSummary,
  useResetLaps,
  useResetSummary,
  useUpdateLaps,
} from '@/hooks/useActivity';
import { MetricTile } from '@/components/common/MetricTile';
import { RunTypeBadge } from '@/components/activity/RunTypeBadge';
import { ProviderBadge } from '@/components/common/ProviderBadge';
import { GarminAttribution } from '@/components/common/GarminAttribution';
import { LapTable } from '@/components/activity/LapTable';
import { HrZoneChart } from '@/components/activity/HrZoneChart';
import { PaceHrChart } from '@/components/activity/PaceHrChart';
import { ConfirmModal } from '@/components/common/ConfirmModal';
import { CopyButton } from '@/components/common/CopyButton';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { Button } from '@/components/ui/button';
import { LapType, SegmentRole, TextPolicy } from '@/types/enums';
import { SEGMENT_ROLE_COLORS } from '@/utils/colors';
import { withGarminAttribution } from '@/utils/attribution';
import {
  formatDate,
  formatDistance,
  formatDuration,
  formatElevation,
  formatHeartRate,
  formatPace,
} from '@/utils/formatters';
import { cn } from '@/lib/utils';

export const ActivityDetailPage: React.FC = () => {
  const { activityId } = useParams<{ activityId: string }>();
  const navigate = useNavigate();
  const location = useLocation();

  const [deleteModalOpen, setDeleteModalOpen] = React.useState(false);
  const [resetLapsModalOpen, setResetLapsModalOpen] = React.useState(false);
  const [restoreSummaryModalOpen, setRestoreSummaryModalOpen] = React.useState(false);
  const [isEditingSummary, setIsEditingSummary] = React.useState(false);
  const [summaryDraft, setSummaryDraft] = React.useState('');

  const {
    data: activity,
    isLoading,
    isError,
  } = useActivity(activityId || '');

  const { mutate: updateLaps, isPending: isUpdatingLaps } = useUpdateLaps(
    activityId || ''
  );
  const { mutate: resetLaps, isPending: isResettingLaps } = useResetLaps(
    activityId || ''
  );
  const { mutate: editSummary, isPending: isSavingSummary } = useEditSummary(
    activityId || ''
  );
  const { mutate: resetSummary, isPending: isResettingSummary } = useResetSummary(
    activityId || ''
  );
  const { mutate: deleteAct, isPending: isDeleting } = useDeleteActivity();

  const summaryInputRef = React.useRef<HTMLTextAreaElement>(null);

  // Fit the edit box to its text so the whole summary is visible while editing
  React.useLayoutEffect(() => {
    const input = summaryInputRef.current;
    if (!input) return;
    input.style.height = 'auto';
    input.style.height = `${input.scrollHeight}px`;
  }, [summaryDraft, isEditingSummary]);

  // Focus the edit box (cursor at the end) when edit mode opens
  React.useEffect(() => {
    const input = summaryInputRef.current;
    if (!isEditingSummary || !input) return;
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }, [isEditingSummary]);

  React.useEffect(() => {
    if (activity?.summary) {
      setSummaryDraft(activity.summary);
    }
  }, [activity?.summary]);

  const handleBack = () => {
    // 'default' key means this page was opened directly, with no in-app history
    if (location.key === 'default') {
      navigate('/activities');
    } else {
      navigate(-1);
    }
  };

  const handleDelete = () => {
    if (!activityId) return;
    deleteAct(activityId, {
      onSuccess: () => {
        setDeleteModalOpen(false);
        navigate('/activities');
      },
    });
  };

  const handleLapSave = (laps: { lapIndex: number; typeId: LapType }[]) => {
    const policy = activity?.summaryTextEdited ? TextPolicy.KEEP : TextPolicy.REGENERATE;
    updateLaps({
      laps: laps.map((l) => ({ lapIndex: l.lapIndex, typeId: l.typeId })),
      textPolicy: policy,
    });
  };

  const handleResetLaps = () => {
    const policy = activity?.summaryTextEdited ? TextPolicy.KEEP : TextPolicy.REGENERATE;
    resetLaps(
      { textPolicy: policy },
      {
        onSuccess: () => setResetLapsModalOpen(false),
      }
    );
  };

  const handleSaveSummary = () => {
    if (!summaryDraft.trim()) return;
    editSummary(
      { text: summaryDraft.trim() },
      {
        onSuccess: () => setIsEditingSummary(false),
      }
    );
  };

  if (isLoading) {
    return (
      <div className="flex h-96 items-center justify-center">
        <LoadingSpinner size="lg" label="Loading workout..." />
      </div>
    );
  }

  if (isError || !activity) {
    return (
      <div className="rounded-2xl border border-destructive/20 bg-destructive/10 p-6 sm:p-8 text-center">
        <h2 className="text-lg font-bold text-destructive">Activity Not Found</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          The requested activity might have been deleted or is not associated with your account.
        </p>
        <Link
          to="/activities"
          className="mt-4 inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground touch-manipulation focus-visible:ring-2 focus-visible:ring-primary"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Activities
        </Link>
      </div>
    );
  }

  const { processed_data } = activity;
  const attributed = [activity];

  return (
    <div className="space-y-6 sm:space-y-8 pb-16">
      {/* Top Header: Back navigation, Title, Source, Badges */}
      <div className="space-y-3">
        <button
          type="button"
          onClick={handleBack}
          className="inline-flex min-h-[44px] items-center gap-1.5 text-xs font-semibold text-muted-foreground hover:text-foreground transition-colors touch-manipulation focus-visible:ring-2 focus-visible:ring-primary rounded-lg px-1 -ml-1 cursor-pointer"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </button>

        <div className="space-y-1.5">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h1 className="text-xl sm:text-3xl font-extrabold tracking-tight text-foreground">
              {processed_data.name || 'Running Workout'}
            </h1>
            <ProviderBadge source={activity.source} deviceName={processed_data.deviceName} />
            <RunTypeBadge
              typeId={processed_data.trainingTypeId}
              typeName={processed_data.trainingTypeDisplay}
              size="md"
            />
          </div>
          <p className="text-xs text-muted-foreground flex items-center gap-1.5">
            <Calendar className="h-3.5 w-3.5" />
            {formatDate(processed_data.startTimeLocal)}
          </p>
        </div>
      </div>

      {/* Section 1: Workout summary (AI generated, editable) */}
      <section className="rounded-xl border border-border bg-card p-4 sm:p-6 shadow-xs space-y-3">
        <div className="border-b border-border pb-3">
          <div className="flex items-center justify-between gap-2">
            <div>
              <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                Analysis & Insights
              </span>
              <h2 className="text-base sm:text-lg font-extrabold text-foreground mt-0.5">
                Workout Summary
              </h2>
            </div>

            {!isEditingSummary && (
              <div className="flex items-center gap-1 -mr-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setSummaryDraft(activity.summary || '');
                    setIsEditingSummary(true);
                  }}
                  className="min-h-[44px] sm:min-h-[36px] text-xs text-muted-foreground hover:text-foreground touch-manipulation"
                >
                  <Pencil className="h-3.5 w-3.5 mr-1" />
                  Edit
                </Button>
                {activity.summary && (
                  <CopyButton
                    text={withGarminAttribution(activity.summary, activity, { derived: true })}
                  />
                )}
              </div>
            )}
          </div>
          <GarminAttribution activities={attributed} derived className="mt-1" />
        </div>

        {isEditingSummary ? (
          <div className="space-y-3">
            <textarea
              ref={summaryInputRef}
              value={summaryDraft}
              onChange={(e) => setSummaryDraft(e.target.value)}
              rows={4}
              aria-label="Summary text"
              className="w-full resize-none overflow-hidden rounded-xl border border-border bg-background p-3 text-sm sm:text-base text-foreground focus:outline-hidden focus:ring-1 focus:ring-primary leading-relaxed"
              placeholder="Write your own summary of this workout..."
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              {activity.summaryTextEdited ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setRestoreSummaryModalOpen(true)}
                  disabled={isResettingSummary}
                  className="min-h-[44px] sm:min-h-[36px] text-xs text-muted-foreground hover:text-foreground touch-manipulation -ml-2"
                >
                  <RotateCcw className="h-3.5 w-3.5 mr-1" />
                  {isResettingSummary ? 'Restoring...' : 'Restore AI summary'}
                </Button>
              ) : (
                <span />
              )}
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setIsEditingSummary(false)}
                  className="min-h-[44px] sm:min-h-[36px] text-xs touch-manipulation"
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  size="sm"
                  onClick={handleSaveSummary}
                  disabled={isSavingSummary || !summaryDraft.trim()}
                  className="min-h-[44px] sm:min-h-[36px] text-xs touch-manipulation font-semibold"
                >
                  {isSavingSummary ? 'Saving...' : 'Save'}
                </Button>
              </div>
            </div>
          </div>
        ) : activity.summary ? (
          // Paragraphs come from blank lines in the stored text; single \n stay as line breaks
          <div className="max-w-prose space-y-3 text-sm sm:text-base leading-relaxed text-foreground">
            {activity.summary.split(/\n\s*\n/).map((paragraph, idx) => (
              <p key={idx} className="whitespace-pre-line">
                {paragraph.trim()}
              </p>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            No summary yet. Check the lap types below and save them to generate one.
          </p>
        )}
      </section>

      {/* Section 2: Core Metrics Grid with Tabular Numerals (Compact for Mobile) */}
      <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5 sm:gap-3">
        <MetricTile
          label="Distance"
          value={formatDistance(processed_data.distance)}
          icon={<Compass className="h-4 w-4" />}
        />
        <MetricTile
          label="Duration"
          value={formatDuration(processed_data.duration)}
          icon={<Timer className="h-4 w-4" />}
        />
        <MetricTile
          label="Avg Pace"
          value={formatPace(processed_data.speed)}
          icon={<Zap className="h-4 w-4" />}
        />
        <MetricTile
          label="Avg HR"
          value={formatHeartRate(processed_data.avgHr)}
          icon={<Heart className="h-4 w-4" />}
        />
        <MetricTile
          label="Max HR"
          value={formatHeartRate(processed_data.maxHr)}
          icon={<HeartPulse className="h-4 w-4" />}
        />
        <MetricTile
          label="Elevation"
          value={formatElevation(processed_data.elevationGain)}
          icon={<Mountain className="h-4 w-4" />}
        />
      </section>

      {/* Section 3: Telemetry Charts (Pace & HR Progression + HR Zones) */}
      <section className="space-y-4">
        <div className="space-y-1">
          <h3 className="text-base sm:text-lg font-bold tracking-tight text-foreground">
            Pace & Heart Rate
          </h3>
          <GarminAttribution activities={attributed} />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6">
          <PaceHrChart laps={processed_data.laps || []} />
          <HrZoneChart zones={processed_data.heartRateZones} />
        </div>
      </section>

      {/* Section 4: Segments Breakdown (Detected Phases) */}
      {processed_data.segments && processed_data.segments.length > 0 && (
        <section className="rounded-2xl border border-border bg-card p-4 sm:p-5 shadow-xs space-y-3">
          <div className="space-y-1">
            <h3 className="text-xs sm:text-sm font-semibold text-foreground uppercase tracking-wider">
              Detected Workout Phases
            </h3>
            <GarminAttribution activities={attributed} derived />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5">
            {processed_data.segments.map((seg, idx) => {
              const roleKey = seg.role as SegmentRole;
              const color = SEGMENT_ROLE_COLORS[roleKey] || SEGMENT_ROLE_COLORS[SegmentRole.WORK];
              return (
                <div
                  key={idx}
                  className="rounded-xl border border-border/80 bg-muted/20 p-3 text-xs space-y-1"
                >
                  <div className="flex items-center justify-between font-semibold">
                    <span
                      className={cn(
                        'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs uppercase font-bold border',
                        color.bg,
                        color.text,
                        color.border
                      )}
                    >
                      <span className={cn('h-1 w-1 rounded-full', color.dot)} />
                      {seg.role}
                    </span>
                    <span className="text-muted-foreground tabular-nums text-xs">
                      Laps {seg.startLapIndex + 1}–{seg.endLapIndex + 1}
                    </span>
                  </div>
                  <div className="text-foreground/90 font-medium">{seg.runTypeDisplay}</div>
                  {seg.label && (
                    <div className="text-xs text-primary font-medium">
                      {seg.label}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Section 5: Mobile-First Interactive Laps Table */}
      <section className="space-y-4">
        <div>
          <h3 className="text-base sm:text-lg font-bold tracking-tight text-foreground">
            Laps
          </h3>
          <GarminAttribution activities={attributed} derived className="my-1" />
          <p className="text-xs text-muted-foreground">
            Change a lap type if it was detected wrong. Saving updates the summary.
          </p>
        </div>

        <LapTable
          laps={processed_data.laps || []}
          editable={true}
          onSave={handleLapSave}
          onReset={() => setResetLapsModalOpen(true)}
          isSaving={isUpdatingLaps}
          isResetting={isResettingLaps}
        />
      </section>

      {/* Destructive action kept at the end of the page, away from the summary */}
      <div className="flex justify-center border-t border-border pt-6">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setDeleteModalOpen(true)}
          className="min-h-[44px] sm:min-h-[36px] text-destructive hover:bg-destructive/10 hover:text-destructive touch-manipulation focus-visible:ring-2 focus-visible:ring-destructive"
        >
          <Trash2 className="h-3.5 w-3.5 mr-1" />
          Delete workout
        </Button>
      </div>

      {/* Restore AI Summary Modal */}
      <ConfirmModal
        open={restoreSummaryModalOpen}
        onOpenChange={setRestoreSummaryModalOpen}
        title="Restore AI summary"
        description="Your edited text will be replaced by a newly generated AI summary. This can't be undone."
        confirmLabel="Restore"
        variant="default"
        loading={isResettingSummary}
        onConfirm={() =>
          resetSummary(undefined, {
            onSuccess: () => {
              setRestoreSummaryModalOpen(false);
              setIsEditingSummary(false);
            },
          })
        }
      />

      {/* Reset Laps Modal */}
      <ConfirmModal
        open={resetLapsModalOpen}
        onOpenChange={setResetLapsModalOpen}
        title="Reset Laps"
        description="Are you sure you want to revert all lap changes back to the original device measurements? This will recompute workout summary."
        confirmLabel="Reset Laps"
        variant="default"
        loading={isResettingLaps}
        onConfirm={handleResetLaps}
      />

      {/* Confirmation Modal for Deletion */}
      <ConfirmModal
        open={deleteModalOpen}
        onOpenChange={setDeleteModalOpen}
        title="Delete Workout"
        description="Are you sure you want to delete this activity? This will permanently remove the activity and its summary from your account."
        confirmLabel="Delete"
        variant="destructive"
        loading={isDeleting}
        onConfirm={handleDelete}
      />
    </div>
  );
};

export default ActivityDetailPage;
