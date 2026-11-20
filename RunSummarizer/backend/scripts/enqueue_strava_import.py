"""Queue Strava activities for the import worker, as a webhook event would.

An activity the user already has stored is left untouched: the worker only adds new
ones. The athlete ID is in the owner's Strava profile URL, the activity ID in the
activity's URL. Start the worker to import them:

  python -m scripts.enqueue_strava_import <athlete_id> <activity_id> [<activity_id> ...]
  python -m app.worker
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

import anyio

from app.db.client import dispose_engine
from app.db.factory import RepositoriesFactory, transaction
from app.domain.enums import Provider
from app.providers.strava.activity_keys import strava_activity_key


async def enqueue_strava_imports(
    athlete_id: int,
    activity_ids: Sequence[int],
    *,
    transaction: RepositoriesFactory = transaction,
) -> str:
    """Queue a webhook item for each of ``activity_ids``, owned by the user who connected
    the Strava athlete ``athlete_id``, and return that user's ID.

    Raises ``LookupError``, queueing nothing, when no user connected the athlete.
    """
    now = datetime.now(UTC)
    async with transaction() as repos:
        user_id = await repos.providers.get_by_provider_user_id(Provider.STRAVA, str(athlete_id))
        if user_id is None:
            raise LookupError(f"No user has connected Strava athlete {athlete_id}")
        for activity_id in activity_ids:
            await repos.import_queue.enqueue_webhook(
                user_id, Provider.STRAVA, strava_activity_key(activity_id), now=now
            )
    return user_id


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("athlete_id", type=int, help="Strava athlete ID of the owner.")
    parser.add_argument(
        "activity_ids", type=int, nargs="+", metavar="activity_id", help="Strava activity ID."
    )
    args = parser.parse_args()

    try:
        user_id = await enqueue_strava_imports(args.athlete_id, args.activity_ids)
    except LookupError as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        await dispose_engine()

    print(
        f"Queued {len(args.activity_ids)} activities for user {user_id}. "
        "Run python -m app.worker to import them."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(anyio.run(main))
