import sys

from database import get_connection


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8"
    )


# =========================================================
# CREATE TABLES
# =========================================================

def ensure_match_detail_tables():

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # =================================================
        # INDIVIDUAL GAMES
        # =================================================

        cursor.execute(
            """
            IF OBJECT_ID(
                N'dbo.club_match_games',
                N'U'
            ) IS NULL
            BEGIN

                CREATE TABLE dbo.club_match_games (

                    id INT IDENTITY(1,1)
                        PRIMARY KEY,

                    club_match_id INT
                        NOT NULL,

                    match_number INT
                        NOT NULL,

                    match_type NVARCHAR(10)
                        NOT NULL,

                    match_label NVARCHAR(50)
                        NULL,

                    winner_side NVARCHAR(10)
                        NULL,

                    winner_wo_raw NVARCHAR(50)
                        NULL,

                    created_at DATETIME2
                        NOT NULL
                        DEFAULT SYSUTCDATETIME(),

                    updated_at DATETIME2
                        NOT NULL
                        DEFAULT SYSUTCDATETIME(),

                    CONSTRAINT UQ_club_match_games
                    UNIQUE (
                        club_match_id,
                        match_number,
                        match_type
                    ),

                    CONSTRAINT FK_club_match_games_match
                    FOREIGN KEY (
                        club_match_id
                    )
                    REFERENCES dbo.club_matches(
                        id
                    )

                    ON DELETE CASCADE
                );

            END
            """
        )


        # =================================================
        # PLAYERS IN INDIVIDUAL GAME
        # =================================================

        cursor.execute(
            """
            IF OBJECT_ID(
                N'dbo.club_match_game_players',
                N'U'
            ) IS NULL
            BEGIN

                CREATE TABLE dbo.club_match_game_players (

                    id INT IDENTITY(1,1)
                        PRIMARY KEY,

                    game_id INT
                        NOT NULL,

                    side NVARCHAR(10)
                        NOT NULL,

                    player_order INT
                        NOT NULL,

                    player_name_snapshot NVARCHAR(255)
                        NOT NULL,

                    badmintonplayer_id INT
                        NULL,

                    badminton_id NVARCHAR(20)
                        NULL,

                    created_at DATETIME2
                        NOT NULL
                        DEFAULT SYSUTCDATETIME(),

                    updated_at DATETIME2
                        NOT NULL
                        DEFAULT SYSUTCDATETIME(),

                    CONSTRAINT UQ_club_match_game_players
                    UNIQUE (
                        game_id,
                        side,
                        player_order
                    ),

                    CONSTRAINT FK_game_players_game
                    FOREIGN KEY (
                        game_id
                    )
                    REFERENCES dbo.club_match_games(
                        id
                    )

                    ON DELETE CASCADE,

                    CONSTRAINT FK_game_players_player
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
        # SETS
        # =================================================

        cursor.execute(
            """
            IF OBJECT_ID(
                N'dbo.club_match_game_sets',
                N'U'
            ) IS NULL
            BEGIN

                CREATE TABLE dbo.club_match_game_sets (

                    id INT IDENTITY(1,1)
                        PRIMARY KEY,

                    game_id INT
                        NOT NULL,

                    set_number INT
                        NOT NULL,

                    home_score INT
                        NULL,

                    away_score INT
                        NULL,

                    raw_score NVARCHAR(50)
                        NULL,

                    created_at DATETIME2
                        NOT NULL
                        DEFAULT SYSUTCDATETIME(),

                    updated_at DATETIME2
                        NOT NULL
                        DEFAULT SYSUTCDATETIME(),

                    CONSTRAINT UQ_club_match_game_sets
                    UNIQUE (
                        game_id,
                        set_number
                    ),

                    CONSTRAINT FK_game_sets_game
                    FOREIGN KEY (
                        game_id
                    )
                    REFERENCES dbo.club_match_games(
                        id
                    )

                    ON DELETE CASCADE
                );

            END
            """
        )


        conn.commit()

        print(
            "[OK] Match detail-tabeller er klar."
        )


    except Exception:

        conn.rollback()
        raise


    finally:

        cursor.close()
        conn.close()


# =========================================================
# RESOLVE BADMINTON ID
# =========================================================

def resolve_badminton_id(
    cursor,
    player,
):

    badminton_id = player.get(
        "badminton_id"
    )

    if badminton_id:
        return badminton_id


    badmintonplayer_id = player.get(
        "badmintonplayer_id"
    )


    if badmintonplayer_id is None:
        return None


    cursor.execute(
        """
        SELECT badminton_id

        FROM dbo.badminton_players

        WHERE badmintonplayer_id = ?
        """,

        badmintonplayer_id
    )


    row = cursor.fetchone()


    if row:

        return row.badminton_id


    return None


# =========================================================
# SAVE ONE MATCH
# =========================================================

def save_match_details_to_azure(
    match,
    details,
):

    games = details.get(
        "games",
        []
    )


    if not games:

        return {
            "games": 0,
            "players": 0,
            "sets": 0,
        }


    ensure_match_detail_tables()


    club_match_id = match[
        "id"
    ]


    conn = get_connection()
    cursor = conn.cursor()


    game_count = 0
    player_count = 0
    set_count = 0


    try:

        for game in games:

            # =============================================
            # GAME
            # =============================================

            cursor.execute(
                """
                MERGE dbo.club_match_games
                    AS target

                USING (
                    SELECT
                        ? AS club_match_id,
                        ? AS match_number,
                        ? AS match_type
                ) AS source

                ON
                    target.club_match_id =
                        source.club_match_id

                    AND target.match_number =
                        source.match_number

                    AND target.match_type =
                        source.match_type


                WHEN MATCHED THEN

                    UPDATE SET
                        match_label = ?,
                        winner_side = ?,
                        winner_wo_raw = ?,
                        updated_at =
                            SYSUTCDATETIME()


                WHEN NOT MATCHED THEN

                    INSERT (
                        club_match_id,
                        match_number,
                        match_type,
                        match_label,
                        winner_side,
                        winner_wo_raw
                    )

                    VALUES (
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?
                    );
                """,

                club_match_id,
                game["match_number"],
                game["match_type"],

                game.get("match_label"),
                game.get("winner_side"),
                game.get("winner_wo_raw"),

                club_match_id,
                game["match_number"],
                game["match_type"],
                game.get("match_label"),
                game.get("winner_side"),
                game.get("winner_wo_raw"),
            )


            cursor.execute(
                """
                SELECT id

                FROM dbo.club_match_games

                WHERE
                    club_match_id = ?
                    AND match_number = ?
                    AND match_type = ?
                """,

                club_match_id,
                game["match_number"],
                game["match_type"]
            )


            game_id = (
                cursor.fetchone().id
            )


            game_count += 1


            # =============================================
            # PLAYERS
            #
            # Replace current snapshot.
            # =============================================

            cursor.execute(
                """
                DELETE FROM dbo.club_match_game_players

                WHERE game_id = ?
                """,

                game_id
            )


            sides = [
                (
                    "home",
                    game.get(
                        "home_players",
                        []
                    )
                ),
                (
                    "away",
                    game.get(
                        "away_players",
                        []
                    )
                ),
            ]


            for side, players in sides:

                for player_order, player in enumerate(
                    players,
                    start=1
                ):

                    badminton_id = (
                        resolve_badminton_id(
                            cursor,
                            player
                        )
                    )


                    cursor.execute(
                        """
                        INSERT INTO dbo.club_match_game_players (
                            game_id,
                            side,
                            player_order,
                            player_name_snapshot,
                            badmintonplayer_id,
                            badminton_id
                        )

                        VALUES (
                            ?,
                            ?,
                            ?,
                            ?,
                            ?,
                            ?
                        )
                        """,

                        game_id,
                        side,
                        player_order,

                        player[
                            "player_name"
                        ],

                        player.get(
                            "badmintonplayer_id"
                        ),

                        badminton_id,
                    )


                    player_count += 1


            # =============================================
            # SETS
            #
            # Replace current snapshot.
            # =============================================

            cursor.execute(
                """
                DELETE FROM dbo.club_match_game_sets

                WHERE game_id = ?
                """,

                game_id
            )


            for game_set in game.get(
                "sets",
                []
            ):

                cursor.execute(
                    """
                    INSERT INTO dbo.club_match_game_sets (
                        game_id,
                        set_number,
                        home_score,
                        away_score,
                        raw_score
                    )

                    VALUES (
                        ?,
                        ?,
                        ?,
                        ?,
                        ?
                    )
                    """,

                    game_id,

                    game_set[
                        "set_number"
                    ],

                    game_set.get(
                        "home"
                    ),

                    game_set.get(
                        "away"
                    ),

                    game_set.get(
                        "raw"
                    ),
                )


                set_count += 1


        conn.commit()


        return {
            "games":
                game_count,

            "players":
                player_count,

            "sets":
                set_count,
        }


    except Exception:

        conn.rollback()
        raise


    finally:

        cursor.close()
        conn.close()


# =========================================================
# LOCAL TABLE TEST
# =========================================================

if __name__ == "__main__":

    ensure_match_detail_tables()