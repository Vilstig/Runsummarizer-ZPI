"""Re-run ML lap classification and regenerate summaries for all activities.

Use when the lap classifier model changes.
"""

import anyio

from app.db.client import dispose_engine
from app.db.factory import RepositoriesFactory, transaction
from app.domain.models import Activity, ActivityRecord, Summary
from app.ml.classifier import classify_laps
from app.summaries.editing import is_edited
from app.summaries.segmentation import segment_activity
from app.summaries.summary import summarize
from scripts.helpers import batch_update_activities


async def reprocess_activities(
    *,
    batch_size: int = 100,
    limit: int | None = None,
    dry_run: bool = False,
    transaction: RepositoriesFactory = transaction,
) -> int:
    """Re-run ML lap classification and regenerate summaries.

    Use when the lap classifier model changes. Lap metrics are taken from the
    stored activity; lap types, segments, training type, and summary are rebuilt
    with the current model and summary logic. A summary the user edited is kept.
    """

    def transform(record: ActivityRecord) -> tuple[Activity, Summary]:
        if not record.activity.laps:
            raise ValueError("no laps to classify")
        activity = segment_activity(classify_laps(record.activity))
        summary = record.summary if is_edited(record.summary) else summarize(activity)
        return activity, summary

    return await batch_update_activities(
        transform=transform,
        transaction=transaction,
        batch_size=batch_size,
        limit=limit,
        dry_run=dry_run,
        error_label="reprocess",
    )


async def main():
    try:
        count = await reprocess_activities()
    finally:
        await dispose_engine()
    print(f"Reprocessed {count} activities.")


if __name__ == "__main__":
    anyio.run(main)
