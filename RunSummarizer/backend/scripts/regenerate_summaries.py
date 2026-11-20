"""Regenerate stored summaries for all activities.

Use when summary generation logic changes.
"""

import anyio

from app.db.client import dispose_engine
from app.db.factory import RepositoriesFactory, transaction
from app.domain.models import Activity, ActivityRecord, Summary
from app.summaries.summary import summarize
from scripts.helpers import batch_update_activities


async def regenerate_summaries(
    *,
    batch_size: int = 100,
    limit: int | None = None,
    dry_run: bool = False,
    transaction: RepositoriesFactory = transaction,
) -> int:
    """Regenerate and persist summaries for activities using current summary logic.
    Summaries the user edited are left as they are."""

    def transform(record: ActivityRecord) -> tuple[Activity, Summary]:
        return record.activity, summarize(record.activity)

    return await batch_update_activities(
        transform=transform,
        transaction=transaction,
        batch_size=batch_size,
        limit=limit,
        dry_run=dry_run,
        error_label="regenerate",
        skip_edited=True,
    )


async def main():
    try:
        count = await regenerate_summaries()
    finally:
        await dispose_engine()
    print(f"Regenerated {count} summaries.")


if __name__ == "__main__":
    anyio.run(main)
