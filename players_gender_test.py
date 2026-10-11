import re
import sys

import requests
from bs4 import BeautifulSoup


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8"
    )


# =========================================================
# CONFIG
# =========================================================

CLUB_ID = 1148
SEASON_ID = 2026

# Fra de links du lige har sendt
RANKING_LIST_ID = 289


BASE_URL = (
    "https://www.badmintonplayer.dk/"
    "DBF/Ranglister/Udskriv/"
)


# Kendte spillere til kontrol
SOFIE_ID = "081023-04"
OLIVER_ID = "040403-04"


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

            "Accept-Language":
                "da-DK,da;q=0.9,en;q=0.8",
        }
    )

    return session


# =========================================================
# NORMALIZE
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

    return " ".join(
        value.split()
    ).strip()


# =========================================================
# BADMINTON ID
# =========================================================

def looks_like_badminton_id(value):

    value = normalize_text(
        value
    )

    return bool(
        re.fullmatch(
            r"\d{6,8}-\d+",
            value
        )
    )


# =========================================================
# BUILD PRINT PARAMS
# =========================================================

def build_print_params(
    club_id,
    season_id,
    gender,
    page=0,
    ranking_list_id=289,
):

    """
    Eksisterende print-format:

    15,289,2026,,,,1148,False,,,,,0,,,0,,,,,

    Vi tilføjer køn som sidste parameter:

    ...,,,,,K
    eller
    ...,,,,,M

    Det matcher kønsfeltets placering i den
    almindelige rangliste-URL.
    """

    gender = (
        str(gender)
        .strip()
        .upper()
    )

    if gender not in {
        "M",
        "K"
    }:

        raise ValueError(
            "gender skal være 'M' eller 'K'"
        )


    values = [

        # Ranking type / print type
        "15",

        # Ranking list
        str(
            ranking_list_id
        ),

        # Season
        str(
            season_id
        ),

        "",

        "",

        "",

        # Club
        str(
            club_id
        ),

        "False",

        "",

        "",

        "",

        "",

        "0",

        "",

        "",

        # Pagination
        str(
            page
        ),

        "",

        "",

        "",

        "",

        "",

        # Gender
        gender,
    ]


    return ",".join(
        values
    )


# =========================================================
# PARSE PLAYER
# =========================================================

def parse_player_row(
    cells,
    gender,
):

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


    for index, value in enumerate(
        values
    ):

        if looks_like_badminton_id(
            value
        ):

            badminton_id_index = (
                index
            )

            break


    if badminton_id_index is None:
        return None


    badminton_id = values[
        badminton_id_index
    ]


    # =====================================================
    # NAME
    # =====================================================

    name_index = (
        badminton_id_index
        +
        1
    )


    if name_index >= len(values):
        return None


    name_and_club = values[
        name_index
    ]


    player_name = (
        name_and_club
    )

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


    # =====================================================
    # RANKING CLASS
    # =====================================================

    ranking_class = None

    class_index = (
        badminton_id_index
        +
        2
    )


    if class_index < len(values):

        ranking_class = (
            values[
                class_index
            ]
            or None
        )


    # =====================================================
    # RANKING POSITION
    # =====================================================

    ranking_position = None

    national_position = None


    if badminton_id_index >= 1:

        first_value = (
            values[0]
        )

        if first_value.isdigit():

            ranking_position = int(
                first_value
            )


    if badminton_id_index >= 2:

        possible_national = (
            values[
                badminton_id_index
                -
                1
            ]
        )

        match = re.fullmatch(
            r"\((\d+)\)",
            possible_national
        )

        if match:

            national_position = int(
                match.group(1)
            )


    # =====================================================
    # INTERNAL BADMINTONPLAYER ID
    # =====================================================

    badmintonplayer_id = None


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

                badmintonplayer_id = int(
                    match.group(1)
                )

                break


        if (
            badmintonplayer_id
            is not None
        ):

            break


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

        "gender":
            gender,

        "raw_cells":
            values,
    }


# =========================================================
# GET PLAYERS FOR ONE GENDER
# =========================================================

def get_players_for_gender(
    club_id,
    season_id,
    gender,
):

    gender = (
        gender
        .strip()
        .upper()
    )


    session = (
        create_session()
    )


    all_players = []

    seen = set()

    page = 0


    print()
    print(
        "=" * 100
    )

    print(
        f"HENTER KØN: {gender}"
    )

    print(
        "=" * 100
    )


    while True:

        params = (
            build_print_params(
                club_id=
                    club_id,

                season_id=
                    season_id,

                gender=
                    gender,

                page=
                    page,

                ranking_list_id=
                    RANKING_LIST_ID,
            )
        )


        print()
        print(
            f"Side {page + 1}"
        )

        print(
            "Params:",
            params
        )


        response = session.get(
            BASE_URL,

            params={
                "params":
                    params
            },

            timeout=30,
        )


        print(
            "HTTP:",
            response.status_code
        )

        print(
            "URL:",
            response.url
        )


        response.raise_for_status()


        html_text = (
            response.content.decode(
                "windows-1252",
                errors="replace"
            )
        )


        soup = BeautifulSoup(
            html_text,
            "html.parser"
        )


        page_players = []


        for row in soup.find_all(
            "tr"
        ):

            cells = row.find_all(
                [
                    "td",
                    "th",
                ]
            )


            if not cells:
                continue


            player = (
                parse_player_row(
                    cells=cells,
                    gender=gender,
                )
            )


            if player is None:
                continue


            page_players.append(
                player
            )


        print(
            "Rækker med spillere:",
            len(page_players)
        )


        # Ingen spillere overhovedet
        if not page_players:

            print(
                "Ingen spillere - stopper."
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
            "Unikke i alt:",
            len(all_players)
        )


        # VIGTIGT:
        # Vi stopper IKKE bare fordi siden
        # indeholder <100 spillere.
        #
        # BadmintonPlayer har tidligere haft
        # overlap mellem siderne.
        #
        # Vi stopper først når næste side
        # ikke giver nogen nye spillere.

        if new_players == 0:

            print(
                "Ingen nye spillere - stopper."
            )

            break


        page += 1


        if page >= 30:

            raise RuntimeError(
                "30 sider nået. "
                "Stopper som sikkerhedsnet."
            )


    return all_players


