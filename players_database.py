import sys

from database import get_connection
from players_test import get_club_players


# =========================================================
# TERMINAL ENCODING
# =========================================================

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8"
    )


# =========================================================
# CONFIG
# =========================================================

CLUB_ID = 1148
SEASON_ID = 2026

# BadmintonPlayers rangliste-ID
RANKING_LIST_ID = 287


# =========================================================
# ENSURE TABLES
# =========================================================

def ensure_player_tables():

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # =================================================
        # BADMINTON PLAYERS
        #
        # Canonical player table.
        # BadmintonID is the stable player identifier.
        # =================================================

        cursor.execute(
            """
            IF OBJECT_ID(
                N'dbo.badminton_players',
                N'U'
            ) IS NULL

            BEGIN

                CREATE TABLE dbo.badminton_players (

                    badminton_id NVARCHAR(20)
                        NOT NULL
                        PRIMARY KEY,

                    player_name NVARCHAR(255)
                        NOT NULL,

                    created_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_badminton_players_created
                        DEFAULT SYSUTCDATETIME(),

                    updated_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_badminton_players_updated
                        DEFAULT SYSUTCDATETIME()

                );

            END
            """
        )


        # =================================================
        # CLUB PLAYERS
        #
        # Player -> club -> season relationship.
        #
        # A player can therefore change clubs without
        # changing the canonical player record.
        # =================================================

        cursor.execute(
            """
            IF OBJECT_ID(
                N'dbo.club_players',
                N'U'
            ) IS NULL

            BEGIN

                CREATE TABLE dbo.club_players (

                    id INT IDENTITY(1,1)
                        PRIMARY KEY,

                    club_id INT
                        NOT NULL,

                    season_id INT
                        NOT NULL,

                    badminton_id NVARCHAR(20)
                        NOT NULL,

                    is_active BIT
                        NOT NULL
                        CONSTRAINT DF_club_players_active
                        DEFAULT 1,

                    first_seen_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_club_players_first_seen
                        DEFAULT SYSUTCDATETIME(),

                    last_seen_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_club_players_last_seen
                        DEFAULT SYSUTCDATETIME(),

                    CONSTRAINT UQ_club_players
                    UNIQUE (
                        club_id,
                        season_id,
                        badminton_id
                    ),

                    CONSTRAINT FK_club_players_club
                    FOREIGN KEY (
                        club_id
                    )
                    REFERENCES dbo.badminton_clubs(
                        club_id
                    ),

                    CONSTRAINT FK_club_players_player
                    FOREIGN KEY (
                        badminton_id
                    )
                    REFERENCES dbo.badminton_players(
                        badminton_id
                    )

                );

            END
            """
        )


        # =================================================
        # PLAYER RANKINGS
        #
        # Ranking information for a player in a given
        # club / season / ranking list.
        # =================================================

        cursor.execute(
            """
            IF OBJECT_ID(
                N'dbo.player_rankings',
                N'U'
            ) IS NULL

            BEGIN

                CREATE TABLE dbo.player_rankings (

                    id INT IDENTITY(1,1)
                        PRIMARY KEY,

                    badminton_id NVARCHAR(20)
                        NOT NULL,

                    club_id INT
                        NOT NULL,

                    season_id INT
                        NOT NULL,

                    ranking_list_id INT
                        NOT NULL,

                    ranking_position INT
                        NULL,

                    national_position INT
                        NULL,

                    ranking_class NVARCHAR(100)
                        NULL,

                    points_raw NVARCHAR(100)
                        NULL,

                    created_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_player_rankings_created
                        DEFAULT SYSUTCDATETIME(),

                    updated_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_player_rankings_updated
                        DEFAULT SYSUTCDATETIME(),

                    CONSTRAINT UQ_player_rankings
                    UNIQUE (
                        badminton_id,
                        club_id,
                        season_id,
                        ranking_list_id
                    ),

                    CONSTRAINT FK_player_rankings_player
                    FOREIGN KEY (
                        badminton_id
                    )
                    REFERENCES dbo.badminton_players(
                        badminton_id
                    ),

                    CONSTRAINT FK_player_rankings_club
                    FOREIGN KEY (
                        club_id
                    )
                    REFERENCES dbo.badminton_clubs(
                        club_id
                    )

                );

            END
            """
        )


        conn.commit()

        print(
            "✓ Spillertabeller er klar."
        )


    except Exception:

        conn.rollback()

        raise


    finally:

        cursor.close()
        conn.close()


# =========================================================
# SAVE PLAYERS
# =========================================================

