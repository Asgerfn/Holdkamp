from database import get_connection

from captain_changes import (
    ensure_captain_change_table,
    record_captain_change,
)


# =========================================================
# TABLE
# =========================================================

def ensure_rule_adjustment_table():
    """
    Opretter historiktabellen til gratis holdtilpasninger,
    som opstår når en administrator ændrer holdstørrelsen
    midt i sæsonen.
    """

    ensure_captain_change_table()

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            IF OBJECT_ID(
                N'dbo.fantasy_team_rule_adjustments',
                N'U'
            ) IS NULL
            BEGIN
                CREATE TABLE dbo.fantasy_team_rule_adjustments (
                    id INT IDENTITY(1,1) PRIMARY KEY,

                    fantasy_team_id INT NOT NULL,
                    club_id INT NOT NULL,
                    season_id INT NOT NULL,

                    department NVARCHAR(10) NOT NULL
                        CONSTRAINT DF_fantasy_rule_adjustment_department
                        DEFAULT 'SEN',

                    gender NVARCHAR(1) NOT NULL,
                    required_count INT NOT NULL,

                    direction NVARCHAR(10) NOT NULL,
                    amount INT NOT NULL,

                    rule_changed_at DATETIME2 NOT NULL,
                    deadline_at DATETIME2 NULL,

                    status NVARCHAR(20) NOT NULL
                        CONSTRAINT DF_fantasy_rule_adjustment_status
                        DEFAULT 'pending',

                    resolved_at DATETIME2 NULL,
                    resolution_note NVARCHAR(500) NULL,

                    created_at DATETIME2 NOT NULL
                        CONSTRAINT DF_fantasy_rule_adjustment_created
                        DEFAULT SYSUTCDATETIME(),

                    CONSTRAINT FK_fantasy_rule_adjustment_team
                    FOREIGN KEY (fantasy_team_id)
                    REFERENCES dbo.fantasy_teams(id),

                    CONSTRAINT CK_fantasy_rule_adjustment_department
                    CHECK (
                        department IN (
                            'SEN',
                            'U',
                            'MOT',
                            'VET'
                        )
                    ),

                    CONSTRAINT CK_fantasy_rule_adjustment_gender
                    CHECK (gender IN ('M', 'K')),

                    CONSTRAINT CK_fantasy_rule_adjustment_direction
                    CHECK (direction IN ('add', 'remove')),

                    CONSTRAINT CK_fantasy_rule_adjustment_amount
                    CHECK (amount >= 0)
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
                    name = 'IX_fantasy_rule_adjustments_team_status'
                    AND object_id =
                        OBJECT_ID(
                            'dbo.fantasy_team_rule_adjustments'
                        )
            )
            BEGIN
                CREATE INDEX
                    IX_fantasy_rule_adjustments_team_status
                ON dbo.fantasy_team_rule_adjustments (
                    fantasy_team_id,
                    status,
                    gender
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
                    name = 'IX_fantasy_rule_adjustments_deadline'
                    AND object_id =
                        OBJECT_ID(
                            'dbo.fantasy_team_rule_adjustments'
                        )
            )
            BEGIN
                CREATE INDEX
                    IX_fantasy_rule_adjustments_deadline
                ON dbo.fantasy_team_rule_adjustments (
                    club_id,
                    department,
                    season_id,
                    status,
                    deadline_at
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


# =========================================================
# SMALL HELPERS
# =========================================================

def _db_now(cursor):
    cursor.execute(
        """
        SELECT SYSUTCDATETIME()
        """
    )

    return cursor.fetchone()[0]


def _next_match_time(
    cursor,
    club_id,
    season_id,
    department,
    after_time,
):
    cursor.execute(
        """
        SELECT MIN(match_time)

        FROM dbo.club_matches cm

        INNER JOIN dbo.club_dashboard_teams cdt
            ON cdt.club_id = cm.club_id
            AND cdt.season_id = cm.season_id
            AND cdt.league_group_id = cm.league_group_id
            AND cdt.team_name = cm.club_team_name

        WHERE
            cm.club_id = ?
            AND cm.season_id = ?
            AND cdt.department = ?
            AND cm.match_time > ?
        """,
        club_id,
        season_id,
        department,
        after_time,
    )

    row = cursor.fetchone()

    if row is None:
        return None

    return row[0]


def _active_gender_count(
    cursor,
    fantasy_team_id,
    gender,
):
    cursor.execute(
        """
        SELECT COUNT(*)

        FROM dbo.fantasy_team_players ftp

        INNER JOIN dbo.badminton_players p
            ON p.badminton_id = ftp.badminton_id

        WHERE
            ftp.fantasy_team_id = ?
            AND ftp.active_to IS NULL
            AND p.gender = ?
        """,
        fantasy_team_id,
        gender,
    )

    return int(
        cursor.fetchone()[0]
        or 0
    )


def _load_adjustment(
    cursor,
    adjustment_id,
    fantasy_team_id=None,
    require_pending=True,
):
    sql = """
        SELECT
            id,
            fantasy_team_id,
            club_id,
            season_id,
            department,
            gender,
            required_count,
            direction,
            amount,
            rule_changed_at,
            deadline_at,
            status

        FROM dbo.fantasy_team_rule_adjustments

        WHERE id = ?
    """

    params = [adjustment_id]

    if fantasy_team_id is not None:
        sql += """
            AND fantasy_team_id = ?
        """
        params.append(fantasy_team_id)

    if require_pending:
        sql += """
            AND status = 'pending'
        """

    cursor.execute(
        sql,
        *params,
    )

    return cursor.fetchone()


def _reconcile_adjustment(
    cursor,
    adjustment_id,
    resolved_status="resolved",
    resolution_note=None,
):
    adjustment = _load_adjustment(
        cursor=cursor,
        adjustment_id=adjustment_id,
        require_pending=False,
    )

    if adjustment is None:
        return None

    current_count = _active_gender_count(
        cursor=cursor,
        fantasy_team_id=adjustment.fantasy_team_id,
        gender=adjustment.gender,
    )

    required_count = int(
        adjustment.required_count
    )

    if current_count == required_count:
        cursor.execute(
            """
            UPDATE dbo.fantasy_team_rule_adjustments

            SET
                amount = 0,
                status = ?,
                resolved_at = SYSUTCDATETIME(),
                resolution_note =
                    COALESCE(?, resolution_note)

            WHERE id = ?
            """,
            resolved_status,
            resolution_note,
            adjustment_id,
        )

        return {
            "status":
                resolved_status,

            "current_count":
                current_count,

            "required_count":
                required_count,

            "amount":
                0,
        }

    direction = (
        "remove"
        if current_count > required_count
        else "add"
    )

    amount = abs(
        current_count
        -
        required_count
    )

    cursor.execute(
        """
        UPDATE dbo.fantasy_team_rule_adjustments

        SET
            direction = ?,
            amount = ?,
            status = 'pending',
            resolved_at = NULL

        WHERE id = ?
        """,
        direction,
        amount,
        adjustment_id,
    )

    return {
        "status":
            "pending",

        "current_count":
            current_count,

        "required_count":
            required_count,

        "direction":
            direction,

        "amount":
            amount,
    }


def _choose_replacement_captain(
    cursor,
    fantasy_team_id,
    excluded_badminton_id,
):
    cursor.execute(
        """
        SELECT TOP 1
            ftp.badminton_id

        FROM dbo.fantasy_team_players ftp

        WHERE
            ftp.fantasy_team_id = ?
            AND ftp.active_to IS NULL
            AND ftp.badminton_id <> ?

        ORDER BY NEWID()
        """,
        fantasy_team_id,
        excluded_badminton_id,
    )

    row = cursor.fetchone()

    if row is None:
        return None

    return str(
        row.badminton_id
    )


def _remove_active_player(
    cursor,
    fantasy_team_id,
    badminton_id,
    effective_at,
):
    """
    Lukker en spillers aktive periode.

    Hvis spilleren er kaptajn, vælges en ny kaptajn gratis
    blandt de øvrige aktive spillere.
    """

    cursor.execute(
        """
        SELECT TOP 1
            ftp.id,
            ftp.badminton_id,
            ftp.is_captain,

            p.player_name,
            p.gender

        FROM dbo.fantasy_team_players ftp

        INNER JOIN dbo.badminton_players p
            ON p.badminton_id = ftp.badminton_id

        WHERE
            ftp.fantasy_team_id = ?
            AND ftp.badminton_id = ?
            AND ftp.active_to IS NULL
        """,
        fantasy_team_id,
        badminton_id,
    )

    outgoing = cursor.fetchone()

    if outgoing is None:
        raise ValueError(
            "Spilleren er ikke længere på det aktive hold."
        )

    new_captain_id = None

    if bool(
        outgoing.is_captain
    ):
        new_captain_id = (
            _choose_replacement_captain(
                cursor=cursor,
                fantasy_team_id=
                    fantasy_team_id,
                excluded_badminton_id=
                    outgoing.badminton_id,
            )
        )

        if new_captain_id is not None:

            record_captain_change(
                cursor=cursor,
                fantasy_team_id=
                    fantasy_team_id,
                old_captain_badminton_id=
                    str(
                        outgoing.badminton_id
                    ),
                new_captain_badminton_id=
                    new_captain_id,
                effective_at=
                    effective_at,
                counts_as_substitution=
                    False,
            )

            cursor.execute(
                """
                UPDATE dbo.fantasy_team_players

                SET
                    is_captain =
                        CASE
                            WHEN badminton_id = ?
                            THEN 1
                            ELSE is_captain
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
        UPDATE dbo.fantasy_team_players

        SET
            active_to = ?,
            updated_at =
                SYSUTCDATETIME()

        WHERE
            id = ?
            AND active_to IS NULL
        """,
        effective_at,
        outgoing.id,
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
        "badminton_id":
            str(
                outgoing.badminton_id
            ),

        "player_name":
            outgoing.player_name,

        "gender":
            outgoing.gender,

        "was_captain":
            bool(
                outgoing.is_captain
            ),

        "new_captain_id":
            new_captain_id,
    }


# =========================================================
# CREATE ADJUSTMENTS AFTER ADMIN RULE CHANGE
# =========================================================

def create_rule_adjustments_for_active_teams(
    cursor,
    club_id,
    season_id,
    department,
    male_required,
    female_required,
    changed_at=None,
):
    """
    Reconciler alle aktive fantasyhold mod de nye regler.

    Gamle pending-regeltilpasninger supersedes, så en ny
    admin-ændring altid bliver den gældende version.
    """

    if changed_at is None:
        changed_at = (
            _db_now(
                cursor
            )
        )

    deadline_at = (
        _next_match_time(
            cursor=cursor,
            club_id=club_id,
            season_id=season_id,
            department=department,
            after_time=changed_at,
        )
    )

    cursor.execute(
        """
        SELECT id

        FROM dbo.fantasy_teams

        WHERE
            club_id = ?
            AND season_id = ?
            AND department = ?
            AND status = 'active'
        """,
        club_id,
        season_id,
        department,
    )

    team_ids = [
        int(
            row.id
        )
        for row
        in cursor.fetchall()
    ]

    if team_ids:
        placeholders = ",".join(
            "?"
            for _ in team_ids
        )

        cursor.execute(
            f"""
            UPDATE dbo.fantasy_team_rule_adjustments

            SET
                status = 'superseded',
                resolved_at =
                    SYSUTCDATETIME(),
                resolution_note =
                    'Erstattet af en nyere holdregel.'

            WHERE
                status = 'pending'
                AND fantasy_team_id IN (
                    {placeholders}
                )
            """,
            *team_ids,
        )

    created = []

    required_by_gender = {
        "M":
            int(
                male_required
            ),

        "K":
            int(
                female_required
            ),
    }

    for fantasy_team_id in team_ids:

        for (
            gender,
            required_count
        ) in required_by_gender.items():

            current_count = (
                _active_gender_count(
                    cursor=cursor,
                    fantasy_team_id=
                        fantasy_team_id,
                    gender=gender,
                )
            )

            if (
                current_count
                ==
                required_count
            ):
                continue

            direction = (
                "remove"
                if current_count > required_count
                else "add"
            )

            amount = abs(
                current_count
                -
                required_count
            )

            cursor.execute(
                """
                INSERT INTO
                    dbo.fantasy_team_rule_adjustments
                (
                    fantasy_team_id,
                    club_id,
                    season_id,
                    department,
                    gender,
                    required_count,
                    direction,
                    amount,
                    rule_changed_at,
                    deadline_at,
                    status
                )

                OUTPUT INSERTED.id

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
                    'pending'
                )
                """,
                fantasy_team_id,
                club_id,
                season_id,
                department,
                gender,
                required_count,
                direction,
                amount,
                changed_at,
                deadline_at,
            )

            adjustment_id = int(
                cursor.fetchone()[0]
            )

            created.append(
                {
                    "id":
                        adjustment_id,

                    "fantasy_team_id":
                        fantasy_team_id,

                    "gender":
                        gender,

                    "direction":
                        direction,

                    "amount":
                        amount,

                    "deadline_at":
                        deadline_at,
                }
            )

    return created


# =========================================================
# LOAD PENDING ADJUSTMENTS
# =========================================================

def get_pending_rule_adjustments(
    cursor,
    fantasy_team_id,
):
    cursor.execute(
        """
        SELECT
            id,
            fantasy_team_id,
            club_id,
            season_id,
            department,
            gender,
            required_count,
            direction,
            amount,
            rule_changed_at,
            deadline_at,
            status

        FROM dbo.fantasy_team_rule_adjustments

        WHERE
            fantasy_team_id = ?
            AND status = 'pending'

        ORDER BY
            CASE gender
                WHEN 'M' THEN 0
                ELSE 1
            END,
            id
        """,
        fantasy_team_id,
    )

    rows = list(
        cursor.fetchall()
    )

    result = []

    now = _db_now(
        cursor
    )

    for row in rows:
        deadline_at = (
            row.deadline_at
        )

        if deadline_at is None:
            deadline_at = (
                _next_match_time(
                    cursor=cursor,
                    club_id=row.club_id,
                    season_id=row.season_id,
                    department=row.department,
                    after_time=
                        row.rule_changed_at,
                )
            )

            if (
                deadline_at
                is not None
            ):
                cursor.execute(
                    """
                    UPDATE
                        dbo.fantasy_team_rule_adjustments

                    SET deadline_at = ?

                    WHERE
                        id = ?
                        AND status = 'pending'
                    """,
                    deadline_at,
                    row.id,
                )

        state = (
            _reconcile_adjustment(
                cursor=cursor,
                adjustment_id=
                    row.id,
            )
        )

        if (
            state is None
            or
            state[
                "status"
            ]
            != "pending"
        ):
            continue

        result.append(
            {
                "id":
                    int(
                        row.id
                    ),

                "gender":
                    row.gender,

                "gender_label":
                    (
                        "herrer"
                        if row.gender == "M"
                        else "damer"
                    ),

                "required_count":
                    int(
                        row.required_count
                    ),

                "direction":
                    state[
                        "direction"
                    ],

                "amount":
                    int(
                        state[
                            "amount"
                        ]
                    ),

                "current_count":
                    int(
                        state[
                            "current_count"
                        ]
                    ),

                "rule_changed_at":
                    row.rule_changed_at,

                "deadline_at":
                    deadline_at,

                "is_overdue":
                    bool(
                        deadline_at is not None
                        and
                        deadline_at <= now
                    ),
            }
        )

    return result


# =========================================================
# MANUAL FREE ADD
# =========================================================

def apply_rule_adjustment_add(
    cursor,
    adjustment_id,
    fantasy_team_id,
    badminton_id,
):
    adjustment = _load_adjustment(
        cursor=cursor,
        adjustment_id=
            adjustment_id,
        fantasy_team_id=
            fantasy_team_id,
        require_pending=True,
    )

    if (
        adjustment is None
        or
        adjustment.direction != "add"
    ):
        raise ValueError(
            "Denne regeltilpasning er ikke længere aktiv."
        )

    current_count = (
        _active_gender_count(
            cursor=cursor,
            fantasy_team_id=
                fantasy_team_id,
            gender=
                adjustment.gender,
        )
    )

    if (
        current_count
        >=
        adjustment.required_count
    ):
        _reconcile_adjustment(
            cursor=cursor,
            adjustment_id=
                adjustment.id,
        )

        raise ValueError(
            "Holdet opfylder allerede den nye regel."
        )

    cursor.execute(
        """
        SELECT TOP 1
            p.badminton_id,
            p.player_name,
            p.gender

        FROM dbo.club_players cp

        INNER JOIN dbo.badminton_players p
            ON p.badminton_id =
                cp.badminton_id

        WHERE
            cp.club_id = ?
            AND cp.season_id = ?
            AND cp.is_active = 1
            AND p.badminton_id = ?
            AND p.gender = ?
        """,
        adjustment.club_id,
        adjustment.season_id,
        badminton_id,
        adjustment.gender,
    )

    incoming = cursor.fetchone()

    if incoming is None:
        raise ValueError(
            "Den valgte spiller kan ikke tilføjes "
            "til denne regeltilpasning."
        )

    cursor.execute(
        """
        SELECT COUNT(*)

        FROM dbo.fantasy_team_players

        WHERE
            fantasy_team_id = ?
            AND badminton_id = ?
            AND active_to IS NULL
        """,
        fantasy_team_id,
        badminton_id,
    )

    if (
        cursor.fetchone()[0]
        >
        0
    ):
        raise ValueError(
            "Spilleren er allerede på dit hold."
        )

    cursor.execute(
        """
        SELECT COUNT(*)

        FROM dbo.fantasy_team_players

        WHERE
            fantasy_team_id = ?
            AND active_to IS NULL
            AND is_captain = 1
        """,
        fantasy_team_id,
    )

    make_captain = (
        int(
            cursor.fetchone()[0]
            or 0
        )
        == 0
    )


    effective_at = _db_now(
        cursor
    )

    # Brug den allerede accepterede selection_type
    # "substitution", men opret IKKE en række i
    # fantasy_team_substitutions. Derfor tæller handlingen
    # ikke som en normal udskiftning.
    cursor.execute(
        """
        INSERT INTO dbo.fantasy_team_players (
            fantasy_team_id,
            badminton_id,
            is_captain,
            active_from,
            active_to,
            selection_type,
            substitution_id
        )
        VALUES (
            ?,
            ?,
            ?,
            ?,
            NULL,
            'substitution',
            NULL
        )
        """,
        fantasy_team_id,
        badminton_id,
        1 if make_captain else 0,
        effective_at,
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

    state = (
        _reconcile_adjustment(
            cursor=cursor,
            adjustment_id=
                adjustment.id,
            resolution_note=
                "Spiller tilføjet manuelt efter regelændring.",
        )
    )

    return {
        "player_name":
            incoming.player_name,

        "effective_at":
            effective_at,

        "remaining":
            int(
                state[
                    "amount"
                ]
                if state
                else 0
            ),

        "became_captain":
            make_captain,
    }



# =========================================================
# MANUAL FREE REMOVE
# =========================================================

def apply_rule_adjustment_remove(
    cursor,
    adjustment_id,
    fantasy_team_id,
    badminton_id,
):
    adjustment = _load_adjustment(
        cursor=cursor,
        adjustment_id=
            adjustment_id,
        fantasy_team_id=
            fantasy_team_id,
        require_pending=True,
    )

    if (
        adjustment is None
        or
        adjustment.direction != "remove"
    ):
        raise ValueError(
            "Denne regeltilpasning er ikke længere aktiv."
        )

    cursor.execute(
        """
        SELECT TOP 1
            ftp.badminton_id,
            p.gender

        FROM dbo.fantasy_team_players ftp

        INNER JOIN dbo.badminton_players p
            ON p.badminton_id =
                ftp.badminton_id

        WHERE
            ftp.fantasy_team_id = ?
            AND ftp.badminton_id = ?
            AND ftp.active_to IS NULL
            AND p.gender = ?
        """,
        fantasy_team_id,
        badminton_id,
        adjustment.gender,
    )

    if (
        cursor.fetchone()
        is None
    ):
        raise ValueError(
            "Den valgte spiller kan ikke fjernes "
            "som en del af denne regeltilpasning."
        )

    current_count = (
        _active_gender_count(
            cursor=cursor,
            fantasy_team_id=
                fantasy_team_id,
            gender=
                adjustment.gender,
        )
    )

    if (
        current_count
        <=
        adjustment.required_count
    ):
        _reconcile_adjustment(
            cursor=cursor,
            adjustment_id=
                adjustment.id,
        )

        raise ValueError(
            "Holdet opfylder allerede den nye regel."
        )

    effective_at = (
        _db_now(
            cursor
        )
    )

    removed = (
        _remove_active_player(
            cursor=cursor,
            fantasy_team_id=
                fantasy_team_id,
            badminton_id=
                badminton_id,
            effective_at=
                effective_at,
        )
    )

    state = (
        _reconcile_adjustment(
            cursor=cursor,
            adjustment_id=
                adjustment.id,
            resolution_note=
                "Spiller fjernet manuelt efter regelændring.",
        )
    )

    removed[
        "remaining"
    ] = int(
        state[
            "amount"
        ]
        if state
        else 0
    )

    removed[
        "effective_at"
    ] = effective_at

    return removed


# =========================================================
# AUTO ENFORCEMENT
# =========================================================

def enforce_due_rule_adjustments(
    cursor,
    club_id,
    season_id,
    department,
    as_of,
    infer_null_deadline=False,
):
    """
    Fjerner automatisk overskydende spillere ved deadline.

    - Kun "remove"-tilpasninger håndhæves automatisk.
    - Ikke-kaptajner vælges før kaptajnen.
    - Blandt egnede spillere vælges tilfældigt.
    - Hvis deadline endnu ikke var kendt, kan det aktuelle
      match bruges som deadline ved pointberegningen.
    """

    if infer_null_deadline:
        cursor.execute(
            """
            SELECT
                id,
                rule_changed_at

            FROM dbo.fantasy_team_rule_adjustments

            WHERE
                club_id = ?
                AND season_id = ?
                AND department = ?
                AND status = 'pending'
                AND direction = 'remove'
                AND deadline_at IS NULL
                AND rule_changed_at < ?
            """,
            club_id,
            season_id,
            department,
            as_of,
        )

        rows_without_deadline = list(
            cursor.fetchall()
        )

        for row in rows_without_deadline:
            inferred_deadline = (
                _next_match_time(
                    cursor=cursor,
                    club_id=club_id,
                    season_id=season_id,
                    department=department,
                    after_time=
                        row.rule_changed_at,
                )
            )

            if (
                inferred_deadline
                is not None
                and
                inferred_deadline <= as_of
            ):
                cursor.execute(
                    """
                    UPDATE dbo.fantasy_team_rule_adjustments

                    SET deadline_at = ?

                    WHERE
                        id = ?
                        AND status = 'pending'
                    """,
                    inferred_deadline,
                    row.id,
                )

    cursor.execute(
        """
        SELECT
            id,
            fantasy_team_id,
            gender,
            required_count,
            deadline_at

        FROM dbo.fantasy_team_rule_adjustments

        WHERE
            club_id = ?
            AND season_id = ?
            AND department = ?
            AND status = 'pending'
            AND direction = 'remove'
            AND deadline_at IS NOT NULL
            AND deadline_at <= ?

        ORDER BY
            deadline_at,
            id
        """,
        club_id,
        season_id,
        department,
        as_of,
    )

    due_rows = list(
        cursor.fetchall()
    )

    auto_removed = []

    for adjustment in due_rows:
        state = (
            _reconcile_adjustment(
                cursor=cursor,
                adjustment_id=
                    adjustment.id,
            )
        )

        if (
            state is None
            or
            state[
                "status"
            ]
            != "pending"
            or
            state[
                "direction"
            ]
            != "remove"
        ):
            continue

        effective_at = (
            adjustment.deadline_at
            or
            as_of
        )

        while (
            _active_gender_count(
                cursor=cursor,
                fantasy_team_id=
                    adjustment.fantasy_team_id,
                gender=
                    adjustment.gender,
            )
            >
            adjustment.required_count
        ):
            cursor.execute(
                """
                SELECT TOP 1
                    ftp.badminton_id

                FROM dbo.fantasy_team_players ftp

                INNER JOIN dbo.badminton_players p
                    ON p.badminton_id =
                        ftp.badminton_id

                WHERE
                    ftp.fantasy_team_id = ?
                    AND ftp.active_to IS NULL
                    AND p.gender = ?

                ORDER BY
                    CASE
                        WHEN ftp.is_captain = 0
                        THEN 0
                        ELSE 1
                    END,
                    NEWID()
                """,
                adjustment.fantasy_team_id,
                adjustment.gender,
            )

            candidate = (
                cursor.fetchone()
            )

            if candidate is None:
                break

            removed = (
                _remove_active_player(
                    cursor=cursor,
                    fantasy_team_id=
                        adjustment.fantasy_team_id,
                    badminton_id=
                        candidate.badminton_id,
                    effective_at=
                        effective_at,
                )
            )

            removed[
                "fantasy_team_id"
            ] = int(
                adjustment.fantasy_team_id
            )

            removed[
                "adjustment_id"
            ] = int(
                adjustment.id
            )

            auto_removed.append(
                removed
            )

        final_state = (
            _reconcile_adjustment(
                cursor=cursor,
                adjustment_id=
                    adjustment.id,
                resolved_status=
                    "auto_resolved",
                resolution_note=
                    "Overskydende spiller(e) fjernet automatisk ved næste holdkamp.",
            )
        )

        if (
            final_state
            and
            final_state[
                "status"
            ]
            == "pending"
        ):
            # Sikkerhed: behold pending hvis data af en eller
            # anden grund ikke kunne bringes ned på kravet.
            pass

    return auto_removed
