import webbrowser

from database import get_connection


BASE_URL = (
    "https://www.badmintonplayer.dk/"
    "DBF/HoldTurnering/Stilling/"
)


def get_match_from_database(
    league_match_id,
    club_id=1148,
    season_id=2026,
):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT

                id,
                club_id,
                season_id,

                club_team_name,
                league_name,

                league_group_id,
                age_group_id,
                region_id,
                league_group_team_id,

                league_match_id,

                match_time,
                home_team,
                away_team,
                result,
                points

            FROM dbo.club_matches

            WHERE
                club_id = ?
                AND season_id = ?
                AND league_match_id = ?
            """,

            club_id,
            season_id,
            league_match_id
        )

        row = cursor.fetchone()

        if row is None:

            return None


        return {

            "id":
                row.id,

            "club_id":
                row.club_id,

            "season_id":
                row.season_id,

            "club_team_name":
                row.club_team_name,

            "league_name":
                row.league_name,

            "league_group_id":
                row.league_group_id,

            "age_group_id":
                row.age_group_id,

            "region_id":
                row.region_id,

            "league_group_team_id":
                row.league_group_team_id,

            "league_match_id":
                row.league_match_id,

            "match_time":
                row.match_time,

            "home_team":
                row.home_team,

            "away_team":
                row.away_team,

            "result":
                row.result,

            "points":
                row.points,
        }


    finally:

        cursor.close()
        conn.close()


def build_match_url(match):

    """
    BadmintonPlayer:

    #5,
    seasonID,
    leagueGroupID,
    ageGroupID,
    regionID,
    leagueGroupTeamID,
    leagueMatchID,
    clubID,
    playerID

    Ved en specifik kamp er leagueGroupTeamID tom.
    """

    params = [

        "5",

        str(
            match["season_id"]
        ),

        str(
            match["league_group_id"]
        ),

        str(
            match["age_group_id"]
        ),

        str(
            match["region_id"]
        ),

        "",

        str(
            match["league_match_id"]
        ),

        str(
            match["club_id"]
        ),

        ""
    ]


    return (
        BASE_URL
        + "#"
        + ",".join(params)
    )


def main():

    # =====================================================
    # TEST MATCH
    # =====================================================

    league_match_id = 507496


    match = get_match_from_database(
        league_match_id=league_match_id
    )


    if match is None:

        print(
            f"Kamp {league_match_id} "
            f"blev ikke fundet i Azure."
        )

        return


    # =====================================================
    # PRINT DATABASE DATA
    # =====================================================

    print()
    print("=" * 80)
    print("KAMP FRA AZURE")
    print("=" * 80)

    print(
        "League match ID:",
        match["league_match_id"]
    )

    print(
        "Hold:",
        match["club_team_name"]
    )

    print(
        "Række:",
        match["league_name"]
    )

    print(
        "League group ID:",
        match["league_group_id"]
    )

    print(
        "Age group ID:",
        match["age_group_id"]
    )

    print(
        "Region ID:",
        match["region_id"]
    )

    print(
        "League group team ID:",
        match["league_group_team_id"]
    )

    print()

    print(
        "Kamp:",
        match["home_team"],
        "-",
        match["away_team"]
    )

    print(
        "Tid:",
        match["match_time"]
    )

    print(
        "Resultat:",
        match["result"]
    )


    # =====================================================
    # BUILD BADMINTONPLAYER URL
    # =====================================================

    url = build_match_url(
        match
    )


    print()
    print("=" * 80)
    print("BADMINTONPLAYER LINK")
    print("=" * 80)

    print(url)


    # =====================================================
    # OPEN IN DEFAULT BROWSER
    # =====================================================

    print()
    print(
        "Åbner kampen i browseren..."
    )

    webbrowser.open(
        url
    )


if __name__ == "__main__":

    main()