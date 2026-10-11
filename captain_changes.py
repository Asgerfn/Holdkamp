from database import get_connection


def ensure_captain_change_table():
    """
    Opretter tabellen til kaptajnskift, hvis den ikke findes.
    """

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            IF OBJECT_ID(
                N'dbo.fantasy_team_captain_changes',
                N'U'
            ) IS NULL
            BEGIN
                CREATE TABLE dbo.fantasy_team_captain_changes (
                    id INT IDENTITY(1,1) PRIMARY KEY,

                    fantasy_team_id INT NOT NULL,

                    old_captain_badminton_id NVARCHAR(20)
                        NOT NULL,

                    new_captain_badminton_id NVARCHAR(20)
                        NOT NULL,

                    effective_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_fantasy_captain_change_effective
                        DEFAULT SYSUTCDATETIME(),

                    counts_as_substitution BIT
                        NOT NULL
                        CONSTRAINT DF_fantasy_captain_change_counts
                        DEFAULT 1,

                    created_at DATETIME2
                        NOT NULL
                        CONSTRAINT DF_fantasy_captain_change_created
                        DEFAULT SYSUTCDATETIME(),

                    CONSTRAINT FK_fantasy_captain_change_team
                    FOREIGN KEY (fantasy_team_id)
                    REFERENCES dbo.fantasy_teams(id),

                    CONSTRAINT FK_fantasy_captain_change_old_player
                    FOREIGN KEY (old_captain_badminton_id)
                    REFERENCES dbo.badminton_players(badminton_id),

                    CONSTRAINT FK_fantasy_captain_change_new_player
                    FOREIGN KEY (new_captain_badminton_id)
                    REFERENCES dbo.badminton_players(badminton_id)
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
                    name = 'IX_fantasy_captain_changes_team'
                    AND object_id =
                        OBJECT_ID(
                            'dbo.fantasy_team_captain_changes'
                        )
            )
            BEGIN
                CREATE INDEX
                    IX_fantasy_captain_changes_team
                ON dbo.fantasy_team_captain_changes (
                    fantasy_team_id,
                    effective_at
                );
            END
            """
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


def count_used_substitutions(
    cursor,
    fantasy_team_id,
):
    """
    Samlet forbrug:
    - almindelige spillerskift
    - manuelle kaptajnskift

    Et automatisk kaptajnskift ved udskiftning af selve
    kaptajnen tæller ikke ekstra.
    """

    cursor.execute(
        """
        SELECT
            (
                SELECT COUNT(*)
                FROM dbo.fantasy_team_substitutions
                WHERE fantasy_team_id = ?
            )
            +
            (
                SELECT COUNT(*)
                FROM dbo.fantasy_team_captain_changes
                WHERE
                    fantasy_team_id = ?
                    AND counts_as_substitution = 1
            )
        """,
        fantasy_team_id,
        fantasy_team_id,
    )

    return int(
        cursor.fetchone()[0]
        or 0
    )


def record_captain_change(
    cursor,
    fantasy_team_id,
    old_captain_badminton_id,
    new_captain_badminton_id,
    effective_at,
    counts_as_substitution,
):
    """
    Gemmer ét kaptajnskift i historikken.
    """

    cursor.execute(
        """
        INSERT INTO dbo.fantasy_team_captain_changes (
            fantasy_team_id,
            old_captain_badminton_id,
            new_captain_badminton_id,
            effective_at,
            counts_as_substitution
        )
        VALUES (
            ?,
            ?,
            ?,
            ?,
            ?
        )
        """,
        fantasy_team_id,
        old_captain_badminton_id,
        new_captain_badminton_id,
        effective_at,
        1 if counts_as_substitution else 0,
    )


def change_team_captain(
    cursor,
    fantasy_team_id,
    new_captain_badminton_id,
    max_substitutions,
):
    """
    Skifter kaptajn på et aktivt fantasyhold.

    Funktionen committer ikke selv.
    Caller styrer transaktionen.
    """

    used_before = count_used_substitutions(
        cursor=cursor,
        fantasy_team_id=fantasy_team_id,
    )

    if used_before >= max_substitutions:
        raise ValueError(
            "Du har allerede brugt alle "
            f"{max_substitutions} udskiftninger."
        )

    cursor.execute(
        """
        SELECT TOP 1
            ftp.badminton_id,
            p.player_name

        FROM dbo.fantasy_team_players ftp

        INNER JOIN dbo.badminton_players p
            ON p.badminton_id = ftp.badminton_id

        WHERE
            ftp.fantasy_team_id = ?
            AND ftp.active_to IS NULL
            AND ftp.is_captain = 1
        """,
        fantasy_team_id,
    )

    old_captain = cursor.fetchone()

    if old_captain is None:
        raise ValueError(
            "Holdet har ingen nuværende kaptajn."
        )

    old_captain_id = str(
        old_captain.badminton_id
    )

    new_captain_id = str(
        new_captain_badminton_id
    )

    if old_captain_id == new_captain_id:
        raise ValueError(
            "Den spiller er allerede kaptajn."
        )

    cursor.execute(
        """
        SELECT TOP 1
            ftp.badminton_id,
            p.player_name

        FROM dbo.fantasy_team_players ftp

        INNER JOIN dbo.badminton_players p
            ON p.badminton_id = ftp.badminton_id

        WHERE
            ftp.fantasy_team_id = ?
            AND ftp.badminton_id = ?
            AND ftp.active_to IS NULL
        """,
        fantasy_team_id,
        new_captain_id,
    )

    new_captain = cursor.fetchone()

    if new_captain is None:
        raise ValueError(
            "Den nye kaptajn skal være en spiller "
            "på dit nuværende hold."
        )

    cursor.execute(
        """
        SELECT SYSUTCDATETIME()
        """
    )

    effective_at = (
        cursor.fetchone()[0]
    )

    record_captain_change(
        cursor=cursor,
        fantasy_team_id=fantasy_team_id,
        old_captain_badminton_id=
            old_captain_id,
        new_captain_badminton_id=
            new_captain_id,
        effective_at=effective_at,
        counts_as_substitution=True,
    )

    cursor.execute(
        """
        UPDATE dbo.fantasy_team_players

        SET
            is_captain =
                CASE
                    WHEN badminton_id = ?
                    THEN 1
                    ELSE 0
                END,

            updated_at =
                SYSUTCDATETIME()

        WHERE
            fantasy_team_id = ?
            AND active_to IS NULL
        """,
        new_captain_id,
        fantasy_team_id,
    )

    cursor.execute(
        """
        UPDATE dbo.fantasy_teams

        SET
            updated_at =
                SYSUTCDATETIME()

        WHERE id = ?
        """,
        fantasy_team_id,
    )

    return {
        "old_captain_id":
            old_captain_id,

        "old_captain_name":
            old_captain.player_name,

        "new_captain_id":
            new_captain_id,

        "new_captain_name":
            new_captain.player_name,

        "effective_at":
            effective_at,

        "substitutions_used":
            used_before + 1,
    }
