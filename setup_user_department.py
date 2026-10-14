from database import get_connection


VALID_DEPARTMENTS = (
    "SEN",
    "U",
    "MOT",
    "VET",
)


def ensure_user_department():
    """
    Tilføjer dbo.users.department hvis kolonnen ikke findes.

    Eksisterende brugere sættes til SEN.

    Gyldige værdier:
        SEN = Senior
        U   = Ungdom
        MOT = Motionist
        VET = Veteran

    Scriptet er idempotent og kan derfor køres flere gange.
    """

    conn = get_connection()
    cursor = conn.cursor()

    try:
        print()
        print("=" * 70)
        print("USER DEPARTMENT MIGRATION")
        print("=" * 70)

        # ---------------------------------------------------------
        # 1. Add department column if missing
        # ---------------------------------------------------------
        cursor.execute(
            """
            SELECT COL_LENGTH(
                'dbo.users',
                'department'
            )
            """
        )

        department_exists = (
            cursor.fetchone()[0]
            is not None
        )

        if not department_exists:

            print(
                "Tilføjer kolonnen dbo.users.department..."
            )

            cursor.execute(
                """
                ALTER TABLE dbo.users
                ADD department NVARCHAR(10) NULL
                """
            )

            conn.commit()

        else:

            print(
                "Kolonnen dbo.users.department findes allerede."
            )


        # ---------------------------------------------------------
        # 2. Existing users become Senior
        # ---------------------------------------------------------
        cursor.execute(
            """
            UPDATE dbo.users
            SET department = 'SEN'
            WHERE
                department IS NULL
                OR LTRIM(RTRIM(department)) = ''
            """
        )

        updated_users = cursor.rowcount

        conn.commit()

        print(
            f"Eksisterende brugere sat til SEN: "
            f"{updated_users}"
        )


        # ---------------------------------------------------------
        # 3. Add default constraint for future users
        # ---------------------------------------------------------
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM sys.default_constraints dc
            INNER JOIN sys.columns c
                ON c.default_object_id = dc.object_id
            INNER JOIN sys.tables t
                ON t.object_id = c.object_id
            INNER JOIN sys.schemas s
                ON s.schema_id = t.schema_id
            WHERE
                s.name = 'dbo'
                AND t.name = 'users'
                AND c.name = 'department'
            """
        )

        has_default = (
            cursor.fetchone()[0] > 0
        )

        if not has_default:

            print(
                "Tilføjer default SEN til nye brugere..."
            )

            cursor.execute(
                """
                ALTER TABLE dbo.users
                ADD CONSTRAINT DF_users_department
                DEFAULT 'SEN'
                FOR department
                """
            )

            conn.commit()

        else:

            print(
                "Default constraint findes allerede."
            )


        # ---------------------------------------------------------
        # 4. Make department NOT NULL
        # ---------------------------------------------------------
        cursor.execute(
            """
            SELECT
                IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE
                TABLE_SCHEMA = 'dbo'
                AND TABLE_NAME = 'users'
                AND COLUMN_NAME = 'department'
            """
        )

        row = cursor.fetchone()

        if row is None:

            raise RuntimeError(
                "Kunne ikke finde dbo.users.department."
            )

        if row.IS_NULLABLE == "YES":

            print(
                "Sætter department til NOT NULL..."
            )

            cursor.execute(
                """
                ALTER TABLE dbo.users
                ALTER COLUMN department NVARCHAR(10) NOT NULL
                """
            )

            conn.commit()

        else:

            print(
                "department er allerede NOT NULL."
            )


        # ---------------------------------------------------------
        # 5. Check constraint
        # ---------------------------------------------------------
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM sys.check_constraints
            WHERE
                name = 'CK_users_department'
                AND parent_object_id =
                    OBJECT_ID('dbo.users')
            """
        )

        has_check = (
            cursor.fetchone()[0] > 0
        )

        if not has_check:

            print(
                "Tilføjer validering af department..."
            )

            cursor.execute(
                """
                ALTER TABLE dbo.users
                ADD CONSTRAINT CK_users_department
                CHECK (
                    department IN (
                        'SEN',
                        'U',
                        'MOT',
                        'VET'
                    )
                )
                """
            )

            conn.commit()

        else:

            print(
                "Check constraint findes allerede."
            )


        # ---------------------------------------------------------
        # 6. Helpful index
        # ---------------------------------------------------------
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM sys.indexes
            WHERE
                name = 'IX_users_club_department'
                AND object_id =
                    OBJECT_ID('dbo.users')
            """
        )

        has_index = (
            cursor.fetchone()[0] > 0
        )

        if not has_index:

            print(
                "Opretter index på club_id + department..."
            )

            cursor.execute(
                """
                CREATE INDEX IX_users_club_department
                ON dbo.users (
                    club_id,
                    department
                )
                """
            )

            conn.commit()

        else:

            print(
                "Index findes allerede."
            )


        # ---------------------------------------------------------
        # 7. Verify result
        # ---------------------------------------------------------
        cursor.execute(
            """
            SELECT
                department,
                COUNT(*) AS users
            FROM dbo.users
            GROUP BY department
            ORDER BY department
            """
        )

        rows = cursor.fetchall()

        print()
        print("=" * 70)
        print("MIGRATION FÆRDIG")
        print("=" * 70)

        for row in rows:

            print(
                f"{row.department}: "
                f"{row.users} brugere"
            )

        print()
        print(
            "Gyldige værdier: "
            "SEN, U, MOT, VET"
        )

    except Exception:

        conn.rollback()
        raise

    finally:

        cursor.close()
        conn.close()


if __name__ == "__main__":

    ensure_user_department()
