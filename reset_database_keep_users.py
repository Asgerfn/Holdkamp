from database import get_connection

# Bevar brugerne og de klubrækker, som users.club_id peger på.
# Alt andet data i dbo-tabeller slettes.
PRESERVE_TABLES = {
    "users",
    "badminton_clubs",
}

CONFIRM_TEXT = "RESET ALL EXCEPT USERS"


def qident(name: str) -> str:
    """SQL Server-safe quoted identifier."""
    return "[" + name.replace("]", "]]") + "]"


def main():
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                s.name AS schema_name,
                t.name AS table_name
            FROM sys.tables t
            INNER JOIN sys.schemas s
                ON s.schema_id = t.schema_id
            WHERE
                t.is_ms_shipped = 0
                AND s.name = 'dbo'
            ORDER BY t.name
            """
        )

        tables = [
            (row.schema_name, row.table_name)
            for row in cursor.fetchall()
        ]

        preserve = [
            (schema, table)
            for schema, table in tables
            if table.lower() in PRESERVE_TABLES
        ]

        delete_tables = [
            (schema, table)
            for schema, table in tables
            if table.lower() not in PRESERVE_TABLES
        ]

        print("=" * 90)
        print("DATABASE RESET")
        print("=" * 90)

        print("\nBEVARES:")
        for schema, table in preserve:
            cursor.execute(
                f"SELECT COUNT(*) FROM {qident(schema)}.{qident(table)}"
            )
            count = cursor.fetchone()[0]
            print(f"  {schema}.{table}: {count} rækker")

        print("\nSLETTES:")
        for schema, table in delete_tables:
            cursor.execute(
                f"SELECT COUNT(*) FROM {qident(schema)}.{qident(table)}"
            )
            count = cursor.fetchone()[0]
            print(f"  {schema}.{table}: {count} rækker")

        print("\nADVARSEL:")
        print("  Alle rækker i tabellerne under SLETTES bliver permanent fjernet.")
        print("  Tabellerne selv og deres struktur bliver bevaret.")
        print("  users og badminton_clubs bliver ikke tømt.")

        typed = input(
            f'\nSkriv præcis "{CONFIRM_TEXT}" for at fortsætte: '
        ).strip()

        if typed != CONFIRM_TEXT:
            print("\nAfbrudt. Intet er slettet.")
            return

        print("\nStarter reset...")

        # Deaktiver constraints på ALLE dbo-tabeller, så vi kan tømme
        # child/parent-tabeller uden at være afhængige af delete-rækkefølge.
        for schema, table in tables:
            cursor.execute(
                f"ALTER TABLE {qident(schema)}.{qident(table)} "
                "NOCHECK CONSTRAINT ALL"
            )

        # Slet alle ikke-bevarede tabeller.
        for schema, table in delete_tables:
            full_name = f"{qident(schema)}.{qident(table)}"
            print(f"  DELETE {schema}.{table}")
            cursor.execute(f"DELETE FROM {full_name}")

            # Reseed kun tabeller, der faktisk har IDENTITY.
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM sys.identity_columns ic
                INNER JOIN sys.tables t
                    ON t.object_id = ic.object_id
                INNER JOIN sys.schemas s
                    ON s.schema_id = t.schema_id
                WHERE s.name = ? AND t.name = ?
                """,
                schema,
                table,
            )

            has_identity = cursor.fetchone()[0] > 0

            if has_identity:
                cursor.execute(
                    f"DBCC CHECKIDENT ('{schema}.{table}', RESEED, 0)"
                )

        # Genaktiver og valider constraints.
        for schema, table in tables:
            cursor.execute(
                f"ALTER TABLE {qident(schema)}.{qident(table)} "
                "WITH CHECK CHECK CONSTRAINT ALL"
            )

        conn.commit()

        print("\n" + "=" * 90)
        print("RESET FÆRDIG")
        print("=" * 90)

        print("\nBEVARET:")
        for schema, table in preserve:
            cursor.execute(
                f"SELECT COUNT(*) FROM {qident(schema)}.{qident(table)}"
            )
            count = cursor.fetchone()[0]
            print(f"  {schema}.{table}: {count} rækker")

        print("\nAlle øvrige dbo-tabeller er tømt.")

    except Exception:
        conn.rollback()
        print("\nFEJL: Reset blev rullet tilbage.")
        raise

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
