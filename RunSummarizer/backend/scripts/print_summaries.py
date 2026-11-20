"""Print summaries for recent activities (CLI helper)."""

import anyio

from app.db.client import dispose_engine
from app.db.factory import RepositoriesFactory, transaction
from app.summaries.summary import summarize


async def print_recent_summaries(
    limit: int = 3,
    *,
    transaction: RepositoriesFactory = transaction,
) -> None:
    async with transaction() as repos:
        records = await repos.activities.list_activities(limit=limit, include_laps=True)

    for record in records:
        print(summarize(record.activity).text)
        print("-" * 70 + "\n")


async def main():
    try:
        await print_recent_summaries()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    anyio.run(main)
