from database import get_connection


# =========================================================
# CREATE TABLE
# =========================================================

def ensure_club_matches_table():

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            IF OBJECT_ID(
                N'dbo.club_matches',
                N'U'
            ) IS NULL

            BEGIN

                CREATE TABLE dbo.club_matches (

                    id INT IDENTITY(1,1)
                        PRIMARY KEY,


                    -- =====================================
                    -- CLUB / SEASON
                    -- =====================================

                    club_id INT NOT NULL,

                    season_id INT NOT NULL,


                    -- =====================================
                    -- BADMINTONPLAYER IDENTIFIERS
                    -- =====================================

                    league_group_id INT NOT NULL,

                    age_group_id INT NULL,

                    region_id INT NULL,

                    league_group_team_id INT NULL,

                    league_match_id INT NOT NULL,


                    -- =====================================
                    -- WHICH CLUB TEAM
                    -- =====================================

                    club_team_name NVARCHAR(255)
                        NULL,

                    league_name NVARCHAR(500)
                        NULL,


                    -- =====================================
                    -- MATCH
                    -- =====================================

                    match_time DATETIME2
                        NULL,

                    home_team NVARCHAR(255)
                        NULL,

                    away_team NVARCHAR(255)
                        NULL,

                    organizer NVARCHAR(255)
                        NULL,

                    venue NVARCHAR(255)
                        NULL,


                    -- =====================================
                    -- RESULT
                    -- =====================================

                    result NVARCHAR(50)
                        NULL,

                    points NVARCHAR(50)
                        NULL,


                    -- =====================================
                    -- META
                    -- =====================================

                    created_at DATETIME2 NOT NULL
                        CONSTRAINT DF_club_matches_created
                        DEFAULT SYSUTCDATETIME(),

                    updated_at DATETIME2 NOT NULL
                        CONSTRAINT DF_club_matches_updated
                        DEFAULT SYSUTCDATETIME(),


                    -- =====================================
                    -- UNIQUE MATCH
                    -- =====================================

                    CONSTRAINT UQ_club_matches
                    UNIQUE (
                        club_id,
                        season_id,
                        league_match_id
                    ),


                    -- =====================================
                    -- CLUB FK
                    -- =====================================

                    CONSTRAINT FK_club_matches_club
                    FOREIGN KEY (club_id)
                    REFERENCES dbo.badminton_clubs(club_id)

                );

            END
        """)

        conn.commit()

        print(
            "dbo.club_matches er klar."
        )

    finally:

        cursor.close()
        conn.close()


# =========================================================
# UPSERT MATCHES
# =========================================================

def save_matches_to_azure(matches):

    """
    Gemmer / opdaterer kampe i Azure.

    matches skal være en liste af dictionaries.

    Eksempel:

    {
        "club_id": 1148,
        "season_id": 2026,

        "league_group_id": 18844,
        "age_group_id": 1,
        "region_id": 1,
        "league_group_team_id": 121898,
        "league_match_id": 507496,

        "club_team_name": "Herlev/Hjorten",
        "league_name": "3. division Pulje 3",

        "match_time": "2026-09-05 13:30:00",

        "home_team": "BC37 Amager",
        "away_team": "Herlev/Hjorten",

        "organizer": "BC37 Amager",
        "venue": "BC37-Hallen",

        "result": "5-8",
        "points": "5-11"
    }
    """


    if not matches:

        print(
            "Ingen kampe at gemme."
        )

        return


    ensure_club_matches_table()


    conn = get_connection()
    cursor = conn.cursor()


    inserted_or_updated = 0


    try:

        for match in matches:

            cursor.execute(
                """
                MERGE dbo.club_matches AS target

                USING (

                    SELECT

                        ? AS club_id,

                        ? AS season_id,

                        ? AS league_match_id

                ) AS source


                ON

                    target.club_id =
                        source.club_id

                    AND target.season_id =
                        source.season_id

                    AND target.league_match_id =
                        source.league_match_id


                WHEN MATCHED THEN

                    UPDATE SET

                        league_group_id = ?,

                        age_group_id = ?,

                        region_id = ?,

                        league_group_team_id = ?,

                        club_team_name = ?,

                        league_name = ?,

                        match_time = ?,

                        home_team = ?,

                        away_team = ?,

                        organizer = ?,

                        venue = ?,

                        result = ?,

                        points = ?,

                        updated_at =
                            SYSUTCDATETIME()


                WHEN NOT MATCHED THEN

                    INSERT (

                        club_id,

                        season_id,

                        league_group_id,

                        age_group_id,

                        region_id,

                        league_group_team_id,

                        league_match_id,

                        club_team_name,

                        league_name,

                        match_time,

                        home_team,

                        away_team,

                        organizer,

                        venue,

                        result,

                        points

                    )

                    VALUES (

                        ?,

                        ?,

                        ?,

                        ?,

                        ?,

                        ?,

                        ?,

                        ?,

                        ?,

                        ?,

                        ?,

                        ?,

                        ?,

                        ?,

                        ?,

                        ?

                    );

                """,

                # =========================================
                # SOURCE
                # =========================================

                match["club_id"],

                match["season_id"],

                match["league_match_id"],


                # =========================================
                # UPDATE
                # =========================================

                match["league_group_id"],

                match.get(
                    "age_group_id"
                ),

                match.get(
                    "region_id"
                ),

                match.get(
                    "league_group_team_id"
                ),

                match.get(
                    "club_team_name"
                ),

                match.get(
                    "league_name"
                ),

                match.get(
                    "match_time"
                ),

                match.get(
                    "home_team"
                ),

                match.get(
                    "away_team"
                ),

                match.get(
                    "organizer"
                ),

                match.get(
                    "venue"
                ),

                match.get(
                    "result"
                ),

                match.get(
                    "points"
                ),


                # =========================================
                # INSERT
                # =========================================

                match["club_id"],

                match["season_id"],

                match["league_group_id"],

                match.get(
                    "age_group_id"
                ),

                match.get(
                    "region_id"
                ),

                match.get(
                    "league_group_team_id"
                ),

                match["league_match_id"],

                match.get(
                    "club_team_name"
                ),

                match.get(
                    "league_name"
                ),

                match.get(
                    "match_time"
                ),

                match.get(
                    "home_team"
                ),

                match.get(
                    "away_team"
                ),

                match.get(
                    "organizer"
                ),

                match.get(
                    "venue"
                ),

                match.get(
                    "result"
                ),

                match.get(
                    "points"
                )
            )


            inserted_or_updated += 1


        conn.commit()


    except Exception:

        conn.rollback()

        raise


    finally:

        cursor.close()
        conn.close()


    print(
        f"{inserted_or_updated} kampe "
        f"blev gemt/opdateret i Azure."
    )


# =========================================================
# LOCAL TEST
# =========================================================

if __name__ == "__main__":

    ensure_club_matches_table()


    # -----------------------------------------------------
    # Test med kampen fra BadmintonPlayer
    # -----------------------------------------------------

    test_matches = [

        {
            "club_id":
                1148,

            "season_id":
                2026,

            "league_group_id":
                18844,

            "age_group_id":
                1,

            "region_id":
                1,

            "league_group_team_id":
                121898,

            "league_match_id":
                507496,

            "club_team_name":
                "Herlev/Hjorten",

            "league_name":
                "3. division Pulje 3",

            "match_time":
                "2026-09-05 13:30:00",

            "home_team":
                "BC37 Amager",

            "away_team":
                "Herlev/Hjorten",

            "organizer":
                "BC37 Amager",

            "venue":
                "BC37-Hallen",

            "result":
                "5-8",

            "points":
                "5-11",
        }

    ]


    save_matches_to_azure(
        test_matches
    )