import re
from datetime import datetime

from bs4 import BeautifulSoup

from badmintonplayer import (
    create_session,
    get_callback_context,
    extract_showstanding_args,
    PAGE_URL,
    API_URL,
)

from matches_data import save_matches_to_azure


# =========================================================
# BADMINTONPLAYER REQUEST
# =========================================================

def call_badmintonplayer(
    session,
    callback_context,
    sub_page,
    season_id,
    club_id,
    league_group_id=None,
    age_group_id=None,
    region_id=None,
    league_group_team_id=None,
    league_match_id=None,
    player_id=None,
):
    """
    Kalder BadmintonPlayers interne webservice og returnerer
    HTML-indholdet fra svaret.
    """

    payload = {
        "ageGroupID": (
            str(age_group_id)
            if age_group_id is not None
            else None
        ),

        "callbackcontextkey": callback_context,

        "clubID": (
            str(club_id)
            if club_id is not None
            else None
        ),

        "leagueGroupID": (
            str(league_group_id)
            if league_group_id is not None
            else None
        ),

        "leagueGroupTeamID": (
            str(league_group_team_id)
            if league_group_team_id is not None
            else None
        ),

        "leagueMatchID": (
            str(league_match_id)
            if league_match_id is not None
            else None
        ),

        "playerID": (
            str(player_id)
            if player_id is not None
            else None
        ),

        "regionID": (
            str(region_id)
            if region_id is not None
            else None
        ),

        "seasonID": str(season_id),

        "subPage": int(sub_page),
    }

    headers = {
        "Accept":
            "application/json, text/javascript, */*; q=0.01",

        "Content-Type":
            "application/json; charset=UTF-8",

        "Origin":
            "https://www.badmintonplayer.dk",

        "Referer":
            PAGE_URL,

        "X-Requested-With":
            "XMLHttpRequest",
    }

    response = session.post(
        API_URL,
        headers=headers,
        json=payload,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    if "d" not in data:
        raise RuntimeError(
            "BadmintonPlayer-svaret mangler feltet 'd'."
        )

    result = data["d"]

    if not isinstance(result, dict):
        raise RuntimeError(
            "BadmintonPlayer returnerede et uventet format."
        )

    html_content = result.get("html")

    if not html_content:
        raise RuntimeError(
            "BadmintonPlayer returnerede ingen HTML."
        )

    return html_content


# =========================================================
# TEXT HELPERS
# =========================================================

def normalize_text(value):
    """
    Rydder whitespace og non-breaking spaces.
    """

    if not value:
        return ""

    value = str(value).replace("\xa0", " ")

    return " ".join(
        value.split()
    ).strip()


def clean_optional(value):
    """
    Gør tomme værdier / bindestreger til None.
    """

    value = normalize_text(value)

    if value in {
        "",
        "-",
        "–",
        "—",
    }:
        return None

    return value


# =========================================================
# FIND REGION + LEAGUE GROUP TEAM ID
# =========================================================

def resolve_team_ids(
    session,
    callback_context,
    club_id,
    season_id,
    league_group_id,
    age_group_id,
    team_name,
):
    """
    Henter rækken/puljen via subPage = 2
    og finder det konkrete hold.

    Returnerer fx:

    {
        "region_id": 1,
        "league_group_team_id": 121898
    }
    """

    html_content = call_badmintonplayer(
        session=session,
        callback_context=callback_context,

        sub_page=2,

        season_id=season_id,
        club_id=club_id,

        league_group_id=league_group_id,
        age_group_id=age_group_id,
    )

    soup = BeautifulSoup(
        html_content,
        "html.parser"
    )

    wanted_team = normalize_text(
        team_name
    ).lower()

    candidates = []

    # =====================================================
    # FIND LINKS TO SUBPAGE 3
    # =====================================================

    for link in soup.find_all(
        "a",
        onclick=True
    ):
        onclick = link.get(
            "onclick",
            ""
        )

        args = extract_showstanding_args(
            onclick
        )

        if not args or len(args) < 9:
            continue

        # subPage 3 = holdets kampe
        if args[0] != "3":
            continue

        # Validate de felter vi allerede kender
        if args[1] != str(season_id):
            continue

        if args[2] != str(league_group_id):
            continue

        if args[3] != str(age_group_id):
            continue

        if args[7] != str(club_id):
            continue

        region_id = args[4]
        league_group_team_id = args[5]

        if not region_id:
            continue

        if not league_group_team_id:
            continue

        row = link.find_parent("tr")

        if row:
            row_text = normalize_text(
                row.get_text(
                    " ",
                    strip=True
                )
            )
        else:
            row_text = normalize_text(
                link.get_text(
                    " ",
                    strip=True
                )
            )

        candidate = {
            "row_text":
                row_text,

            "region_id":
                int(region_id),

            "league_group_team_id":
                int(league_group_team_id),
        }

        candidates.append(
            candidate
        )

        row_text_lower = (
            row_text.lower()
        )

        # Første forsøg:
        # exact / prefix match
        if (
            row_text_lower == wanted_team
            or row_text_lower.startswith(
                wanted_team + " "
            )
        ):
            return {
                "region_id":
                    int(region_id),

                "league_group_team_id":
                    int(league_group_team_id),
            }

    # =====================================================
    # SECOND ATTEMPT
    # =====================================================

    matches = [
        candidate
        for candidate in candidates
        if wanted_team
        in candidate["row_text"].lower()
    ]

    if len(matches) == 1:
        return {
            "region_id":
                matches[0]["region_id"],

            "league_group_team_id":
                matches[0]["league_group_team_id"],
        }

    # =====================================================
    # DEBUG
    # =====================================================

    print()
    print("Kunne ikke finde holdet automatisk.")
    print()
    print("Mulige hold i rækken:")

    for candidate in candidates:
        print(
            "  ",
            candidate["row_text"],
            "| region:",
            candidate["region_id"],
            "| team:",
            candidate["league_group_team_id"],
        )

    raise RuntimeError(
        f"Kunne ikke finde '{team_name}' "
        f"i league_group_id {league_group_id}."
    )


# =========================================================
# MATCH TIME PARSER
# =========================================================

def parse_match_time(text):
    """
    Håndterer fx:

    lø 05-09-2026 13:30
    05-09-2026 13:30
    05/09/2026 13:30
    05.09.2026 13:30

    samt forskellige unicode-bindestreger.
    """

    if not text:
        return None

    text = str(text)

    # Normalize unicode
    text = (
        text
        .replace("\u2010", "-")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\xa0", " ")
    )

    text = " ".join(
        text.split()
    )

    match = re.search(
        r"(\d{1,2})"
        r"\s*[-./]\s*"
        r"(\d{1,2})"
        r"\s*[-./]\s*"
        r"(\d{4})"
        r"\s+"
        r"(\d{1,2})"
        r"[:.]"
        r"(\d{2})",
        text
    )

    if not match:
        return None

    day = int(
        match.group(1)
    )

    month = int(
        match.group(2)
    )

    year = int(
        match.group(3)
    )

    hour = int(
        match.group(4)
    )

    minute = int(
        match.group(5)
    )

    return datetime(
        year,
        month,
        day,
        hour,
        minute
    )


# =========================================================
# GET TEAM MATCHES
# =========================================================

def get_team_matches(
    session,
    callback_context,
    club_id,
    season_id,
    league_group_id,
    age_group_id,
    region_id,
    league_group_team_id,
    club_team_name=None,
    league_name=None,
):
    """
    Henter kampoversigten via subPage = 3.
    """

    html_content = call_badmintonplayer(
        session=session,
        callback_context=callback_context,

        sub_page=3,

        season_id=season_id,
        club_id=club_id,

        league_group_id=league_group_id,
        age_group_id=age_group_id,
        region_id=region_id,

        league_group_team_id=
            league_group_team_id,
    )

    soup = BeautifulSoup(
        html_content,
        "html.parser"
    )

    matches = []

    seen_match_ids = set()

    # =====================================================
    # LOOP TABLE ROWS
    # =====================================================

    for row in soup.find_all("tr"):

        cells = row.find_all("td")

        # Vi forventer:
        #
        # 0 Tid
        # 1 #
        # 2 Hjemmehold
        # 3 Udehold
        # 4 Arrangør
        # 5 Spillested
        # 6 Resultat
        # 7 Point

        if len(cells) < 8:
            continue

        # =================================================
        # FIND LINK TO SUBPAGE 5
        # =================================================

        match_link = None
        match_args = None

        for link in row.find_all(
            "a",
            onclick=True
        ):
            args = extract_showstanding_args(
                link.get(
                    "onclick",
                    ""
                )
            )

            if not args or len(args) < 9:
                continue

            # subPage 5 = konkret kamp
            if args[0] != "5":
                continue

            # leagueMatchID = args[6]
            if not args[6]:
                continue

            match_link = link
            match_args = args

            break

        if not match_link:
            continue

        # =================================================
        # MATCH ID
        # =================================================

        league_match_id = int(
            match_args[6]
        )

        if league_match_id in seen_match_ids:
            continue

        seen_match_ids.add(
            league_match_id
        )

        # =================================================
        # TIME
        # =================================================

        time_text = cells[0].get_text(
            " ",
            strip=True
        )

        print(
            "RAW TIME:",
            repr(time_text)
        )

        match_time = parse_match_time(
            time_text
        )

        # =================================================
        # OTHER VALUES
        # =================================================

        home_team = normalize_text(
            cells[2].get_text(
                " ",
                strip=True
            )
        )

        away_team = normalize_text(
            cells[3].get_text(
                " ",
                strip=True
            )
        )

        organizer = normalize_text(
            cells[4].get_text(
                " ",
                strip=True
            )
        )

        venue = normalize_text(
            cells[5].get_text(
                " ",
                strip=True
            )
        )

        result = clean_optional(
            cells[6].get_text(
                " ",
                strip=True
            )
        )

        points = clean_optional(
            cells[7].get_text(
                " ",
                strip=True
            )
        )

        # =================================================
        # BUILD MATCH OBJECT
        # =================================================

        matches.append({

            "club_id":
                int(club_id),

            "season_id":
                int(season_id),

            "league_group_id":
                int(league_group_id),

            "age_group_id":
                (
                    int(age_group_id)
                    if age_group_id is not None
                    else None
                ),

            "region_id":
                (
                    int(region_id)
                    if region_id is not None
                    else None
                ),

            "league_group_team_id":
                (
                    int(league_group_team_id)
                    if league_group_team_id is not None
                    else None
                ),

            "league_match_id":
                league_match_id,

            "club_team_name":
                club_team_name,

            "league_name":
                league_name,

            "match_time":
                match_time,

            "home_team":
                home_team,

            "away_team":
                away_team,

            "organizer":
                organizer,

            "venue":
                venue,

            "result":
                result,

            "points":
                points,
        })

    matches.sort(
        key=lambda item: (
            item["match_time"]
            or datetime.max
        )
    )

    return matches


# =========================================================
# FULL PIPELINE
# =========================================================

def fetch_and_save_team_matches(
    club_id,
    season_id,
    league_group_id,
    age_group_id,
    team_name,
    league_name=None,
):
    """
    Hele flowet:

    1. Opret session
    2. Find callback context
    3. Find region_id
    4. Find league_group_team_id
    5. Hent kampe
    6. Parse kamp-ID'er
    7. Gem i Azure
    """

    print()
    print("=" * 90)
    print("HENTER HOLDKAMPE")
    print("=" * 90)

    print(
        "Klub:",
        club_id
    )

    print(
        "Hold:",
        team_name
    )

    print(
        "Række:",
        league_name
    )

    print(
        "League group:",
        league_group_id
    )

    # =====================================================
    # SESSION
    # =====================================================

    session = create_session()

    callback_context = (
        get_callback_context(
            session
        )
    )

    # =====================================================
    # RESOLVE TEAM IDS
    # =====================================================

    ids = resolve_team_ids(
        session=session,

        callback_context=
            callback_context,

        club_id=
            club_id,

        season_id=
            season_id,

        league_group_id=
            league_group_id,

        age_group_id=
            age_group_id,

        team_name=
            team_name,
    )

    region_id = (
        ids["region_id"]
    )

    league_group_team_id = (
        ids["league_group_team_id"]
    )

    print()
    print(
        "Region ID:",
        region_id
    )

    print(
        "League Group Team ID:",
        league_group_team_id
    )

    # =====================================================
    # GET MATCHES
    # =====================================================

    matches = get_team_matches(
        session=session,

        callback_context=
            callback_context,

        club_id=
            club_id,

        season_id=
            season_id,

        league_group_id=
            league_group_id,

        age_group_id=
            age_group_id,

        region_id=
            region_id,

        league_group_team_id=
            league_group_team_id,

        club_team_name=
            team_name,

        league_name=
            league_name,
    )

    # =====================================================
    # PRINT RESULTS
    # =====================================================

    print()
    print(
        f"Fundet {len(matches)} kampe:"
    )

    print()

    for match in matches:

        if match["match_time"]:

            match_time = (
                match["match_time"]
                .strftime(
                    "%d-%m-%Y %H:%M"
                )
            )

        else:

            match_time = "Ukendt"

        print(
            f"{match['league_match_id']} | "
            f"{match_time} | "
            f"{match['home_team']} - "
            f"{match['away_team']} | "
            f"{match['result'] or '-'}"
        )

    # =====================================================
    # AZURE
    # =====================================================

    if matches:

        print()
        print(
            "Gemmer i Azure..."
        )

        save_matches_to_azure(
            matches
        )

    else:

        print()
        print(
            "Ingen kampe fundet."
        )

    return matches


# =========================================================
# LOCAL TEST
# =========================================================

if __name__ == "__main__":

    fetch_and_save_team_matches(

        club_id=1148,

        season_id=2026,

        league_group_id=18844,

        age_group_id=1,

        team_name="Herlev/Hjorten",

        league_name=
            "3. division Pulje 3",
    )