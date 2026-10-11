import re
import sys



from database import get_connection



from badmintonplayer import (

    create_session,

    get_callback_context,

)



from fantasy_points import (

    recalculate_match_points,

)



from team_matches import (

    resolve_team_ids,

    get_team_matches,

)



from matches_data import (

    save_matches_to_azure,

)



from match_details import (

    get_saved_team_matches,

    fetch_match_details,

)





if hasattr(sys.stdout, "reconfigure"):

    sys.stdout.reconfigure(

        encoding="utf-8"

    )





# =========================================================

# HELPERS

# =========================================================



def normalize_text(value):



    if value is None:

        return ""



    return " ".join(

        str(value)

        .replace("\xa0", " ")

        .split()

    ).strip()





# =========================================================

# INCREMENTAL SYNC HELPERS

# =========================================================


def has_match_result(match):
    """
    True kun når kampoversigten indeholder et rigtigt
    holdresultat, fx. "8-5" eller "13 - 0".

    Tekst, placeholders og andre ikke-resultater skal ikke
    udløse hentning af kampdetaljer.
    """

    result = normalize_text(
        match.get("result")
    )

    return (
        re.search(
            r"\d+\s*-\s*\d+",
            result,
        )
        is not None
    )



def match_details_exist(
    club_match_id,
):
    """
    En kamp regnes som hentet, når der allerede findes
    mindst én delkamp i dbo.club_match_games.
    """

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT
                COUNT(*) AS game_count

            FROM dbo.club_match_games

            WHERE
                club_match_id = ?
            """,
            club_match_id,
        )

        row = cursor.fetchone()

        return (
            row is not None
            and int(row.game_count or 0) > 0
        )

    finally:

        cursor.close()
        conn.close()



def get_existing_match_results(
    club_id,
    season_id,
):
    """
    Snapshot af eksisterende resultater FØR den nye
    kampoversigt gemmes.

    Det gør det muligt at opdage rettelser til allerede
    spillede kampe og genhente deres detaljer.
    """

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT
                league_match_id,
                result

            FROM dbo.club_matches

            WHERE
                club_id = ?
                AND season_id = ?
            """,
            club_id,
            season_id,
        )

        rows = cursor.fetchall()

        return {
            row.league_match_id:
                normalize_text(
                    row.result
                )

            for row in rows
        }

    finally:

        cursor.close()
        conn.close()





# =========================================================

# GET ACTIVE TEAMS FOR CLUB

# =========================================================



