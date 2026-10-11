import re
import sys

import requests
from bs4 import BeautifulSoup


# =========================================================
# UTF-8 WINDOWS
# =========================================================

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8",
        errors="replace"
    )


# =========================================================
# URLS
# =========================================================

PAGE_URL = (
    "https://www.badmintonplayer.dk/"
    "DBF/HoldTurnering/Stilling/"
)

API_URL = (
    "https://www.badmintonplayer.dk/"
    "SportsResults/Components/"
    "WebService1.asmx/GetLeagueStanding"
)


# =========================================================
# SESSION
# =========================================================

def create_session():

    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/154.0.0.0 Safari/537.36"
        ),
        "Accept-Language":
            "da-DK,da;q=0.9,en;q=0.8",
    })

    return session


# =========================================================
# CALLBACK CONTEXT
# =========================================================

def get_callback_context(session):

    response = session.get(
        PAGE_URL,
        timeout=30
    )

    response.raise_for_status()

    match = re.search(
        r"var\s+SR_CallbackContext\s*=\s*['\"]([^'\"]+)['\"]",
        response.text,
        re.IGNORECASE
    )

    if not match:

        raise RuntimeError(
            "Kunne ikke finde SR_CallbackContext "
            "på BadmintonPlayer."
        )

    return match.group(1)


# =========================================================
# SHOWSTANDING ARGS
# =========================================================

def extract_showstanding_args(onclick):

    if not onclick:
        return None

    match = re.search(
        r"ShowStanding\((.*?)\)",
        onclick,
        re.DOTALL
    )

    if not match:
        return None

    return re.findall(
        r"'([^']*)'",
        match.group(1)
    )


# =========================================================
# MAP BADMINTONPLAYER SECTION
# =========================================================

def map_department(section):

    if not section:
        return None, None

    section = (
        section
        .strip()
        .upper()
    )


    # =====================================================
    # UNGDOM
    #
    # U9
    # U11
    # U13
    # U15
    # U17/U19
    # osv.
    # =====================================================

    if re.fullmatch(
        r"U\d+(?:/U\d+)?",
        section
    ):

        return (
            "U",
            section
        )


    # =====================================================
    # SENIOR
    # =====================================================

    if section == "SEN":

        return (
            "SEN",
            None
        )


    # =====================================================
    # MOTIONIST
    # =====================================================

    if section == "MOT":

        return (
            "MOT",
            None
        )


    # =====================================================
    # VETERAN
    #
    # BadmintonPlayer bruger bl.a. SEN+50
    # =====================================================

    if section in {
        "VET",
        "SEN+50"
    }:

        return (
            "VET",
            None
        )


    return (
        None,
        None
    )


# =========================================================
# PARSE HTML FROM BADMINTONPLAYER
# =========================================================

