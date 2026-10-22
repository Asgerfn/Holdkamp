from database import get_connection


VIEW_SQL = r"""
CREATE OR ALTER VIEW dbo.v_department_players
AS

SELECT DISTINCT
    cp.club_id,
    cp.season_id,
    mapped.department,
    cp.badminton_id

FROM dbo.club_players cp

OUTER APPLY (
    SELECT TOP 1
        UPPER(LTRIM(RTRIM(COALESCE(pr.ranking_class, ''))))
            AS ranking_class
    FROM dbo.player_rankings pr
    WHERE
        pr.badminton_id = cp.badminton_id
        AND pr.club_id = cp.club_id
        AND pr.season_id = cp.season_id
    ORDER BY pr.id DESC
) latest

CROSS APPLY (
    SELECT CASE
        WHEN latest.ranking_class LIKE 'SEN+50%'
            OR latest.ranking_class LIKE 'VET%'
            THEN 'VET'
        WHEN latest.ranking_class LIKE 'U17%'
            OR latest.ranking_class LIKE 'U19%'
            OR latest.ranking_class LIKE 'SEN%'
            THEN 'SEN'
        WHEN latest.ranking_class LIKE 'MOT%'
            THEN 'MOT'
        WHEN latest.ranking_class LIKE 'U%'
            THEN 'U'
        ELSE NULL
    END AS department
) mapped

WHERE
    cp.is_active = 1
    AND mapped.department IS NOT NULL;
"""


def main():
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(VIEW_SQL)
        conn.commit()

        print("[OK] dbo.v_department_players er opdateret.")
        print("SEN = U17 + U19 + SEN")

        cursor.execute(
            """
            SELECT
                club_id,
                season_id,
                department,
                COUNT(*) AS player_count
            FROM dbo.v_department_players
            GROUP BY
                club_id,
                season_id,
                department
            ORDER BY
                club_id,
                season_id,
                department
            """
        )

        for row in cursor.fetchall():
            print(
                f"club={row.club_id} | season={row.season_id} | "
                f"{row.department}={row.player_count}"
            )

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
