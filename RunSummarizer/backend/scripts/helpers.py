from collections.abc import Callable

from app.db.factory import RepositoriesFactory
from app.domain.models import Activity, ActivityRecord, Summary
from app.summaries.editing import is_edited


async def batch_update_activities(
    *,
    transform: Callable[[ActivityRecord], tuple[Activity, Summary] | None],
    transaction: RepositoriesFactory,
    batch_size: int = 100,
    limit: int | None = None,
    dry_run: bool = False,
    error_label: str = "update",
    skip_edited: bool = False,
    user_id: str | None = None,
) -> int:
    """Apply ``transform(record) -> (activity, summary)`` across stored activities, those
    of ``user_id`` only when given, leaving out those whose summary the user edited when
    ``skip_edited``. A record ``transform`` returns None for is left as it is.

    Each page is read and updated in its own transaction; pages committed before a
    crash stay updated.
    """
    updated = 0
    skip = 0
    skipped_edited = 0
    errors: list[dict] = []

    while True:
        batch_limit = batch_size
        if limit is not None:
            remaining = limit - updated - len(errors)
            if remaining <= 0:
                break
            batch_limit = min(batch_size, remaining)

        async with transaction() as repos:
            records = await repos.activities.list_activities(
                user_id=user_id, limit=batch_limit, skip=skip, include_laps=True
            )

            for record in records:
                activity_id = record.activity.key
                if skip_edited and is_edited(record.summary):
                    skipped_edited += 1
                    continue
                try:
                    transformed = transform(record)
                except Exception as exc:  # noqa: BLE001 — record failures; keep the batch going
                    errors.append({"activityId": activity_id, "error": str(exc)})
                    continue
                if transformed is None:
                    continue
                activity, summary = transformed

                if dry_run:
                    text = summary.text
                    preview = text if len(text) <= 80 else f"{text[:80]}..."
                    print(f"{activity_id}: {preview}")
                else:
                    await repos.activities.update_activity(
                        activity_id, activity, summary=summary, user_id=record.user_id
                    )
                updated += 1

                if limit is not None and updated + len(errors) >= limit:
                    break

        skip += len(records)
        if len(records) < batch_limit or (limit is not None and updated + len(errors) >= limit):
            break

    if skipped_edited:
        print(f"Skipped {skipped_edited} activities with a summary edited by the user")
    if errors:
        print(f"Failed to {error_label} {len(errors)} activities:")
        for error in errors:
            print(f"  {error['activityId']}: {error['error']}")

    return updated
