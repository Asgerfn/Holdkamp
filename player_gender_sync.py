import sys

from database import get_connection

from players_gender_test import (
    get_players_for_gender,
)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8"
    )


# =========================================================
# CONFIG
# =========================================================

CLUB_ID = 1148
SEASON_ID = 2026


# =========================================================
# DATABASE COLUMN
# =========================================================

def ensure_gender_column():

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # Tilføj gender hvis den ikke findes
        cursor.execute(
            """
            IF COL_LENGTH(
                'dbo.badminton_players',
                'gender'
            ) IS NULL
            BEGIN

                ALTER TABLE dbo.badminton_players

                ADD gender NVARCHAR(1) NULL;

            END
            """
        )

        conn.commit()


        # Constraint: kun M / K / NULL
        cursor.execute(
            """
            IF NOT EXISTS (
                SELECT 1
                FROM sys.check_constraints
                WHERE name = 'CK_badminton_players_gender'
            )
            BEGIN

                ALTER TABLE dbo.badminton_players

                ADD CONSTRAINT
                    CK_badminton_players_gender

                CHECK (
                    gender IS NULL
                    OR gender IN ('M', 'K')
                );

            END
            """
        )

        conn.commit()

        print(
            "[OK] gender-kolonnen er klar."
        )

    finally:

        cursor.close()
        conn.close()


# =========================================================
# SCRAPE GENDER
# =========================================================

def scrape_gender(
    club_id,
    season_id,
):

    print()
    print("=" * 100)
    print("HENTER KVINDER")
    print("=" * 100)

    women = get_players_for_gender(
        club_id=club_id,
        season_id=season_id,
        gender="K",
    )


    print()
    print("=" * 100)
    print("HENTER HERRER")
    print("=" * 100)

    men = get_players_for_gender(
        club_id=club_id,
        season_id=season_id,
        gender="M",
    )


    women_ids = {
        player["badminton_id"]
        for player in women
    }

    men_ids = {
        player["badminton_id"]
        for player in men
    }


    overlap = (
        women_ids
        &
        men_ids
    )


    if overlap:

        raise RuntimeError(
            "Nogle spillere findes både "
            "under M og K: "
            +
            ", ".join(
                sorted(overlap)
            )
        )


    gender_map = {}


    for player in women:

        gender_map[
            player["badminton_id"]
        ] = "K"


    for player in men:

        gender_map[
            player["badminton_id"]
        ] = "M"


    return gender_map


# =========================================================
# SAVE TO DATABASE
# =========================================================

def save_gender(
    gender_map
):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        updated = 0
        not_found = 0


        for (
            badminton_id,
            gender
        ) in gender_map.items():

            cursor.execute(
                """
                UPDATE dbo.badminton_players

                SET
                    gender = ?,
                    updated_at =
                        SYSUTCDATETIME()

                WHERE
                    badminton_id = ?
                """,
                gender,
                badminton_id,
            )


            if cursor.rowcount > 0:

                updated += 1

            else:

                not_found += 1


        conn.commit()


        print()
        print("=" * 100)
        print("DATABASE UPDATE")
        print("=" * 100)

        print(
            "Spillere opdateret:",
            updated
        )

        print(
            "Ikke fundet i badminton_players:",
            not_found
        )


    finally:

        cursor.close()
        conn.close()


# =========================================================
# VALIDATE CLUB
# =========================================================

def validate(
    club_id,
    season_id,
):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT
                p.gender,
                COUNT(*) AS player_count

            FROM dbo.club_players cp

            INNER JOIN dbo.badminton_players p
                ON p.badminton_id =
                    cp.badminton_id

            WHERE
                cp.club_id = ?
                AND cp.season_id = ?
                AND cp.is_active = 1

            GROUP BY
                p.gender

            ORDER BY
                p.gender
            """,
            club_id,
            season_id,
        )


        rows = cursor.fetchall()


        print()
        print("=" * 100)
        print("AKTIVE KLUBSPILLERE")
        print("=" * 100)


        for row in rows:

            print(
                row.gender
                if row.gender
                else "NULL",
                ":",
                row.player_count
            )


        # ---------------------------------------------
        # Show remaining unknown players
        # ---------------------------------------------

        cursor.execute(
            """
            SELECT
                p.badminton_id,
                p.player_name

            FROM dbo.club_players cp

            INNER JOIN dbo.badminton_players p
                ON p.badminton_id =
                    cp.badminton_id

            WHERE
                cp.club_id = ?
                AND cp.season_id = ?
                AND cp.is_active = 1
                AND p.gender IS NULL

            ORDER BY
                p.player_name
            """,
            club_id,
            season_id,
        )


        unknown = (
            cursor.fetchall()
        )


        print()
        print(
            "Spillere uden køn:",
            len(unknown)
        )


        for row in unknown:

            print(
                " -",
                row.badminton_id,
                row.player_name
            )


    finally:

        cursor.close()
        conn.close()


# =========================================================
# MAIN
# =========================================================

def sync_player_genders(
    club_id,
    season_id,
    validate_result=False,
):
    """
    Henter køn for klubbens spillere og gemmer det på
    dbo.badminton_players. Kan kaldes direkte fra app.py
    efter sync_club_players().
    """

    ensure_gender_column()

    gender_map = scrape_gender(
        club_id=club_id,
        season_id=season_id,
    )

    print()
    print(
        "Unikke spillere med køn:",
        len(gender_map)
    )

    save_gender(
        gender_map
    )

    if validate_result:
        validate(
            club_id=club_id,
            season_id=season_id,
        )

    return gender_map


def main():

    sync_player_genders(
        club_id=CLUB_ID,
        season_id=SEASON_ID,
        validate_result=True,
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()