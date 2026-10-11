import sys

from database import get_connection


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8"
    )


# =========================================================
# FANTASY TEAM DATABASE
# =========================================================

def ensure_fantasy_team_tables():

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # =================================================
        # CHECK REQUIRED EXISTING TABLES
        # =================================================

        required_tables = [
            "dbo.users",
            "dbo.badminton_clubs",
            "dbo.badminton_players",
        ]


        for table_name in required_tables:

            cursor.execute(
                """
                SELECT OBJECT_ID(?, 'U')
                """,
                table_name
            )

            object_id = cursor.fetchone()[0]


            if object_id is None:

                raise RuntimeError(
                    f"Krævet tabel mangler: {table_name}"
                )


        # =================================================
        # 1. FANTASY TEAM RULES
        # =================================================
        #
        # Én regelopsætning pr. klub + sæson.
        #
        # Eksempel:
        #   6 herrer
        #   4 damer
        #   1 kaptajn
        #   3 udskiftninger
        #   kaptajn giver x2 point
        # =================================================

        cursor.execute(
            """
            IF OBJECT_ID(
                N'dbo.fantasy_team_rules',
                N'U'
            ) IS NULL
            BEGIN

                CREATE TABLE dbo.fantasy_team_rules (

                    id INT IDENTITY(1,1)
                        PRIMARY KEY,

                    club_id INT
                        NOT NULL,

                    season_id INT
                        NOT NULL,

                    male_players INT
                        NOT NULL
                        CONSTRAINT DF_fantasy_team_rules_male
                        DEFAULT 6,

                    female_players INT
                        NOT NULL
                        CONSTRAINT DF_fantasy_team_rules_female
                        DEFAULT 4,

                    captain_count INT
                        NOT NULL
                        CONSTRAINT DF_fantasy_team_rules_captain
                        DEFAULT 1,

                    max_substitutions INT
                        NOT NULL
                        CONSTRAINT DF_fantasy_team_rules_subs
                        DEFAULT 0,

                    captain_multiplier DECIMAL(5,2)
                        NOT NULL
                        CONSTRAINT DF_fantasy_team_rules_multiplier
                        DEFAULT 2.00,

                    created_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_fantasy_team_rules_created
                        DEFAULT SYSUTCDATETIME(),

                    updated_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_fantasy_team_rules_updated
                        DEFAULT SYSUTCDATETIME(),


                    CONSTRAINT FK_fantasy_team_rules_club
                    FOREIGN KEY (
                        club_id
                    )
                    REFERENCES dbo.badminton_clubs(
                        club_id
                    ),


                    CONSTRAINT UQ_fantasy_team_rules
                    UNIQUE (
                        club_id,
                        season_id
                    ),


                    CONSTRAINT CK_fantasy_team_rules_male
                    CHECK (
                        male_players >= 0
                    ),


                    CONSTRAINT CK_fantasy_team_rules_female
                    CHECK (
                        female_players >= 0
                    ),


                    CONSTRAINT CK_fantasy_team_rules_captain
                    CHECK (
                        captain_count = 1
                    ),


                    CONSTRAINT CK_fantasy_team_rules_subs
                    CHECK (
                        max_substitutions >= 0
                    ),


                    CONSTRAINT CK_fantasy_team_rules_multiplier
                    CHECK (
                        captain_multiplier >= 1
                    )
                );

            END
            """
        )

        conn.commit()


        # =================================================
        # 2. FANTASY TEAMS
        # =================================================
        #
        # Ét hold pr. bruger / klub / sæson.
        #
        # draft:
        #   brugeren kan stadig bygge holdet frit.
        #
        # active:
        #   holdet er låst ind.
        #   ændringer derefter bliver udskiftninger.
        # =================================================

        cursor.execute(
            """
            IF OBJECT_ID(
                N'dbo.fantasy_teams',
                N'U'
            ) IS NULL
            BEGIN

                CREATE TABLE dbo.fantasy_teams (

                    id INT IDENTITY(1,1)
                        PRIMARY KEY,

                    user_id INT
                        NOT NULL,

                    club_id INT
                        NOT NULL,

                    season_id INT
                        NOT NULL,

                    team_name NVARCHAR(100)
                        NOT NULL,

                    status NVARCHAR(20)
                        NOT NULL
                        CONSTRAINT DF_fantasy_teams_status
                        DEFAULT 'draft',

                    activated_at DATETIME2
                        NULL,

                    created_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_fantasy_teams_created
                        DEFAULT SYSUTCDATETIME(),

                    updated_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_fantasy_teams_updated
                        DEFAULT SYSUTCDATETIME(),


                    CONSTRAINT FK_fantasy_teams_user
                    FOREIGN KEY (
                        user_id
                    )
                    REFERENCES dbo.users(
                        user_id
                    ),


                    CONSTRAINT FK_fantasy_teams_club
                    FOREIGN KEY (
                        club_id
                    )
                    REFERENCES dbo.badminton_clubs(
                        club_id
                    ),


                    CONSTRAINT UQ_fantasy_teams_user_season
                    UNIQUE (
                        user_id,
                        club_id,
                        season_id
                    ),


                    CONSTRAINT CK_fantasy_teams_status
                    CHECK (
                        status IN (
                            'draft',
                            'active'
                        )
                    )
                );

            END
            """
        )

        conn.commit()


        # =================================================
        # 3. SUBSTITUTION HISTORY
        # =================================================
        #
        # Én række = én rigtig udskiftning.
        #
        # De første spillervalg tæller IKKE.
        #
        # Først efter holdet er activated bliver en ændring
        # registreret her.
        # =================================================

        cursor.execute(
            """
            IF OBJECT_ID(
                N'dbo.fantasy_team_substitutions',
                N'U'
            ) IS NULL
            BEGIN

                CREATE TABLE dbo.fantasy_team_substitutions (

                    id INT IDENTITY(1,1)
                        PRIMARY KEY,

                    fantasy_team_id INT
                        NOT NULL,

                    player_out_badminton_id NVARCHAR(20)
                        NOT NULL,

                    player_in_badminton_id NVARCHAR(20)
                        NOT NULL,

                    effective_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_fantasy_team_sub_effective
                        DEFAULT SYSUTCDATETIME(),

                    created_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_fantasy_team_sub_created
                        DEFAULT SYSUTCDATETIME(),


                    CONSTRAINT FK_fantasy_team_sub_team
                    FOREIGN KEY (
                        fantasy_team_id
                    )
                    REFERENCES dbo.fantasy_teams(
                        id
                    ),


                    CONSTRAINT FK_fantasy_team_sub_player_out
                    FOREIGN KEY (
                        player_out_badminton_id
                    )
                    REFERENCES dbo.badminton_players(
                        badminton_id
                    ),


                    CONSTRAINT FK_fantasy_team_sub_player_in
                    FOREIGN KEY (
                        player_in_badminton_id
                    )
                    REFERENCES dbo.badminton_players(
                        badminton_id
                    ),


                    CONSTRAINT CK_fantasy_team_sub_different
                    CHECK (
                        player_out_badminton_id
                        <>
                        player_in_badminton_id
                    )
                );

            END
            """
        )

        conn.commit()


        # =================================================
        # 4. FANTASY TEAM PLAYERS
        # =================================================
        #
        # Dette er historikken over spillerne på holdet.
        #
        # active_to = NULL betyder:
        #   spilleren er på holdet lige nu.
        #
        # is_captain:
        #   kaptajnen får senere x2 fantasy point.
        #
        # selection_type:
        #   initial      = oprindeligt hold
        #   substitution = kommet ind via udskiftning
        # =================================================

        cursor.execute(
            """
            IF OBJECT_ID(
                N'dbo.fantasy_team_players',
                N'U'
            ) IS NULL
            BEGIN

                CREATE TABLE dbo.fantasy_team_players (

                    id INT IDENTITY(1,1)
                        PRIMARY KEY,

                    fantasy_team_id INT
                        NOT NULL,

                    badminton_id NVARCHAR(20)
                        NOT NULL,

                    is_captain BIT
                        NOT NULL
                        CONSTRAINT DF_fantasy_team_players_captain
                        DEFAULT 0,

                    active_from DATETIME2
                        NOT NULL
                        CONSTRAINT DF_fantasy_team_players_from
                        DEFAULT SYSUTCDATETIME(),

                    active_to DATETIME2
                        NULL,

                    selection_type NVARCHAR(20)
                        NOT NULL
                        CONSTRAINT DF_fantasy_team_players_type
                        DEFAULT 'initial',

                    substitution_id INT
                        NULL,

                    created_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_fantasy_team_players_created
                        DEFAULT SYSUTCDATETIME(),

                    updated_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_fantasy_team_players_updated
                        DEFAULT SYSUTCDATETIME(),


                    CONSTRAINT FK_fantasy_team_players_team
                    FOREIGN KEY (
                        fantasy_team_id
                    )
                    REFERENCES dbo.fantasy_teams(
                        id
                    ),


                    CONSTRAINT FK_fantasy_team_players_player
                    FOREIGN KEY (
                        badminton_id
                    )
                    REFERENCES dbo.badminton_players(
                        badminton_id
                    ),


                    CONSTRAINT FK_fantasy_team_players_sub
                    FOREIGN KEY (
                        substitution_id
                    )
                    REFERENCES dbo.fantasy_team_substitutions(
                        id
                    ),


                    CONSTRAINT CK_fantasy_team_players_dates
                    CHECK (
                        active_to IS NULL
                        OR active_to >= active_from
                    ),


                    CONSTRAINT CK_fantasy_team_players_type
                    CHECK (
                        selection_type IN (
                            'initial',
                            'substitution'
                        )
                    )
                );

            END
            """
        )

        conn.commit()


        # =================================================
        # INDEX:
        # CURRENT PLAYER MAY ONLY APPEAR ONCE
        # =================================================

        cursor.execute(
            """
            IF NOT EXISTS (
                SELECT 1

                FROM sys.indexes

                WHERE
                    name =
                        'UX_fantasy_team_players_current'

                    AND object_id =
                        OBJECT_ID(
                            'dbo.fantasy_team_players'
                        )
            )
            BEGIN

                CREATE UNIQUE INDEX
                    UX_fantasy_team_players_current

                ON dbo.fantasy_team_players (
                    fantasy_team_id,
                    badminton_id
                )

                WHERE active_to IS NULL;

            END
            """
        )

        conn.commit()


        # =================================================
        # INDEX:
        # MAX ONE ACTIVE CAPTAIN PER TEAM
        # =================================================

        cursor.execute(
            """
            IF NOT EXISTS (
                SELECT 1

                FROM sys.indexes

                WHERE
                    name =
                        'UX_fantasy_team_active_captain'

                    AND object_id =
                        OBJECT_ID(
                            'dbo.fantasy_team_players'
                        )
            )
            BEGIN

                CREATE UNIQUE INDEX
                    UX_fantasy_team_active_captain

                ON dbo.fantasy_team_players (
                    fantasy_team_id
                )

                WHERE
                    active_to IS NULL
                    AND is_captain = 1;

            END
            """
        )

        conn.commit()


        # =================================================
        # INDEX:
        # TEAM LOOKUP
        # =================================================

        cursor.execute(
            """
            IF NOT EXISTS (
                SELECT 1

                FROM sys.indexes

                WHERE
                    name =
                        'IX_fantasy_team_players_team'

                    AND object_id =
                        OBJECT_ID(
                            'dbo.fantasy_team_players'
                        )
            )
            BEGIN

                CREATE INDEX
                    IX_fantasy_team_players_team

                ON dbo.fantasy_team_players (
                    fantasy_team_id,
                    active_from,
                    active_to
                );

            END
            """
        )

        conn.commit()


        # =================================================
        # INDEX:
        # PLAYER LOOKUP
        # =================================================

        cursor.execute(
            """
            IF NOT EXISTS (
                SELECT 1

                FROM sys.indexes

                WHERE
                    name =
                        'IX_fantasy_team_players_player'

                    AND object_id =
                        OBJECT_ID(
                            'dbo.fantasy_team_players'
                        )
            )
            BEGIN

                CREATE INDEX
                    IX_fantasy_team_players_player

                ON dbo.fantasy_team_players (
                    badminton_id
                );

            END
            """
        )

        conn.commit()


        # =================================================
        # INDEX:
        # SUBSTITUTIONS
        # =================================================

        cursor.execute(
            """
            IF NOT EXISTS (
                SELECT 1

                FROM sys.indexes

                WHERE
                    name =
                        'IX_fantasy_team_substitutions_team'

                    AND object_id =
                        OBJECT_ID(
                            'dbo.fantasy_team_substitutions'
                        )
            )
            BEGIN

                CREATE INDEX
                    IX_fantasy_team_substitutions_team

                ON dbo.fantasy_team_substitutions (
                    fantasy_team_id,
                    effective_at
                );

            END
            """
        )

        conn.commit()


        # =================================================
        # STATUS
        # =================================================

        print()
        print("=" * 100)
        print("FANTASY TEAM DATABASE")
        print("=" * 100)


        tables = [
            "fantasy_team_rules",
            "fantasy_teams",
            "fantasy_team_substitutions",
            "fantasy_team_players",
        ]


        for table_name in tables:

            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM dbo.{table_name}
                """
            )

            count = cursor.fetchone()[0]

            print(
                f"[OK] dbo.{table_name}: "
                f"{count} rows"
            )


        print()
        print(
            "[OK] Fantasy team-tabeller er klar."
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

    ensure_fantasy_team_tables()