# =========================================================
# FIND PLAYER
# =========================================================

def find_player(
    players,
    badminton_id,
):

    for player in players:

        if (
            player[
                "badminton_id"
            ]
            ==
            badminton_id
        ):

            return player


    return None


# =========================================================
# PRINT SAMPLE
# =========================================================

def print_sample(
    title,
    players,
    amount=20,
):

    print()
    print(
        "=" * 100
    )

    print(
        title
    )

    print(
        "=" * 100
    )


    for index, player in enumerate(
        players[:amount],
        start=1
    ):

        print(
            f"{index:>3}. "
            f"{player['badminton_id']} | "
            f"{player['player_name']} | "
            f"{player['ranking_class']} | "
            f"køn={player['gender']}"
        )


# =========================================================
# MAIN
# =========================================================

def main():

    # =====================================================
    # WOMEN
    # =====================================================

    women = (
        get_players_for_gender(
            club_id=
                CLUB_ID,

            season_id=
                SEASON_ID,

            gender=
                "K",
        )
    )


    # =====================================================
    # MEN
    # =====================================================

    men = (
        get_players_for_gender(
            club_id=
                CLUB_ID,

            season_id=
                SEASON_ID,

            gender=
                "M",
        )
    )


    women_ids = {
        player[
            "badminton_id"
        ]
        for player in women
    }


    men_ids = {
        player[
            "badminton_id"
        ]
        for player in men
    }


    overlap = (
        women_ids
        &
        men_ids
    )


    # =====================================================
    # RESULTS
    # =====================================================

    print()
    print()
    print(
        "#" * 100
    )

    print(
        "RESULTAT"
    )

    print(
        "#" * 100
    )


    print()
    print(
        "Kvinder:",
        len(women)
    )

    print(
        "Herrer:",
        len(men)
    )

    print(
        "Samlet:",
        len(
            women_ids
            |
            men_ids
        )
    )

    print(
        "Overlap mellem K og M:",
        len(overlap)
    )


    # =====================================================
    # KNOWN PLAYER TESTS
    # =====================================================

    sofie_woman = (
        find_player(
            women,
            SOFIE_ID
        )
    )

    sofie_man = (
        find_player(
            men,
            SOFIE_ID
        )
    )


    oliver_man = (
        find_player(
            men,
            OLIVER_ID
        )
    )

    oliver_woman = (
        find_player(
            women,
            OLIVER_ID
        )
    )


    print()
    print(
        "-" * 100
    )

    print(
        "KONTROLSPILLERE"
    )

    print(
        "-" * 100
    )


    print()
    print(
        "Sofie Dahl:"
    )

    print(
        "  Findes under K:",
        bool(
            sofie_woman
        )
    )

    print(
        "  Findes under M:",
        bool(
            sofie_man
        )
    )


    print()
    print(
        "Oliver Trzepacz:"
    )

    print(
        "  Findes under M:",
        bool(
            oliver_man
        )
    )

    print(
        "  Findes under K:",
        bool(
            oliver_woman
        )
    )


    # =====================================================
    # OVERLAP
    # =====================================================

    if overlap:

        print()
        print(
            "ADVARSEL:"
        )

        print(
            "Følgende spillere findes både "
            "på K- og M-listen:"
        )


        for badminton_id in sorted(
            overlap
        ):

            player = (
                find_player(
                    women,
                    badminton_id
                )
                or
                find_player(
                    men,
                    badminton_id
                )
            )

            print(
                badminton_id,
                "-",
                player[
                    "player_name"
                ]
                if player
                else ""
            )


    # =====================================================
    # SAMPLES
    # =====================================================

    print_sample(
        "FØRSTE KVINDER",
        women,
    )


    print_sample(
        "FØRSTE HERRER",
        men,
    )


    # =====================================================
    # FINAL VALIDATION
    # =====================================================

    print()
    print(
        "=" * 100
    )

    print(
        "VALIDERING"
    )

    print(
        "=" * 100
    )


    success = True


    if sofie_woman is None:

        print(
            "[FEJL] Sofie Dahl blev "
            "ikke fundet under K."
        )

        success = False


    if sofie_man is not None:

        print(
            "[FEJL] Sofie Dahl blev også "
            "fundet under M."
        )

        success = False


    if oliver_man is None:

        print(
            "[FEJL] Oliver Trzepacz blev "
            "ikke fundet under M."
        )

        success = False


    if oliver_woman is not None:

        print(
            "[FEJL] Oliver Trzepacz blev også "
            "fundet under K."
        )

        success = False


    if overlap:

        print(
            "[FEJL] K og M har overlap."
        )

        success = False


    if success:

        print()
        print(
            "[OK] K/M-filteret virker."
        )

        print(
            "Vi kan bruge ranglisten som "
            "kilde til spillerens køn."
        )

    else:

        print()
        print(
            "[IKKE OK] Filteret virker ikke "
            "som forventet på print-endpointet."
        )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()