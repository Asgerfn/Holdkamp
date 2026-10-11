import re
import sys

import requests
from bs4 import BeautifulSoup


# =========================================================
# TERMINAL ENCODING
# =========================================================

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# =========================================================
# CONFIG
# =========================================================

CLUB_ID = 1148
SEASON_ID = 2026
RANKING_LIST_ID = 287

BASE_URL = (
    "https://www.badmintonplayer.dk/"
    "DBF/Ranglister/Udskriv/"
)


# =========================================================
# SESSION
# =========================================================

def create_session():

    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/154.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
        }
    )

    return session


# =========================================================
# HELPERS
# =========================================================

def normalize_text(value):

    if value is None:
        return ""

    value = str(value)

    value = (
        value
        .replace("\xa0", " ")
        .replace("\u2010", "-")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )

    return " ".join(value.split()).strip()


def looks_like_badminton_id(value):

    value = normalize_text(value)

    return bool(
        re.fullmatch(
            r"\d{6,8}-\d+",
            value
        )
    )


# =========================================================
# BUILD BADMINTONPLAYER PARAMS
# =========================================================

def build_print_params(
    club_id,
    season_id,
    page=0,
    ranking_list_id=287,
):

    values = [
        "15",
        str(ranking_list_id),
        str(season_id),
        "",
        "",
        "",
        str(club_id),
        "False",
        "",
        "",
        "",
        "",
        "0",
        "",
        "",
        str(page),
        "",
        "",
        "",
        "",
        "",
    ]

    return ",".join(values)


# =========================================================
# INTERNAL BADMINTONPLAYER ID
# =========================================================

def extract_badmintonplayer_id(cells):

    for cell in cells:

        for link in cell.find_all(
            "a",
            href=True
        ):

            href = link.get(
                "href",
                ""
            )

            match = re.search(
                r"/Spiller/VisSpiller/#(\d+)",
                href
            )

            if match:

                return int(
                    match.group(1)
                )

    return None


# =========================================================
# PARSE ONE PLAYER ROW
# =========================================================

def parse_player_row(cells):

    values = [
        normalize_text(
            cell.get_text(
                " ",
                strip=True
            )
        )
        for cell in cells
    ]


    # =====================================================
    # FIND BADMINTON ID
    # =====================================================

    badminton_id_index = None

    for index, value in enumerate(values):

        if looks_like_badminton_id(value):

            badminton_id_index = index
            break


    if badminton_id_index is None:
        return None


    badminton_id = values[
        badminton_id_index
    ]


    badmintonplayer_id = (
        extract_badmintonplayer_id(
            cells
        )
    )


    # =====================================================
    # NAME
    # =====================================================

    name_index = badminton_id_index + 1

    if name_index >= len(values):
        return None


    name_and_club = values[
        name_index
    ]


    # =====================================================
    # RANKING CLASS
    # =====================================================

    ranking_class = None

    class_index = (
        badminton_id_index + 2
    )

    if class_index < len(values):

        ranking_class = (
            values[class_index]
            or None
        )


    # =====================================================
    # POINTS
    # =====================================================

    points = None

    points_index = (
        badminton_id_index + 3
    )

    if points_index < len(values):

        raw_points = values[
            points_index
        ]

        if raw_points:
            points = raw_points


    # =====================================================
    # CLUB POSITION
    # =====================================================

    ranking_position = None

    if values:

        first_value = values[0]

        if first_value.isdigit():

            ranking_position = int(
                first_value
            )


    # =====================================================
    # NATIONAL POSITION
    # =====================================================

    national_position = None

    if badminton_id_index >= 1:

        possible_national = values[
            badminton_id_index - 1
        ]

        match = re.fullmatch(
            r"\((\d+)\)",
            possible_national
        )

        if match:

            national_position = int(
                match.group(1)
            )


    # =====================================================
    # NAME + CLUB
    # =====================================================

    player_name = name_and_club
    club_name = None

    if "," in name_and_club:

        player_name, club_name = (
            name_and_club.rsplit(
                ",",
                1
            )
        )

        player_name = (
            player_name.strip()
        )

        club_name = (
            club_name.strip()
        )


    return {
        "badminton_id":
            badminton_id,

        "badmintonplayer_id":
            badmintonplayer_id,

        "player_name":
            player_name,

        "club_name":
            club_name,

        "ranking_position":
            ranking_position,

        "national_position":
            national_position,

        "ranking_class":
            ranking_class,

        "points":
            points,

        "raw_cells":
            values,
    }


