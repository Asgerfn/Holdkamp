from database import get_connection


VALID_DEPARTMENTS = (
    "SEN",
    "U",
    "MOT",
    "VET",
)


def _column_exists(cursor, table_name, column_name):
    cursor.execute(
        """
        SELECT COL_LENGTH(?, ?)
        """,
        f"dbo.{table_name}",
        column_name,
    )
    return cursor.fetchone()[0] is not None


def _constraint_exists(cursor, table_name, constraint_name):
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM sys.objects
        WHERE
            parent_object_id = OBJECT_ID(?)
            AND name = ?
            AND type IN ('C', 'D', 'UQ')
        """,
        f"dbo.{table_name}",
        constraint_name,
    )
    return int(cursor.fetchone()[0] or 0) > 0


def _index_exists(cursor, table_name, index_name):
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM sys.indexes
        WHERE
            object_id = OBJECT_ID(?)
            AND name = ?
        """,
        f"dbo.{table_name}",
        index_name,
    )
    return int(cursor.fetchone()[0] or 0) > 0


def _table_exists(cursor, table_name):
    cursor.execute(
        """
        SELECT OBJECT_ID(?, 'U')
        """,
        f"dbo.{table_name}",
    )
    return cursor.fetchone()[0] is not None


def _ensure_department_column(
    cursor,
    table_name,
    *,
    allow_null=False,
):
    """
    Adds department to an existing app-owned table.
    Existing tenant-owned rows are migrated to SEN.
    Shared/source-derived tables may keep NULL until backfill.
    """
    if not _table_exists(cursor, table_name):
        print(f"[SKIP] dbo.{table_name} findes ikke.")
        return

    if not _column_exists(
        cursor,
        table_name,
        "department",
    ):
        print(
            f"[ADD] dbo.{table_name}.department"
        )
        cursor.execute(
            f"""
            ALTER TABLE dbo.{table_name}
            ADD department NVARCHAR(10) NULL
            """
        )

    if not allow_null:
        cursor.execute(
            f"""
            UPDATE dbo.{table_name}
            SET department = 'SEN'
            WHERE
                department IS NULL
                OR LTRIM(RTRIM(department)) = ''
            """
        )

    if not allow_null:
        cursor.execute(
            f"""
            ALTER TABLE dbo.{table_name}
            ALTER COLUMN department
                NVARCHAR(10) NOT NULL
            """
        )

    default_name = (
        f"DF_{table_name}_department"
    )

    if not _constraint_exists(
        cursor,
        table_name,
        default_name,
    ):
        # Only add defaults to tables where every new row
        # should always belong to a tenant.
        if not allow_null:
            cursor.execute(
                f"""
                ALTER TABLE dbo.{table_name}
                ADD CONSTRAINT {default_name}
                DEFAULT 'SEN'
                FOR department
                """
            )

    check_name = (
        f"CK_{table_name}_department"
    )

    if not _constraint_exists(
        cursor,
        table_name,
        check_name,
    ):
        null_clause = (
            "department IS NULL OR "
            if allow_null
            else ""
        )

        cursor.execute(
            f"""
            ALTER TABLE dbo.{table_name}
            ADD CONSTRAINT {check_name}
            CHECK (
                {null_clause}
                department IN (
                    'SEN',
                    'U',
                    'MOT',
                    'VET'
                )
            )
            """
        )