def save_club_players_to_azure(
    players,
    club_id,
    season_id,
    ranking_list_id,
):

    if not players:

        print(
            "Ingen spillere at gemme."
        )

        return


    ensure_player_tables()


    conn = get_connection()
    cursor = conn.cursor()


    try:

        # =================================================
        # MARK CURRENT CLUB PLAYERS INACTIVE
        #
        # Alle der findes i det nye scrape bliver sat
        # aktive igen nedenfor.
        #
        # På den måde sletter vi aldrig historik.
        # =================================================

        cursor.execute(
            """
            UPDATE dbo.club_players

            SET
                is_active = 0

            WHERE
                club_id = ?
                AND season_id = ?
            """,

            club_id,
            season_id
        )


        # =================================================
        # LOOP PLAYERS
        # =================================================

        for index, player in enumerate(
            players,
            start=1
        ):

            badminton_id = (
                player["badminton_id"]
            )

            player_name = (
                player["player_name"]
            )


            # =============================================
            # 1. CANONICAL PLAYER
            # =============================================

            cursor.execute(
                """
                MERGE dbo.badminton_players
                    AS target

                USING (

                    SELECT
                        ? AS badminton_id,
                        ? AS player_name

                ) AS source

                ON
                    target.badminton_id =
                        source.badminton_id


                WHEN MATCHED THEN

                    UPDATE SET

                        player_name =
                            source.player_name,

                        updated_at =
                            SYSUTCDATETIME()


                WHEN NOT MATCHED THEN

                    INSERT (

                        badminton_id,
                        player_name

                    )

                    VALUES (

                        source.badminton_id,
                        source.player_name

                    );
                """,

                badminton_id,
                player_name
            )


            # =============================================
            # 2. CLUB RELATIONSHIP
            # =============================================

            cursor.execute(
                """
                MERGE dbo.club_players
                    AS target

                USING (

                    SELECT

                        ? AS club_id,
                        ? AS season_id,
                        ? AS badminton_id

                ) AS source


                ON

                    target.club_id =
                        source.club_id

                    AND

                    target.season_id =
                        source.season_id

                    AND

                    target.badminton_id =
                        source.badminton_id


                WHEN MATCHED THEN

                    UPDATE SET

                        is_active = 1,

                        last_seen_at =
                            SYSUTCDATETIME()


                WHEN NOT MATCHED THEN

                    INSERT (

                        club_id,
                        season_id,
                        badminton_id,
                        is_active

                    )

                    VALUES (

                        source.club_id,
                        source.season_id,
                        source.badminton_id,
                        1

                    );
                """,

                club_id,
                season_id,
                badminton_id
            )


            # =============================================
            # 3. RANKING
            # =============================================

            cursor.execute(
                """
                MERGE dbo.player_rankings
                    AS target

                USING (

                    SELECT

                        ? AS badminton_id,
                        ? AS club_id,
                        ? AS season_id,
                        ? AS ranking_list_id

                ) AS source


                ON

                    target.badminton_id =
                        source.badminton_id

                    AND

                    target.club_id =
                        source.club_id

                    AND

                    target.season_id =
                        source.season_id

                    AND

                    target.ranking_list_id =
                        source.ranking_list_id


                WHEN MATCHED THEN

                    UPDATE SET

                        ranking_position = ?,

                        national_position = ?,

                        ranking_class = ?,

                        points_raw = ?,

                        updated_at =
                            SYSUTCDATETIME()


                WHEN NOT MATCHED THEN

                    INSERT (

                        badminton_id,
                        club_id,
                        season_id,
                        ranking_list_id,

                        ranking_position,
                        national_position,
                        ranking_class,
                        points_raw

                    )

                    VALUES (

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

                badminton_id,
                club_id,
                season_id,
                ranking_list_id,


                # =========================================
                # UPDATE
                # =========================================

                player.get(
                    "ranking_position"
                ),

                player.get(
                    "national_position"
                ),

                player.get(
                    "ranking_class"
                ),

                player.get(
                    "points"
                ),


                # =========================================
                # INSERT
                # =========================================

                badminton_id,
                club_id,
                season_id,
                ranking_list_id,

                player.get(
                    "ranking_position"
                ),

                player.get(
                    "national_position"
                ),

                player.get(
                    "ranking_class"
                ),

                player.get(
                    "points"
                ),
            )


            if (
                index % 25 == 0
                or index == len(players)
            ):

                print(
                    f"  {index}/{len(players)} "
                    f"spillere behandlet..."
                )


        # =================================================
        # COMMIT EVERYTHING
        # =================================================

        conn.commit()


        print()
        print(
            f"✓ {len(players)} spillere "
            f"blev gemt/opdateret i Azure."
        )


    except Exception as e:

        conn.rollback()

        print()
        print(
            "FEJL ved gemning af spillere:"
        )

        print(e)

        raise


    finally:

        cursor.close()
        conn.close()


# =========================================================
# FULL SYNC
# =========================================================

def sync_club_players(
    club_id,
    season_id,
    ranking_list_id=287,
):

    print()
    print("=" * 100)
    print("SYNKRONISERER KLUBSPILLERE")
    print("=" * 100)

    print(
        "Club ID:",
        club_id
    )

    print(
        "Season:",
        season_id
    )

    print(
        "Ranking list ID:",
        ranking_list_id
    )


    # =====================================================
    # GET FROM BADMINTONPLAYER
    # =====================================================

    players = get_club_players(

        club_id=
            club_id,

        season_id=
            season_id,
    )


    print()
    print(
        "Spillere fundet:",
        len(players)
    )


    if not players:

        print(
            "Stopper fordi der ikke "
            "blev fundet spillere."
        )

        return []


    # =====================================================
    # SAVE TO AZURE
    # =====================================================

    save_club_players_to_azure(

        players=
            players,

        club_id=
            club_id,

        season_id=
            season_id,

        ranking_list_id=
            ranking_list_id,
    )


    return players


# =========================================================
# LOCAL TEST
# =========================================================

if __name__ == "__main__":

    players = sync_club_players(

        club_id=
            CLUB_ID,

        season_id=
            SEASON_ID,

        ranking_list_id=
            RANKING_LIST_ID,
    )


    # =====================================================
    # PRINT FIRST 20
    # =====================================================

    print()
    print("=" * 100)
    print("FØRSTE SPILLERE FRA SCRAPE")
    print("=" * 100)


    for player in players[:20]:

        print(

            player[
                "badminton_id"
            ],

            "|",

            player[
                "player_name"
            ],

            "|",

            player.get(
                "ranking_class"
            ),

            "| national:",

            player.get(
                "national_position"
            )
        )