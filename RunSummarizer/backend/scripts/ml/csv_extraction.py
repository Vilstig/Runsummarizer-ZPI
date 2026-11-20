"""Export one user's laps to a CSV for labelling, newest activity first."""

import argparse
from pathlib import Path

import anyio
import pandas as pd

from app.db.client import dispose_engine
from app.db.factory import RepositoriesFactory, transaction
from app.domain.models import Activity
from app.ml.features_extractor import MLFeatureExtractor

PAGE_SIZE = 200  # activities per list_activities call
DEFAULT_OUTPUT = Path("treningi_do_etykietowania.csv")  # relative to the working directory


async def load_activities(
    user_id: str,
    *,
    page_size: int = PAGE_SIZE,
    transaction: RepositoriesFactory = transaction,
) -> list[Activity]:
    """Every stored activity of ``user_id``, newest first."""
    activities = []
    skip = 0
    async with transaction() as repos:
        while page := await repos.activities.list_activities(
            user_id=user_id, limit=page_size, skip=skip, include_laps=True
        ):
            activities.extend(record.activity for record in page)
            skip += len(page)
    return activities


def export_activities_to_csv(activities, output_filename: str | Path = DEFAULT_OUTPUT):
    all_dfs = []

    for act in activities:
        extractor = MLFeatureExtractor(act)
        df_raw = extractor.get_raw_features()

        if not df_raw.empty:
            all_dfs.append(df_raw)

    if all_dfs:
        final_df = pd.concat(all_dfs, ignore_index=True)
        final_df.to_csv(output_filename, index=False)
        print(f"Zapisano {len(final_df)} okrążeń do pliku {output_filename}")
        return final_df

    print("Brak okrążeń do zapisania")
    return pd.DataFrame()


async def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--user-id", required=True, help="Owner of the exported activities.")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"CSV to write (default: {DEFAULT_OUTPUT}).",
    )
    args = parser.parse_args()

    try:
        activities = await load_activities(args.user_id)
    finally:
        await dispose_engine()

    export_activities_to_csv(activities, args.out)


if __name__ == "__main__":
    anyio.run(main)
