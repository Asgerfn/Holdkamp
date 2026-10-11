import os
import sys
from pathlib import Path


# Gør projektets rodmappe tilgængelig for imports,
# når scriptet køres som: python scripts/run_match_sync.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


from database import get_connection
from active_team_sync import sync_club_active_teams


SEASON_ID = int(
    os.getenv(
        "CURRENT_SEASON",
        "2026",
    )
)


def get_active_club_ids(
    season_id,
):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT DISTINCT
                club_id
            FROM dbo.club_dashboard_teams
            WHERE
                season_id = ?
                AND is_active = 1
            ORDER BY
                club_id
            """,
            season_id,
        )

        return [
            int(row.club_id)
            for row in cursor.fetchall()
        ]

    finally:
        cursor.close()
        conn.close()


def main():

    print()
    print("=" * 100)
    print("NIGHTLY MATCH SYNC")
    print("=" * 100)
    print(
        "Season:",
        SEASON_ID,
    )

    club_ids = get_active_club_ids(
        SEASON_ID
    )

    print(
        "Klubber med aktive hold:",
        len(club_ids),
    )

    totals = {
        "clubs": len(club_ids),
        "successful_clubs": 0,
        "failed_clubs": 0,
        "active_teams": 0,
        "matches": 0,
        "detail_matches": 0,
        "games": 0,
        "skipped_no_result": 0,
        "skipped_existing_details": 0,
        "refreshed_changed_result": 0,
        "failed_matches": 0,
    }

    club_errors = []

    for club_id in club_ids:

        print()
        print("=" * 100)
        print(
            f"SYNC CLUB {club_id}"
        )
        print("=" * 100)

        try:

            result = sync_club_active_teams(
                club_id=club_id,
                season_id=SEASON_ID,
            )

            totals[
                "successful_clubs"
            ] += 1

            for key in (
                "active_teams",
                "matches",
                "detail_matches",
                "games",
                "skipped_no_result",
                "skipped_existing_details",
                "refreshed_changed_result",
                "failed_matches",
            ):

                totals[key] += int(
                    result.get(
                        key,
                        0,
                    )
                    or 0
                )

        except Exception as exc:

            totals[
                "failed_clubs"
            ] += 1

            club_errors.append(
                {
                    "club_id": club_id,
                    "error": str(exc),
                }
            )

            print()
            print(
                f"FEJL VED CLUB {club_id}:"
            )
            print(exc)

    print()
    print("=" * 100)
    print("NIGHTLY SYNC SUMMARY")
    print("=" * 100)

    print(
        "Klubber:",
        totals["clubs"],
    )

    print(
        "Klubber OK:",
        totals["successful_clubs"],
    )

    print(
        "Klubber med fejl:",
        totals["failed_clubs"],
    )

    print(
        "Aktive hold:",
        totals["active_teams"],
    )

    print(
        "Holdkampe:",
        totals["matches"],
    )

    print(
        "Kampdetaljer hentet:",
        totals["detail_matches"],
    )

    print(
        "Delkampe fundet:",
        totals["games"],
    )

    print(
        "Uspillede sprunget over:",
        totals["skipped_no_result"],
    )

    print(
        "Eksisterende detaljer sprunget over:",
        totals["skipped_existing_details"],
    )

    print(
        "Ændrede resultater genhentet:",
        totals["refreshed_changed_result"],
    )

    print(
        "Kampe med fejl:",
        totals["failed_matches"],
    )

    if club_errors:

        print()
        print("KLUBFEJL")

        for error in club_errors:

            print(
                f"- {error['club_id']}: "
                f"{error['error']}"
            )

    print("=" * 100)

    if (
        totals["failed_clubs"] > 0
        or
        totals["failed_matches"] > 0
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