# =========================================================
# PARSE ONE PAGE
# =========================================================

def parse_players_from_html(html_text):

    soup = BeautifulSoup(
        html_text,
        "html.parser"
    )

    players = []


    for row in soup.find_all("tr"):

        cells = row.find_all(
            [
                "td",
                "th",
            ]
        )

        if not cells:
            continue


        player = parse_player_row(
            cells
        )

        if player is None:
            continue


        players.append(
            player
        )


    return players


# =========================================================
# GET ALL CLUB PLAYERS
# =========================================================

def get_club_players(
    club_id,
    season_id,
):

    session = create_session()

    all_players = []
    seen = set()

    page = 0


    print()
    print("=" * 100)
    print("HENTER SPILLERE FRA BADMINTONPLAYER")
    print("=" * 100)

    print(
        "Club ID:",
        club_id
    )

    print(
        "Season:",
        season_id
    )


    while True:

        print_params = (
            build_print_params(
                club_id=club_id,
                season_id=season_id,
                page=page,
            )
        )


        print()
        print(
            f"Henter side {page + 1} "
            f"(page={page})"
        )

        print(
            "Params:",
            print_params
        )


        response = session.get(
            BASE_URL,
            params={
                "params":
                    print_params
            },
            timeout=30,
        )


        print(
            "HTTP status:",
            response.status_code
        )


        response.raise_for_status()


        html_text = (
            response.content.decode(
                "windows-1252",
                errors="strict"
            )
        )


        page_players = (
            parse_players_from_html(
                html_text
            )
        )


        print(
            f"Spillere fundet på side {page + 1}:",
            len(page_players)
        )


        if not page_players:

            print(
                "Ingen spillere på siden - stopper."
            )

            break


        new_players = 0


        for player in page_players:

            badminton_id = (
                player[
                    "badminton_id"
                ]
            )


            if badminton_id in seen:
                continue


            seen.add(
                badminton_id
            )


            all_players.append(
                player
            )


            new_players += 1


        print(
            "Nye spillere:",
            new_players
        )

        print(
            "Spillere i alt:",
            len(all_players)
        )


        # BadmintonPlayer giver overlappende sider.
        # Når næste side ikke indeholder nye spillere,
        # er vi færdige.

        if new_players == 0:

            print(
                "Ingen nye spillere - stopper."
            )

            break


        page += 1


        if page >= 50:

            raise RuntimeError(
                "Mere end 50 sider fundet. "
                "Stopper for at undgå infinite loop."
            )


    print()
    print("=" * 100)
    print("FÆRDIG")
    print("=" * 100)

    print(
        "Spillere fundet i alt:",
        len(all_players)
    )


    return all_players


# =========================================================
# MAIN
# =========================================================

def main():

    players = get_club_players(
        club_id=CLUB_ID,
        season_id=SEASON_ID,
    )


    print()
    print("=" * 100)
    print("RESULTAT")
    print("=" * 100)

    print(
        "Spillere fundet:",
        len(players)
    )


    for index, player in enumerate(
        players[:50],
        start=1
    ):

        print()
        print(
            f"{index}."
        )

        print(
            "  BadmintonID:",
            player[
                "badminton_id"
            ]
        )

        print(
            "  BadmintonPlayer ID:",
            player.get(
                "badmintonplayer_id"
            )
        )

        print(
            "  Navn:",
            player[
                "player_name"
            ]
        )

        print(
            "  Klub:",
            player[
                "club_name"
            ]
        )

        print(
            "  Placering:",
            player[
                "ranking_position"
            ]
        )

        print(
            "  National placering:",
            player[
                "national_position"
            ]
        )

        print(
            "  Række:",
            player[
                "ranking_class"
            ]
        )

        print(
            "  Point:",
            player[
                "points"
            ]
        )


if __name__ == "__main__":
    main()