def get_active_teams(

    club_id,

    season_id,

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

                team_name,

                league_name,

                league_group_id,

                age_group_id,

                region_id,

                league_group_team_id



            FROM dbo.club_dashboard_teams



            WHERE

                club_id = ?

                AND season_id = ?

                AND is_active = 1



            ORDER BY id

            """,

            club_id,

            season_id

        )



        rows = cursor.fetchall()



        return [

            {

                "id":

                    row.id,



                "club_id":

                    row.club_id,



                "season_id":

                    row.season_id,



                "team_name":

                    row.team_name,



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

            }



            for row in rows

        ]



    finally:



        cursor.close()

        conn.close()





# =========================================================

# SAVE RESOLVED TEAM IDS

# =========================================================



def save_resolved_team_ids(

    team_id,

    club_id,

    season_id,

    region_id,

    league_group_team_id,

):



    conn = get_connection()

    cursor = conn.cursor()



    try:



        cursor.execute(

            """

            UPDATE dbo.club_dashboard_teams



            SET

                region_id = ?,

                league_group_team_id = ?,

                updated_at =

                    SYSUTCDATETIME()



            WHERE

                id = ?

                AND club_id = ?

                AND season_id = ?

            """,



            region_id,

            league_group_team_id,

            team_id,

            club_id,

            season_id,

        )



        conn.commit()



    except Exception:



        conn.rollback()

        raise



    finally:



        cursor.close()

        conn.close()





# =========================================================

# SYNC ONE CLUB

# =========================================================



def sync_club_active_teams(

    club_id,

    season_id,

):



    print()

    print("=" * 100)

    print("SYNC ACTIVE TEAMS")

    print("=" * 100)



    print(

        "Club ID:",

        club_id

    )



    print(

        "Season:",

        season_id

    )





    teams = get_active_teams(

        club_id=club_id,

        season_id=season_id,

    )





    print(

        "Aktive hold:",

        len(teams)

    )





    if not teams:



        return {

            "active_teams": 0,

            "successful_teams": 0,

            "failed_teams": 0,

            "matches": 0,

            "detail_matches": 0,

            "games": 0,

            "skipped_no_result": 0,

            "skipped_existing_details": 0,

            "refreshed_changed_result": 0,

            "failed_matches": 0,

        }





    # =====================================================

    # ONE BADMINTONPLAYER SESSION

    # =====================================================



    session = create_session()



    callback_context = (

        get_callback_context(

            session

        )

    )





    all_matches = []



    successful_teams = 0



    failed_teams = []



    # =====================================================
    # EXISTING RESULT SNAPSHOT
    #
    # Hentes før kampoversigten gemmes igen, så vi kan
    # opdage ændrede resultater.
    # =====================================================

    existing_results = (
        get_existing_match_results(
            club_id=club_id,
            season_id=season_id,
        )
    )






    # =====================================================

    # FETCH TEAM MATCH LISTS

    # =====================================================



    for index, team in enumerate(

        teams,

        start=1

    ):



        print()

        print("-" * 100)



        print(

            f"[{index}/{len(teams)}] "

            f"{team['team_name']} - "

            f"{team['league_name']}"

        )





        try:



            # =============================================

            # AGE GROUP REQUIRED

            # =============================================



            if team["age_group_id"] is None:



                raise RuntimeError(

                    "Holdet mangler age_group_id."

                )





            # =============================================

            # RESOLVE TEAM IDS

            # =============================================



            ids = resolve_team_ids(

                session=session,



                callback_context=

                    callback_context,



                club_id=

                    club_id,



                season_id=

                    season_id,



                league_group_id=

                    team[

                        "league_group_id"

                    ],



                age_group_id=

                    team[

                        "age_group_id"

                    ],



                team_name=

                    team[

                        "team_name"

                    ],

            )





            region_id = (

                ids[

                    "region_id"

                ]

            )





            league_group_team_id = (

                ids[

                    "league_group_team_id"

                ]

            )





            print(

                "Region ID:",

                region_id

            )



            print(

                "League Group Team ID:",

                league_group_team_id

            )





            # =============================================

            # SAVE RESOLVED TEAM IDS

            # =============================================



            save_resolved_team_ids(

                team_id=

                    team["id"],



                club_id=

                    club_id,



                season_id=

                    season_id,



                region_id=

                    region_id,



                league_group_team_id=

                    league_group_team_id,

            )





            # =============================================

            # GET TEAM MATCHES

            # =============================================



            matches = get_team_matches(

                session=session,



                callback_context=

                    callback_context,



                club_id=

                    club_id,



                season_id=

                    season_id,



                league_group_id=

                    team[

                        "league_group_id"

                    ],



                age_group_id=

                    team[

                        "age_group_id"

                    ],



                region_id=

                    region_id,



                league_group_team_id=

                    league_group_team_id,



                club_team_name=

                    team[

                        "team_name"

                    ],



                league_name=

                    team[

                        "league_name"

                    ],

            )





            print(

                "Holdkampe fundet:",

                len(matches)

            )





            all_matches.extend(

                matches

            )





            successful_teams += 1





        except Exception as e:



            print()

            print(

                "FEJL VED HOLD:"

            )



            print(

                team["team_name"],

                "-",

                team["league_name"]

            )



            print(e)





            failed_teams.append(

                {

                    "team_name":

                        team[

                            "team_name"

                        ],



                    "league_name":

                        team[

                            "league_name"

                        ],



                    "error":

                        str(e),

                }

            )





    # =====================================================

    # REMOVE DUPLICATES

    # =====================================================



    unique_matches = {}





    for match in all_matches:



        key = (

            match["club_id"],

            match["season_id"],

            match["league_match_id"],

        )



        unique_matches[

            key

        ] = match





    all_matches = list(

        unique_matches.values()

    )





    print()



    print(

        "Unikke holdkampe:",

        len(all_matches)

    )





    # =====================================================
    # DETECT CHANGED RESULTS
    #
    # Sammenlignes med snapshot fra før den nye oversigt
    # bliver gemt.
    # =====================================================

    changed_result_match_ids = set()


    for match in all_matches:

        league_match_id = (
            match["league_match_id"]
        )

        old_result = normalize_text(
            existing_results.get(
                league_match_id
            )
        )

        new_result = normalize_text(
            match.get(
                "result"
            )
        )


        if (
            old_result
            and new_result
            and old_result != new_result
        ):

            changed_result_match_ids.add(
                league_match_id
            )

            print(
                "Ændret resultat fundet:",
                league_match_id,
                f"{old_result} -> {new_result}"
            )



    # =====================================================

    # SAVE HOLD MATCHES

    # =====================================================



    if all_matches:



        print()



        print(

            f"Gemmer {len(all_matches)} "

            f"holdkampe i Azure..."

        )



        save_matches_to_azure(

            all_matches

        )





    # =====================================================

    # FETCH DETAILS + CALCULATE POINTS

    # =====================================================



    detail_matches = 0



    total_games = 0



    skipped_no_result = 0



    skipped_existing_details = 0



    refreshed_changed_result = 0





    failed_matches = []



    seen_matches = set()





    for team in teams:



        try:



            saved_matches = (

                get_saved_team_matches(

                    club_id=

                        club_id,



                    season_id=

                        season_id,



                    league_group_id=

                        team[

                            "league_group_id"

                        ],

                )

            )



        except Exception as e:



            print(

                "Kunne ikke hente gemte kampe for",

                team["team_name"],

                ":",

                e

            )



            continue





        for match in saved_matches:



            # ---------------------------------------------

            # Samme league_group_id kan i særlige tilfælde

            # bruges af mere end ét hold.

            #

            # Derfor filtrerer vi på holdnavn.

            # ---------------------------------------------



            if (

                normalize_text(

                    match[

                        "club_team_name"

                    ]

                ).casefold()

                !=

                normalize_text(

                    team[

                        "team_name"

                    ]

                ).casefold()

            ):



                continue





            league_match_id = (

                match[

                    "league_match_id"

                ]

            )





            if league_match_id in seen_matches:



                continue





            seen_matches.add(

                league_match_id

            )





            # =============================================
            # SKIP 1: NO RESULT
            #
            # Uspillede/fremtidige kampe skal aldrig åbnes
            # på detaljesiden.
            # =============================================

            if not has_match_result(
                match
            ):

                skipped_no_result += 1

                print(
                    "SKIP - intet resultat:",
                    league_match_id
                )

                continue



            # =============================================
            # SKIP 2: DETAILS ALREADY EXIST
            #
            # Hvis kampdetaljer allerede findes og
            # oversigtsresultatet er uændret, springes
            # kampen helt over.
            # =============================================

            details_already_exist = (
                match_details_exist(
                    club_match_id=
                        match["id"]
                )
            )

            result_changed = (
                league_match_id
                in changed_result_match_ids
            )


            if (
                details_already_exist
                and not result_changed
            ):

                skipped_existing_details += 1

                print(
                    "SKIP - detaljer findes allerede:",
                    league_match_id
                )

                continue



            # =============================================
            # REFRESH CHANGED RESULT
            # =============================================

            if result_changed:

                refreshed_changed_result += 1

                print(
                    "REFRESH - resultat ændret:",
                    league_match_id
                )



            try:



                print()



                print(

                    "Henter detaljer for kamp:",

                    league_match_id

                )





                # =========================================

                # FETCH + SAVE MATCH DETAILS

                # =========================================



                details = (

                    fetch_match_details(

                        session=

                            session,



                        callback_context=

                            callback_context,



                        match=

                            match,

                    )

                )





                detail_matches += 1





                game_count = len(

                    details.get(

                        "games",

                        []

                    )

                )





                total_games += (

                    game_count

                )





                # =========================================

                # FANTASY POINTS

                # =========================================



                if game_count > 0:



                    point_result = (

                        recalculate_match_points(

                            club_match_id=

                                match[

                                    "id"

                                ]

                        )

                    )





                    print(

                        "Fantasy point:",

                        point_result[

                            "events"

                        ],

                        "events"

                    )





            except Exception as e:



                print()



                print(

                    "FEJL VED KAMP",

                    league_match_id,

                    ":",

                    e

                )





                failed_matches.append(

                    {

                        "league_match_id":

                            league_match_id,



                        "error":

                            str(e),

                    }

                )





    # =====================================================

    # SUMMARY

    # =====================================================



    result = {



        "active_teams":

            len(teams),



        "successful_teams":

            successful_teams,



        "failed_teams":

            len(

                failed_teams

            ),



        "matches":

            len(

                all_matches

            ),



        "detail_matches":

            detail_matches,



        "games":

            total_games,



        "skipped_no_result":

            skipped_no_result,



        "skipped_existing_details":

            skipped_existing_details,



        "refreshed_changed_result":

            refreshed_changed_result,



        "failed_matches":

            len(

                failed_matches

            ),

    }





    print()

    print("=" * 100)

    print("SYNC SUMMARY")

    print("=" * 100)





    print(

        "Aktive hold:",

        result[

            "active_teams"

        ]

    )





    print(

        "Hold synkroniseret:",

        result[

            "successful_teams"

        ]

    )





    print(

        "Hold med fejl:",

        result[

            "failed_teams"

        ]

    )





    print(

        "Holdkampe:",

        result[

            "matches"

        ]

    )





    print(

        "Kampdetaljer tjekket:",

        result[

            "detail_matches"

        ]

    )





    print(

        "Delkampe fundet:",

        result[

            "games"

        ]

    )





    print(

        "Uspillede kampe sprunget over:",

        result[

            "skipped_no_result"

        ]

    )





    print(

        "Eksisterende detaljer sprunget over:",

        result[

            "skipped_existing_details"

        ]

    )





    print(

        "Kampe genhentet pga. ændret resultat:",

        result[

            "refreshed_changed_result"

        ]

    )





    print(

        "Kampe med fejl:",

        result[

            "failed_matches"

        ]

    )





    return result





# =========================================================

# SYNC ALL CLUBS

# =========================================================



def sync_all_active_teams(

    season_id,

):



    conn = get_connection()

    cursor = conn.cursor()





    try:



        cursor.execute(

            """

            SELECT DISTINCT

                club_id



            FROM dbo.club_dashboard_teams



            WHERE

                season_id = ?

                AND is_active = 1



            ORDER BY

                club_id

            """,



            season_id

        )





        club_ids = [

            row.club_id



            for row

            in cursor.fetchall()

        ]





    finally:



        cursor.close()

        conn.close()





    results = []





    for club_id in club_ids:



        try:



            result = (

                sync_club_active_teams(

                    club_id=

                        club_id,



                    season_id=

                        season_id,

                )

            )





            results.append(

                {

                    "club_id":

                        club_id,



                    "success":

                        True,



                    "result":

                        result,

                }

            )





        except Exception as e:



            print()



            print(

                "FEJL VED CLUB",

                club_id,

                ":",

                e

            )





            results.append(

                {

                    "club_id":

                        club_id,



                    "success":

                        False,



                    "error":

                        str(e),

                }

            )





    return results