def migrate_department_isolation():
    """
    Makes club_id + department the tenant boundary for
    user/app-owned data.

    Existing app data belongs to SEN, matching the migration
    of all existing profiles to Senior.
    """

    conn = get_connection()
    cursor = conn.cursor()

    try:
        print()
        print("=" * 72)
        print("DEPARTMENT ISOLATION MIGRATION")
        print("=" * 72)

        # -----------------------------------------------------
        # Users were migrated earlier, but keep this script
        # safe if it is run on a database that has not done so.
        # -----------------------------------------------------
        _ensure_department_column(
            cursor,
            "users",
        )

        # -----------------------------------------------------
        # Fantasy rules
        # -----------------------------------------------------
        _ensure_department_column(
            cursor,
            "fantasy_team_rules",
        )

        if _table_exists(
            cursor,
            "fantasy_team_rules",
        ):
            if _constraint_exists(
                cursor,
                "fantasy_team_rules",
                "UQ_fantasy_team_rules",
            ):
                cursor.execute(
                    """
                    ALTER TABLE dbo.fantasy_team_rules
                    DROP CONSTRAINT UQ_fantasy_team_rules
                    """
                )

            if not _constraint_exists(
                cursor,
                "fantasy_team_rules",
                "UQ_fantasy_team_rules_department",
            ):
                cursor.execute(
                    """
                    ALTER TABLE dbo.fantasy_team_rules
                    ADD CONSTRAINT
                        UQ_fantasy_team_rules_department
                    UNIQUE (
                        club_id,
                        season_id,
                        department
                    )
                    """
                )

            if not _index_exists(
                cursor,
                "fantasy_team_rules",
                "IX_fantasy_team_rules_tenant",
            ):
                cursor.execute(
                    """
                    CREATE INDEX
                        IX_fantasy_team_rules_tenant
                    ON dbo.fantasy_team_rules (
                        club_id,
                        department,
                        season_id
                    )
                    """
                )

        # -----------------------------------------------------
        # Fantasy teams
        # -----------------------------------------------------
        _ensure_department_column(
            cursor,
            "fantasy_teams",
        )

        if _table_exists(
            cursor,
            "fantasy_teams",
        ):
            if _constraint_exists(
                cursor,
                "fantasy_teams",
                "UQ_fantasy_teams_user_season",
            ):
                cursor.execute(
                    """
                    ALTER TABLE dbo.fantasy_teams
                    DROP CONSTRAINT
                        UQ_fantasy_teams_user_season
                    """
                )

            if not _constraint_exists(
                cursor,
                "fantasy_teams",
                "UQ_fantasy_teams_user_department_season",
            ):
                cursor.execute(
                    """
                    ALTER TABLE dbo.fantasy_teams
                    ADD CONSTRAINT
                        UQ_fantasy_teams_user_department_season
                    UNIQUE (
                        user_id,
                        club_id,
                        season_id,
                        department
                    )
                    """
                )

            if not _index_exists(
                cursor,
                "fantasy_teams",
                "IX_fantasy_teams_tenant",
            ):
                cursor.execute(
                    """
                    CREATE INDEX
                        IX_fantasy_teams_tenant
                    ON dbo.fantasy_teams (
                        club_id,
                        department,
                        season_id,
                        status
                    )
                    """
                )

        # -----------------------------------------------------
        # Rule-adjustment history
        # -----------------------------------------------------
        _ensure_department_column(
            cursor,
            "fantasy_team_rule_adjustments",
        )

        if (
            _table_exists(
                cursor,
                "fantasy_team_rule_adjustments",
            )
            and not _index_exists(
                cursor,
                "fantasy_team_rule_adjustments",
                "IX_fantasy_rule_adjustments_tenant",
            )
        ):
            cursor.execute(
                """
                CREATE INDEX
                    IX_fantasy_rule_adjustments_tenant
                ON dbo.fantasy_team_rule_adjustments (
                    club_id,
                    department,
                    season_id,
                    status,
                    deadline_at
                )
                """
            )

        # -----------------------------------------------------
        # Betting
        # -----------------------------------------------------
        _ensure_department_column(
            cursor,
            "betting_slips",
        )

        if (
            _table_exists(
                cursor,
                "betting_slips",
            )
            and not _index_exists(
                cursor,
                "betting_slips",
                "IX_betting_slips_tenant",
            )
        ):
            cursor.execute(
                """
                CREATE INDEX
                    IX_betting_slips_tenant
                ON dbo.betting_slips (
                    club_id,
                    department,
                    season_id,
                    user_id,
                    created_at
                )
                """
            )

        # -----------------------------------------------------
        # Fantasy point events
        #
        # These are match facts rather than user-owned rows,
        # so department may be NULL when an old match cannot
        # be linked back to a dashboard team.
        # -----------------------------------------------------
        _ensure_department_column(
            cursor,
            "fantasy_point_events",
            allow_null=True,
        )

        if _table_exists(
            cursor,
            "fantasy_point_events",
        ):
            print(
                "[BACKFILL] fantasy_point_events.department"
            )

            cursor.execute(
                """
                UPDATE fpe
                SET department = mapped.department

                FROM dbo.fantasy_point_events fpe

                INNER JOIN dbo.club_matches cm
                    ON cm.id = fpe.club_match_id

                OUTER APPLY (
                    SELECT TOP 1
                        cdt.department

                    FROM dbo.club_dashboard_teams cdt

                    WHERE
                        cdt.club_id = cm.club_id
                        AND cdt.season_id =
                            cm.season_id
                        AND cdt.league_group_id =
                            cm.league_group_id
                        AND cdt.team_name =
                            cm.club_team_name

                    ORDER BY cdt.id
                ) mapped

                WHERE
                    mapped.department IS NOT NULL
                    AND (
                        fpe.department IS NULL
                        OR fpe.department <> mapped.department
                    )
                """
            )

            if not _index_exists(
                cursor,
                "fantasy_point_events",
                "IX_fantasy_point_events_department",
            ):
                cursor.execute(
                    """
                    CREATE INDEX
                        IX_fantasy_point_events_department
                    ON dbo.fantasy_point_events (
                        club_id,
                        department,
                        season_id,
                        badminton_id
                    )
                    """
                )

        # -----------------------------------------------------
        # Department player view
        #
        # A club player belongs to a department when the player
        # has appeared in a match for one of that department's
        # teams. App queries can fall back to the full club roster
        # when a department has no match history yet.
        # -----------------------------------------------------
        if (
            _table_exists(cursor, "club_dashboard_teams")
            and _table_exists(cursor, "club_matches")
            and _table_exists(cursor, "club_match_games")
            and _table_exists(cursor, "club_match_game_players")
        ):
            cursor.execute(
                """
                CREATE OR ALTER VIEW
                    dbo.v_department_players
                AS

                SELECT DISTINCT
                    cm.club_id,
                    cm.season_id,
                    cdt.department,
                    gp.badminton_id

                FROM dbo.club_match_game_players gp

                INNER JOIN dbo.club_match_games g
                    ON g.id = gp.game_id

                INNER JOIN dbo.club_matches cm
                    ON cm.id = g.club_match_id

                INNER JOIN dbo.club_dashboard_teams cdt
                    ON cdt.club_id = cm.club_id
                    AND cdt.season_id = cm.season_id
                    AND cdt.league_group_id =
                        cm.league_group_id
                    AND cdt.team_name =
                        cm.club_team_name

                WHERE
                    gp.badminton_id IS NOT NULL
                """
            )


        # -----------------------------------------------------
        # Dashboard teams already have the real BadmintonPlayer
        # department. Existing profiles are now SEN, so old
        # non-senior selections should not silently become the
        # starting configuration of a future U/MOT/VET tenant.
        # -----------------------------------------------------
        if _table_exists(
            cursor,
            "club_dashboard_teams",
        ):
            cursor.execute(
                """
                UPDATE dbo.club_dashboard_teams
                SET
                    is_active = 0,
                    updated_at = SYSUTCDATETIME()
                WHERE
                    department <> 'SEN'
                    AND is_active = 1
                """
            )

        conn.commit()

        print()
        print("=" * 72)
        print("MIGRATION FÆRDIG")
        print("=" * 72)

        # Small verification
        checks = [
            "users",
            "fantasy_team_rules",
            "fantasy_teams",
            "fantasy_team_rule_adjustments",
            "betting_slips",
            "fantasy_point_events",
        ]

        for table_name in checks:
            if not _table_exists(
                cursor,
                table_name,
            ):
                continue

            if not _column_exists(
                cursor,
                table_name,
                "department",
            ):
                continue

            cursor.execute(
                f"""
                SELECT
                    COALESCE(department, '<NULL>'),
                    COUNT(*)
                FROM dbo.{table_name}
                GROUP BY department
                ORDER BY department
                """
            )

            values = ", ".join(
                f"{row[0]}={row[1]}"
                for row in cursor.fetchall()
            )

            print(
                f"dbo.{table_name}: {values or '0 rows'}"
            )

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    migrate_department_isolation()