def parse_club_teams(
    html_content,
    club_id,
    season_id
):

    soup = BeautifulSoup(
        html_content,
        "html.parser"
    )


    teams = []

    seen = set()

    current_section = None


    # =====================================================
    # ALL TABLE ROWS
    # =====================================================

    rows = soup.find_all(
        "tr"
    )


    for row in rows:

        classes = row.get(
            "class",
            []
        )


        # =================================================
        # SECTION HEADER
        #
        # Fx:
        #
        # U11
        # U13
        # U15
        # U17/U19
        # SEN
        # SEN+50
        # MOT
        # =================================================

        if "agegrouprow" in classes:

            heading = row.find(
                "h3"
            )

            if heading:

                current_section = (
                    heading.get_text(
                        " ",
                        strip=True
                    )
                )

            continue


        # =================================================
        # ONLY TEAM ROWS
        # =================================================

        if "grouprow" not in classes:

            continue


        if not current_section:

            continue


        # =================================================
        # DEPARTMENT
        # =================================================

        (
            department,
            sub_department
        ) = map_department(
            current_section
        )


        # Ukendt sektion
        if not department:

            continue


        # =================================================
        # TD CELLS
        # =================================================

        cells = row.find_all(
            "td"
        )


        if len(cells) < 2:

            continue


        # =================================================
        # TEAM NAME
        #
        # Fx:
        #
        # Herlev/Hjorten
        # Herlev/Hjorten 2
        # Herlev/Hjorten 7
        # =================================================

        team_name = (
            cells[0]
            .get_text(
                " ",
                strip=True
            )
        )


        if not team_name:

            continue


        # =================================================
        # LEAGUE LINK
        # =================================================

        link = cells[1].find(
            "a",
            onclick=True
        )


        if not link:

            continue


        league_name = (
            link
            .get_text(
                " ",
                strip=True
            )
        )


        onclick = link.get(
            "onclick",
            ""
        )


        # =================================================
        # SHOWSTANDING ARGUMENTS
        # =================================================

        args = extract_showstanding_args(
            onclick
        )


        if not args:

            continue


        if len(args) < 8:

            continue


        # =================================================
        # SHOWSTANDING STRUCTURE
        #
        # args[0] = subPage
        # args[1] = seasonID
        # args[2] = leagueGroupID
        # args[3] = leagueGroupTeamID
        # ...
        # args[7] = clubID
        # =================================================

        found_season_id = (
            args[1]
        )

        league_group_id = (
            args[2]
        )

        league_group_team_id = (
            args[3]
        )

        found_club_id = (
            args[7]
        )


        # =================================================
        # CORRECT CLUB
        # =================================================

        if found_club_id != str(
            club_id
        ):

            continue


        # =================================================
        # CORRECT SEASON
        # =================================================

        if found_season_id != str(
            season_id
        ):

            continue


        # =================================================
        # GROUP ID REQUIRED
        # =================================================

        if not league_group_id:

            continue


        # =================================================
        # DUPLICATE PROTECTION
        #
        # VIGTIGT:
        #
        # league_group_id er IKKE alene unik for et
        # klubhold.
        #
        # Fx kan:
        #
        # Herlev/Hjorten 1
        # Herlev/Hjorten 7
        #
        # begge have league_group_id = 18937.
        #
        # Derfor inkluderer vi team_name.
        # =================================================

        unique_key = (
            str(club_id),
            str(season_id),
            current_section,
            team_name,
            league_group_id,
            league_name,
        )


        if unique_key in seen:

            continue


        seen.add(
            unique_key
        )


        # =================================================
        # SAVE TEAM
        # =================================================

        teams.append({

            "department":
                department,

            "sub_department":
                sub_department,

            "source_section":
                current_section,

            "team_name":
                team_name,

            "league_name":
                league_name,

            "season_id":
                int(season_id),

            "league_group_id":
                league_group_id,

            "league_group_team_id":
                league_group_team_id,

            "club_id":
                int(club_id),

        })


    # =====================================================
    # SORTING
    # =====================================================

    department_order = {

        "U": 1,

        "SEN": 2,

        "MOT": 3,

        "VET": 4,

    }


    youth_order = {

        "U9": 1,

        "U11": 2,

        "U13": 3,

        "U15": 4,

        "U17/U19": 5,

    }


    def sort_key(team):

        return (

            department_order.get(
                team["department"],
                99
            ),

            youth_order.get(
                team["sub_department"],
                99
            ),

            team["team_name"],

            team["league_name"],

        )


    teams.sort(
        key=sort_key
    )


    return teams


# =========================================================
# MAIN FUNCTION
# =========================================================

