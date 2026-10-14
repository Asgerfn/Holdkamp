from database import get_connection


def get_existing_column_type(cursor, table_name, column_name):
    """
    Read the SQL type of an existing Azure SQL column.

    We use this for badminton_id so the betting table gets the
    exact same type as dbo.badminton_players.badminton_id.
    """
    cursor.execute(
        """
        SELECT
            DATA_TYPE,
            CHARACTER_MAXIMUM_LENGTH,
            NUMERIC_PRECISION,
            NUMERIC_SCALE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE
            TABLE_SCHEMA = 'dbo'
            AND TABLE_NAME = ?
            AND COLUMN_NAME = ?
        """,
        table_name,
        column_name,
    )

    row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            f"Could not find dbo.{table_name}.{column_name}"
        )

    data_type = str(row.DATA_TYPE).lower()

    if data_type in {
        "nvarchar",
        "varchar",
        "nchar",
        "char",
    }:
        length = row.CHARACTER_MAXIMUM_LENGTH

        if length == -1:
            return f"{data_type.upper()}(MAX)"

        return f"{data_type.upper()}({int(length)})"

    if data_type in {
        "decimal",
        "numeric",
    }:
        return (
            f"{data_type.upper()}("
            f"{int(row.NUMERIC_PRECISION)},"
            f"{int(row.NUMERIC_SCALE)}"
            f")"
        )

    return data_type.upper()


def ensure_betting_tables():
    """
    Create the betting tables in Azure SQL.

    Safe to run multiple times.
    Existing data is preserved.
    """

    conn = get_connection()
    cursor = conn.cursor()

    try:
        badminton_id_type = get_existing_column_type(
            cursor,
            "badminton_players",
            "badminton_id",
        )

        # =====================================================
        # BETTING SLIPS
        # =====================================================

        cursor.execute(
            """
            IF OBJECT_ID(
                N'dbo.betting_slips',
                N'U'
            ) IS NULL
            BEGIN

                CREATE TABLE dbo.betting_slips (

                    id INT IDENTITY(1,1)
                        PRIMARY KEY,

                    user_id INT NOT NULL,

                    club_id INT NOT NULL,

                    season_id INT NOT NULL,

                    status NVARCHAR(20)
                        NOT NULL
                        CONSTRAINT DF_betting_slips_status
                        DEFAULT 'open',

                    created_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_betting_slips_created
                        DEFAULT SYSUTCDATETIME(),

                    updated_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_betting_slips_updated
                        DEFAULT SYSUTCDATETIME(),

                    CONSTRAINT CK_betting_slips_department
                CHECK (department IN ('SEN', 'U', 'MOT', 'VET')),

                        CONSTRAINT CK_betting_slips_status
                        CHECK (
                            status IN (
                                'open',
                                'settled',
                                'cancelled'
                            )
                        ),

                    CONSTRAINT FK_betting_slips_user
                        FOREIGN KEY (user_id)
                        REFERENCES dbo.users(user_id),

                    CONSTRAINT FK_betting_slips_club
                        FOREIGN KEY (club_id)
                        REFERENCES dbo.badminton_clubs(club_id)

                );

            END
            """
        )

        # =====================================================
        # BETTING PICKS
        # =====================================================

        cursor.execute(
            f"""
            IF OBJECT_ID(
                N'dbo.betting_picks',
                N'U'
            ) IS NULL
            BEGIN

                CREATE TABLE dbo.betting_picks (

                    id INT IDENTITY(1,1)
                        PRIMARY KEY,

                    betting_slip_id INT NOT NULL,

                    line_number INT NOT NULL,

                    badminton_id {badminton_id_type}
                        NOT NULL,

                    prediction NVARCHAR(10)
                        NOT NULL,

                    matched_game_id INT NULL,

                    actual_result NVARCHAR(10)
                        NULL,

                    result NVARCHAR(10)
                        NULL,

                    created_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_betting_picks_created
                        DEFAULT SYSUTCDATETIME(),

                    updated_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_betting_picks_updated
                        DEFAULT SYSUTCDATETIME(),

                    CONSTRAINT CK_betting_picks_prediction
                        CHECK (
                            prediction IN (
                                'win',
                                'loss'
                            )
                        ),

                    CONSTRAINT CK_betting_picks_actual_result
                        CHECK (
                            actual_result IS NULL
                            OR actual_result IN (
                                'win',
                                'loss'
                            )
                        ),

                    CONSTRAINT CK_betting_picks_result
                        CHECK (
                            result IS NULL
                            OR result IN (
                                'correct',
                                'wrong',
                                'void'
                            )
                        ),

                    CONSTRAINT FK_betting_picks_slip
                        FOREIGN KEY (betting_slip_id)
                        REFERENCES dbo.betting_slips(id)
                        ON DELETE CASCADE,

                    CONSTRAINT FK_betting_picks_player
                        FOREIGN KEY (badminton_id)
                        REFERENCES dbo.badminton_players(badminton_id),

                    CONSTRAINT FK_betting_picks_game
                        FOREIGN KEY (matched_game_id)
                        REFERENCES dbo.club_match_games(id),

                    CONSTRAINT UQ_betting_pick_line
                        UNIQUE (
                            betting_slip_id,
                            line_number
                        ),

                    CONSTRAINT UQ_betting_pick_player
                        UNIQUE (
                            betting_slip_id,
                            badminton_id
                        )

                );

            END
            """
        )

        # =====================================================
        # INDEXES
        # =====================================================

        cursor.execute(
            """
            IF NOT EXISTS (
                SELECT 1
                FROM sys.indexes
                WHERE
                    name = 'IX_betting_slips_user_season'
                    AND object_id =
                        OBJECT_ID('dbo.betting_slips')
            )
            BEGIN

                CREATE INDEX
                    IX_betting_slips_user_season
                ON dbo.betting_slips (
                    user_id,
                    season_id,
                    created_at
                );

            END
            """
        )

        cursor.execute(
            """
            IF NOT EXISTS (
                SELECT 1
                FROM sys.indexes
                WHERE
                    name = 'IX_betting_picks_player'
                    AND object_id =
                        OBJECT_ID('dbo.betting_picks')
            )
            BEGIN

                CREATE INDEX
                    IX_betting_picks_player
                ON dbo.betting_picks (
                    badminton_id,
                    result
                );

            END
            """
        )

        conn.commit()

        print("=" * 70)
        print("BETTING DATABASE READY")
        print("=" * 70)
        print("dbo.betting_slips: OK")
        print("dbo.betting_picks: OK")
        print("badminton_id type:", badminton_id_type)

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    ensure_betting_tables()
