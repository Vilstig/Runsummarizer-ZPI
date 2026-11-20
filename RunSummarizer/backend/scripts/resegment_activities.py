"""Segment stored activities again from their stored lap types.

Use when segmentation or the segment stats change. Lap types are not classified again;
summary text the user didn't edit is written again from the new segments. Run with
--dry-run first to see which training types change:

  python -m scripts.resegment_activities [--dry-run] [--user-id USER_ID] [--limit N]
"""

import argparse

import anyio

from app.db.client import dispose_engine
from app.db.factory import RepositoriesFactory, transaction
from app.domain.enums import RunType
from app.domain.models import Activity, ActivityRecord, Summary
from app.summaries.editing import is_edited
from app.summaries.segmentation import segment_activity
from app.summaries.summary import summarize
from scripts.helpers import batch_update_activities


def resegmented(record: ActivityRecord) -> tuple[Activity, Summary] | None:
    """The record's activity segmented again from its lap types, with its segment stats and
    training type, and its summary: the user's edited text, or text written from the new
    segments. None for an activity without laps, which has nothing to segment."""
    if not record.activity.laps:
        return None
    activity = segment_activity(record.activity)
    summary = record.summary if is_edited(record.summary) else summarize(activity)
    return activity, summary


async def resegment_activities(
    *,
    batch_size: int = 100,
    limit: int | None = None,
    dry_run: bool = False,
    user_id: str | None = None,
    transaction: RepositoriesFactory = transaction,
) -> int:
    """Store each activity, those of ``user_id`` only when given, as ``resegmented`` gives
    it, and print the activities whose training type changed. Returns how many were
    resegmented."""
    changes: list[tuple[str, RunType | None, RunType | None]] = []

    def transform(record: ActivityRecord) -> tuple[Activity, Summary] | None:
        result = resegmented(record)
        if result is not None and result[0].training_type != record.activity.training_type:
            changes.append(
                (record.activity.key, record.activity.training_type, result[0].training_type)
            )
        return result

    count = await batch_update_activities(
        transform=transform,
        transaction=transaction,
        batch_size=batch_size,
        limit=limit,
        dry_run=dry_run,
        error_label="resegment",
        user_id=user_id,
    )

    for key, before, after in changes:
        print(f"{key}: {_type_name(before)} -> {_type_name(after)}")
    print(f"Training type changed for {len(changes)} activities")
    return count


def _type_name(run_type: RunType | None) -> str:
    return run_type.display_name if run_type is not None else "none"


async def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Write nothing.")
    parser.add_argument("--user-id", help="Only this user's activities.")
    parser.add_argument("--limit", type=int, help="At most this many activities.")
    args = parser.parse_args()

    try:
        count = await resegment_activities(
            limit=args.limit, dry_run=args.dry_run, user_id=args.user_id
        )
    finally:
        await dispose_engine()
    print(f"{'Would resegment' if args.dry_run else 'Resegmented'} {count} activities.")


if __name__ == "__main__":
    anyio.run(main)