def get_club_teams(
    club_id,
    season_id=2026,
    headless=None,
):

    """
    Henter alle hold/rækker for en klub direkte fra
    BadmintonPlayer via deres GetLeagueStanding endpoint.

    Selenium bruges IKKE.

    headless-parameteren beholdes midlertidigt,
    så eksisterende app.py fortsat kan kalde:

        get_club_teams(
            club_id=...,
            season_id=...,
            headless=True
        )

    uden at app.py fejler.
    """


    # =====================================================
    # NORMALIZE INPUT
    # =====================================================

    club_id = int(
        club_id
    )

    season_id = int(
        season_id
    )


    # =====================================================
    # HTTP SESSION
    # =====================================================

    session = (
        create_session()
    )


    # =====================================================
    # CALLBACK CONTEXT
    # =====================================================

    callback_context = (
        get_callback_context(
            session
        )
    )


    # =====================================================
    # PAYLOAD
    # =====================================================

    payload = {

        "ageGroupID":
            None,

        "callbackcontextkey":
            callback_context,

        "clubID":
            str(club_id),

        "leagueGroupID":
            None,

        "leagueGroupTeamID":
            None,

        "leagueMatchID":
            None,

        "playerID":
            None,

        "regionID":
            None,

        "seasonID":
            str(season_id),

        "subPage":
            6,

    }


    # =====================================================
    # HEADERS
    # =====================================================

    headers = {

        "Accept":
            "application/json, "
            "text/javascript, "
            "*/*; q=0.01",

        "Content-Type":
            "application/json; charset=UTF-8",

        "Origin":
            "https://www.badmintonplayer.dk",

        "Referer":
            PAGE_URL,

        "X-Requested-With":
            "XMLHttpRequest",

    }


    # =====================================================
    # REQUEST
    # =====================================================

    response = session.post(
        API_URL,
        headers=headers,
        json=payload,
        timeout=30
    )


    response.raise_for_status()


    # =====================================================
    # JSON
    # =====================================================

    data = (
        response.json()
    )


    if "d" not in data:

        raise RuntimeError(
            "BadmintonPlayer-svaret "
            "indeholder ikke feltet 'd'."
        )


    result = (
        data["d"]
    )


    if not isinstance(
        result,
        dict
    ):

        raise RuntimeError(
            "BadmintonPlayer returnerede "
            "et uventet format i data['d']."
        )


    # =====================================================
    # HTML
    # =====================================================

    html_content = (
        result.get(
            "html"
        )
    )


    if not html_content:

        raise RuntimeError(
            "BadmintonPlayer returnerede "
            "ingen hold-HTML."
        )


    # =====================================================
    # PARSE TEAMS
    # =====================================================

    teams = parse_club_teams(

        html_content=
            html_content,

        club_id=
            club_id,

        season_id=
            season_id,

    )


    return teams


# =========================================================
# LOCAL TEST
# =========================================================

if __name__ == "__main__":

    club_id = int(
        input(
            "Indtast klub-ID: "
        )
    )


    teams = get_club_teams(

        club_id=
            club_id,

        season_id=
            2026,

    )


    print()

    print(
        f"Fundet "
        f"{len(teams)} "
        f"hold/rækker"
    )


    current_department = None

    current_sub_department = None


    for team in teams:


        # =================================================
        # DEPARTMENT HEADER
        # =================================================

        if (
            team["department"]
            != current_department
        ):

            current_department = (
                team["department"]
            )

            current_sub_department = None


            print()

            print(
                "=" * 100
            )

            print(
                current_department
            )

            print(
                "=" * 100
            )


        # =================================================
        # YOUTH SUB DEPARTMENT
        # =================================================

        if (
            team["department"] == "U"
            and
            team["sub_department"]
            != current_sub_department
        ):

            current_sub_department = (
                team["sub_department"]
            )


            print()

            print(
                f"--- "
                f"{current_sub_department}"
                f" ---"
            )


        # =================================================
        # TEAM
        # =================================================

        print()

        print(
            "Hold:      ",
            team["team_name"]
        )

        print(
            "Afdeling:  ",
            team["department"]
        )

        print(
            "Underafd.: ",
            team["sub_department"]
        )

        print(
            "Sektion:   ",
            team["source_section"]
        )

        print(
            "Række:     ",
            team["league_name"]
        )

        print(
            "Group ID:  ",
            team["league_group_id"]
        )

        print(
            "Team ID:   ",
            team[
                "league_group_team_id"
            ]
        )

        print(
            "Club ID:   ",
            team["club_id"]
        )


    # =====================================================
    # SUMMARY
    # =====================================================

    print()

    print(
        "=" * 100
    )

    print(
        "SUMMARY"
    )

    print(
        "=" * 100
    )


    for department in [
        "U",
        "SEN",
        "MOT",
        "VET",
    ]:

        count = sum(

            1

            for team in teams

            if (
                team["department"]
                == department
            )

        )


        print(
            f"{department:<5}: "
            f"{count}"
        )


    print()

    print(
        f"TOTAL: "
        f"{len(teams)}"
    )