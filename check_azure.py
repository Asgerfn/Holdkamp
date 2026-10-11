import sys

from database import get_connection


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8"
    )


# =========================================================
# CREATE / UPDATE FANTASY POINT TABLES
# =========================================================

def ensure_fantasy_point_tables():

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # =================================================
        # FANTASY POINT EVENTS
        # =================================================

        cursor.execute(
            """
            IF OBJECT_ID(
                N'dbo.fantasy_point_events',
                N'U'
            ) IS NULL
            BEGIN

                CREATE TABLE dbo.fantasy_point_events (

                    id INT IDENTITY(1,1)
                        PRIMARY KEY,

                    club_id INT
                        NOT NULL,

                    season_id INT
                        NOT NULL,

                    club_match_id INT
                        NOT NULL,

                    game_id INT
                        NULL,

                    set_number INT
                        NULL,

                    badmintonplayer_id INT
                        NULL,

                    badminton_id NVARCHAR(20)
                        NULL,

                    player_name_snapshot NVARCHAR(255)
                        NULL,

                    event_code NVARCHAR(50)
                        NOT NULL,

                    points INT
                        NOT NULL,

                    description NVARCHAR(255)
                        NULL,

                    event_key NVARCHAR(255)
                        NOT NULL,

                    created_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_fantasy_point_events_created
                        DEFAULT SYSUTCDATETIME(),

                    updated_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_fantasy_point_events_updated
                        DEFAULT SYSUTCDATETIME(),

                    CONSTRAINT FK_fantasy_point_events_club
                    FOREIGN KEY (
                        club_id
                    )
                    REFERENCES dbo.badminton_clubs(
                        club_id
                    ),

                    CONSTRAINT FK_fantasy_point_events_match
                    FOREIGN KEY (
                        club_match_id
                    )
                    REFERENCES dbo.club_matches(
                        id
                    ),

                    CONSTRAINT FK_fantasy_point_events_game
                    FOREIGN KEY (
                        game_id
                    )
                    REFERENCES dbo.club_match_games(
                        id
                    ),

                    CONSTRAINT FK_fantasy_point_events_player
                    FOREIGN KEY (
                        badminton_id
                    )
                    REFERENCES dbo.badminton_players(
                        badminton_id
                    ),

                    CONSTRAINT UQ_fantasy_point_events_event_key
                    UNIQUE (
                        event_key
                    )
                );

            END
            """
        )

        conn.commit()


        # =================================================
        # INDEX: PLAYER
        # =================================================

        cursor.execute(
            """
            IF NOT EXISTS (
                SELECT 1

                FROM sys.indexes

                WHERE
                    name =
                        'IX_fantasy_point_events_player'

                    AND object_id =
                        OBJECT_ID(
                            'dbo.fantasy_point_events'
                        )
            )
            BEGIN

                CREATE INDEX
                    IX_fantasy_point_events_player

                ON dbo.fantasy_point_events (
                    badminton_id,
                    season_id
                );

            END
            """
        )

        conn.commit()


        # =================================================
        # INDEX: BADMINTONPLAYER ID
        # =================================================

        cursor.execute(
            """
            IF NOT EXISTS (
                SELECT 1

                FROM sys.indexes

                WHERE
                    name =
                        'IX_fantasy_point_events_bp_player'

                    AND object_id =
                        OBJECT_ID(
                            'dbo.fantasy_point_events'
                        )
            )
            BEGIN

                CREATE INDEX
                    IX_fantasy_point_events_bp_player

                ON dbo.fantasy_point_events (
                    badmintonplayer_id,
                    season_id
                );

            END
            """
        )

        conn.commit()


        # =================================================
        # INDEX: MATCH
        # =================================================

        cursor.execute(
            """
            IF NOT EXISTS (
                SELECT 1

                FROM sys.indexes

                WHERE
                    name =
                        'IX_fantasy_point_events_match'

                    AND object_id =
                        OBJECT_ID(
                            'dbo.fantasy_point_events'
                        )
            )
            BEGIN

                CREATE INDEX
                    IX_fantasy_point_events_match

                ON dbo.fantasy_point_events (
                    club_match_id
                );

            END
            """
        )

        conn.commit()


        # =================================================
        # INDEX: GAME
        # =================================================

        cursor.execute(
            """
            IF NOT EXISTS (
                SELECT 1

                FROM sys.indexes

                WHERE
                    name =
                        'IX_fantasy_point_events_game'

                    AND object_id =
                        OBJECT_ID(
                            'dbo.fantasy_point_events'
                        )
            )
            BEGIN

                CREATE INDEX
                    IX_fantasy_point_events_game

                ON dbo.fantasy_point_events (
                    game_id
                );

            END
            """
        )

        conn.commit()


        print()
        print("=" * 100)
        print("FANTASY POINT DATABASE")
        print("=" * 100)

        print(
            "[OK] dbo.fantasy_point_events er klar."
        )


        # =================================================
        # STATUS
        # =================================================

        cursor.execute(
            """
            SELECT COUNT(*)

            FROM dbo.fantasy_point_events
            """
        )

        count = (
            cursor.fetchone()[0]
        )


        print(
            "Point events i databasen:",
            count
        )


    except Exception:

        conn.rollback()
        raise


    finally:

        cursor.close()
        conn.close()


# =========================================================
# LOCAL RUN
# =========================================================

if __name__ == "__main__":

    ensure_fantasy_point_tables()