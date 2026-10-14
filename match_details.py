import re
import sys

from bs4 import BeautifulSoup

from database import get_connection
from match_details_database import (
    save_match_details_to_azure,
)
from badmintonplayer import (
    create_session,
    get_callback_context,
)

from team_matches import (
    call_badmintonplayer,
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

    value = str(value)

    value = (
        value
        .replace("\xa0", " ")
        .replace("\r", " ")
        .replace("\n", " ")
    )

    return " ".join(
        value.split()
    ).strip()


def normalize_key(value):

    return normalize_text(
        value
    ).casefold()


# =========================================================
# PLAYER PARSER
# =========================================================

def extract_players(
    cell,
    team_name=None,
):

    """
    Returnerer fx:

    [
        {
            "player_name": "Oliver Trzepacz",
            "badmintonplayer_id": 234562,
            "badminton_id": None
        }
    ]
    """

    players = []


    # =====================================================
    # PLAYER LINKS
    # =====================================================

    for link in cell.find_all(
        "a",
        href=True
    ):

        player_name = normalize_text(
            link.get_text(
                " ",
                strip=True
            )
        )

        href = link.get(
            "href",
            ""
        )


        match = re.search(
            r"/Spiller/VisSpiller/#(\d+)",
            href
        )


        if not player_name:
            continue


        if not match:
            continue


        players.append(
            {
                "player_name":
                    player_name,

                "badmintonplayer_id":
                    int(
                        match.group(1)
                    ),

                "badminton_id":
                    None,
            }
        )


    # Hvis links blev fundet, bruger vi dem.
    if players:
        return players


    # =====================================================
    # FALLBACK
    # =====================================================

    for value in cell.stripped_strings:

        player_name = normalize_text(
            value
        )


        if not player_name:
            continue


        if (
            team_name
            and normalize_key(player_name)
            == normalize_key(team_name)
        ):
            continue


        players.append(
            {
                "player_name":
                    player_name,

                "badmintonplayer_id":
                    None,

                "badminton_id":
                    None,
            }
        )


    return players


# =========================================================
# LINK PLAYERS TO AZURE
# =========================================================

def link_players_to_azure(
    details,
    club_id,
    season_id,
    club_team_name,
):

    """
    Kobler BadmintonPlayers interne player-ID til vores
    canonical badminton_players.

    Prioritet:

    1. Hvis badmintonplayer_id allerede findes i Azure:
       brug den eksisterende relation.

    2. Hvis det er en spiller fra brugerens egen klub:
       exact match på navn mod club_players.

    3. Hvis navnet matcher præcis én spiller:
       gem badmintonplayer_id permanent.

    Ingen fuzzy matching.
    """

    if not details.get(
        "games"
    ):
        return


    home_is_club = (
        normalize_key(
            details.get(
                "home_team"
            )
        )
        ==
        normalize_key(
            club_team_name
        )
    )


    away_is_club = (
        normalize_key(
            details.get(
                "away_team"
            )
        )
        ==
        normalize_key(
            club_team_name
        )
    )


    conn = get_connection()
    cursor = conn.cursor()


    try:

        # =================================================
        # LOAD CLUB PLAYERS
        # =================================================

        cursor.execute(
            """
            SELECT
                p.badminton_id,
                p.player_name,
                p.badmintonplayer_id

            FROM dbo.badminton_players p

            INNER JOIN dbo.club_players cp
                ON cp.badminton_id =
                    p.badminton_id

            WHERE
                cp.club_id = ?
                AND cp.season_id = ?
                AND cp.is_active = 1
            """,

            club_id,
            season_id
        )


        club_player_map = {}


        for row in cursor.fetchall():

            key = normalize_key(
                row.player_name
            )


            club_player_map.setdefault(
                key,
                []
            ).append(
                {
                    "badminton_id":
                        row.badminton_id,

                    "player_name":
                        row.player_name,

                    "badmintonplayer_id":
                        row.badmintonplayer_id,
                }
            )


        # Cache så samme spiller ikke slås op igen
        cache = {}


        # =================================================
        # PROCESS PLAYERS
        # =================================================

        for game in details["games"]:

            sides = [
                (
                    "home",
                    game["home_players"],
                    home_is_club,
                ),
                (
                    "away",
                    game["away_players"],
                    away_is_club,
                ),
            ]


            for (
                side,
                players,
                is_club_side,
            ) in sides:


                for player in players:

                    badmintonplayer_id = (
                        player.get(
                            "badmintonplayer_id"
                        )
                    )


                    if badmintonplayer_id is None:
                        continue


                    # =====================================
                    # CACHE
                    # =====================================

                    if badmintonplayer_id in cache:

                        player[
                            "badminton_id"
                        ] = cache[
                            badmintonplayer_id
                        ]

                        continue


                    # =====================================
                    # ALREADY KNOWN BY INTERNAL ID
                    # =====================================

                    cursor.execute(
                        """
                        SELECT
                            badminton_id

                        FROM dbo.badminton_players

                        WHERE
                            badmintonplayer_id = ?
                        """,

                        badmintonplayer_id
                    )


                    existing = (
                        cursor.fetchone()
                    )


                    if existing:

                        badminton_id = (
                            existing.badminton_id
                        )

                        player[
                            "badminton_id"
                        ] = badminton_id

                        cache[
                            badmintonplayer_id
                        ] = badminton_id

                        continue


                    # =====================================
                    # ONLY NAME-MATCH OWN CLUB
                    # =====================================

                    if not is_club_side:

                        cache[
                            badmintonplayer_id
                        ] = None

                        continue


                    player_name = (
                        player[
                            "player_name"
                        ]
                    )


                    candidates = (
                        club_player_map.get(
                            normalize_key(
                                player_name
                            ),
                            []
                        )
                    )


                    # Kun entydige exact matches
                    if len(candidates) != 1:

                        cache[
                            badmintonplayer_id
                        ] = None

                        continue


                    candidate = (
                        candidates[0]
                    )


                    badminton_id = (
                        candidate[
                            "badminton_id"
                        ]
                    )


                    existing_internal_id = (
                        candidate[
                            "badmintonplayer_id"
                        ]
                    )


                    # =====================================
                    # CONFLICT
                    # =====================================

                    if (
                        existing_internal_id
                        is not None
                        and existing_internal_id
                        != badmintonplayer_id
                    ):

                        print(
                            "ID-konflikt:",
                            player_name,
                            "| Azure:",
                            existing_internal_id,
                            "| Kamp:",
                            badmintonplayer_id
                        )

                        cache[
                            badmintonplayer_id
                        ] = None

                        continue


                    # =====================================
                    # MAKE SURE INTERNAL ID IS NOT OWNED
                    # BY ANOTHER PLAYER
                    # =====================================

                    cursor.execute(
                        """
                        SELECT
                            badminton_id

                        FROM dbo.badminton_players

                        WHERE
                            badmintonplayer_id = ?
                        """,

                        badmintonplayer_id
                    )


                    owner = (
                        cursor.fetchone()
                    )


                    if (
                        owner
                        and owner.badminton_id
                        != badminton_id
                    ):

                        print(
                            "ID-konflikt:",
                            badmintonplayer_id,
                            "tilhører allerede",
                            owner.badminton_id
                        )

                        cache[
                            badmintonplayer_id
                        ] = None

                        continue


                    # =====================================
                    # UPDATE AZURE
                    # =====================================

                    cursor.execute(
                        """
                        UPDATE dbo.badminton_players

                        SET
                            badmintonplayer_id = ?,
                            updated_at =
                                SYSUTCDATETIME()

                        WHERE
                            badminton_id = ?
                        """,

                        badmintonplayer_id,
                        badminton_id
                    )


                    player[
                        "badminton_id"
                    ] = badminton_id


                    cache[
                        badmintonplayer_id
                    ] = badminton_id


        conn.commit()


    except Exception:

        conn.rollback()
        raise


    finally:

        cursor.close()
        conn.close()


# =========================================================
# SCORE PARSER
# =========================================================

def parse_set_score(value):

    value = normalize_text(
        value
    )


    if not value:
        return None


    match = re.search(
        r"(\d+)\s*-\s*(\d+)",
        value
    )


    if not match:

        return {
            "raw":
                value,

            "home":
                None,

            "away":
                None,
        }


    return {
        "raw":
            value,

        "home":
            int(
                match.group(1)
            ),

        "away":
            int(
                match.group(2)
            ),
    }


# =========================================================
# WINNER
# =========================================================

def calculate_game_winner(
    sets
):

    home_sets = 0
    away_sets = 0


    for game_set in sets:

        if not game_set:
            continue


        home = game_set.get(
            "home"
        )

        away = game_set.get(
            "away"
        )


        if (
            home is None
            or away is None
        ):
            continue


        if home > away:

            home_sets += 1


        elif away > home:

            away_sets += 1


    if home_sets > away_sets:
        return "home"


    if away_sets > home_sets:
        return "away"


    return None


# =========================================================
# GAME LABEL
# =========================================================

def parse_game_label(value):

    value = normalize_text(
        value
    )


    # Understøtter både normale holdkampe:
    #
    #   1. MD
    #   1. HS
    #   1. DS
    #   1. HD
    #   1. DD
    #   1. XD
    #
    # og BadmintonPlayers "4 Spillere"-format:
    #
    #   1. S
    #   2. S
    #   1. D
    #   4. D
    #
    match = re.match(
        r"^(\d+)\.\s*(MD|DS|HS|DD|HD|MD|S|D)$",
        value,
        re.IGNORECASE
    )


    if not match:
        return None


    return {
        "match_number":
            int(
                match.group(1)
            ),

        "match_type":
            match.group(2).upper(),

        "match_label":
            value,
    }


# =========================================================
# FIND MATCH TABLE
# =========================================================

def find_match_table(soup):

    for table in soup.find_all(
        "table"
    ):

        table_text = normalize_text(
            table.get_text(
                " ",
                strip=True
            )
        )


        # En rigtig kamptabel har kolonnen "Vinder".
        if "Vinder" not in table_text:
            continue


        # I stedet for at kræve fx. "1. MD" eller "1. HS"
        # ser vi nu efter mindst én række, som vores
        # game-label parser genkender.
        #
        # Dermed virker både:
        #   normale holdkampe
        #   4-spiller-holdkampe med S / D
        for row in table.find_all(
            "tr"
        ):

            cells = row.find_all(
                "td"
            )


            if not cells:
                continue


            label_text = normalize_text(
                cells[0].get_text(
                    " ",
                    strip=True
                )
            )


            if parse_game_label(
                label_text
            ) is not None:

                return table


    return None


# =========================================================
# PARSE MATCH DETAILS
# =========================================================

def parse_match_details(
    html_content,
    league_match_id,
):

    soup = BeautifulSoup(
        html_content,
        "html.parser"
    )


    match_table = (
        find_match_table(
            soup
        )
    )


    if match_table is None:

        return {
            "league_match_id":
                league_match_id,

            "games":
                [],
        }


    rows = match_table.find_all(
        "tr"
    )


    home_team = None
    away_team = None


    if rows:

        header_cells = (
            rows[0].find_all(
                [
                    "th",
                    "td",
                ]
            )
        )


        if len(header_cells) >= 3:

            home_team = normalize_text(
                header_cells[1].get_text(
                    " ",
                    strip=True
                )
            )

            away_team = normalize_text(
                header_cells[2].get_text(
                    " ",
                    strip=True
                )
            )


    games = []


    # =====================================================
    # GAME ROWS
    # =====================================================

    for row in rows:

        cells = row.find_all(
            "td"
        )


        if len(cells) < 3:
            continue


        label_text = normalize_text(
            cells[0].get_text(
                " ",
                strip=True
            )
        )


        game_label = (
            parse_game_label(
                label_text
            )
        )


        if game_label is None:
            continue


        # =================================================
        # PLAYERS
        # =================================================

        home_players = (
            extract_players(
                cells[1],
                team_name=
                    home_team,
            )
        )


        away_players = (
            extract_players(
                cells[2],
                team_name=
                    away_team,
            )
        )


        # =================================================
        # SETS
        # =================================================

        sets = []


        for index in range(
            3,
            min(
                len(cells),
                6
            )
        ):

            raw_score = normalize_text(
                cells[index].get_text(
                    " ",
                    strip=True
                )
            )


            if not raw_score:
                continue


            parsed_score = (
                parse_set_score(
                    raw_score
                )
            )


            if parsed_score:

                parsed_score[
                    "set_number"
                ] = (
                    index - 2
                )


                sets.append(
                    parsed_score
                )


        # =================================================
        # W.O.
        # =================================================

        winner_wo = None


        if len(cells) >= 7:

            winner_wo = normalize_text(
                cells[6].get_text(
                    " ",
                    strip=True
                )
            )

            if not winner_wo:
                winner_wo = None


        winner_side = (
            calculate_game_winner(
                sets
            )
        )


        games.append(
            {
                "league_match_id":
                    int(
                        league_match_id
                    ),

                "match_number":
                    game_label[
                        "match_number"
                    ],

                "match_type":
                    game_label[
                        "match_type"
                    ],

                "match_label":
                    game_label[
                        "match_label"
                    ],

                "home_team":
                    home_team,

                "away_team":
                    away_team,

                "home_players":
                    home_players,

                "away_players":
                    away_players,

                "sets":
                    sets,

                "winner_side":
                    winner_side,

                "winner_wo_raw":
                    winner_wo,
            }
        )


    return {
        "league_match_id":
            int(
                league_match_id
            ),

        "home_team":
            home_team,

        "away_team":
            away_team,

        "games":
            games,
    }


# =========================================================
# GET SAVED MATCHES
# =========================================================

def get_saved_team_matches(
    club_id,
    season_id,
    league_group_id,
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
                AND league_group_id = ?

            ORDER BY
                match_time,
                league_match_id
            """,

            club_id,
            season_id,
            league_group_id
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

            for row in rows
        ]


    finally:

        cursor.close()
        conn.close()


# =========================================================
# FETCH ONE MATCH
# =========================================================

def fetch_match_details(
    session,
    callback_context,
    match,
):

    html_content = (
        call_badmintonplayer(
            session=
                session,

            callback_context=
                callback_context,

            sub_page=
                5,

            season_id=
                match[
                    "season_id"
                ],

            club_id=
                match[
                    "club_id"
                ],

            league_group_id=
                match[
                    "league_group_id"
                ],

            age_group_id=
                match[
                    "age_group_id"
                ],

            region_id=
                match[
                    "region_id"
                ],

            league_group_team_id=
                None,

            league_match_id=
                match[
                    "league_match_id"
                ],
        )
    )


    details = (
        parse_match_details(
            html_content=html_content,
            league_match_id=
                match[
                    "league_match_id"
                ],
        )
    )


    link_players_to_azure(
        details=details,
        club_id=match["club_id"],
        season_id=match["season_id"],
        club_team_name=
            match[
                "club_team_name"
            ],
    )


    save_result = (
        save_match_details_to_azure(
            match=match,
            details=details,
        )
    )


    if save_result["games"]:

        print(
            "  Azure:",
            f"{save_result['games']} delkampe,",
            f"{save_result['players']} spillere,",
            f"{save_result['sets']} sæt gemt"
        )


    return details

# =========================================================
# PLAYER DISPLAY
# =========================================================

def format_player(
    player
):

    text = player[
        "player_name"
    ]


    badmintonplayer_id = (
        player.get(
            "badmintonplayer_id"
        )
    )


    badminton_id = (
        player.get(
            "badminton_id"
        )
    )


    if badmintonplayer_id:

        text += (
            f" [BP:{badmintonplayer_id}]"
        )


    if badminton_id:

        text += (
            f" [{badminton_id}]"
        )


    return text


# =========================================================
# PRINT MATCH DETAILS
# =========================================================

def print_match_details(
    match,
    details,
):

    print()
    print("=" * 100)

    print(
        f"{match['league_match_id']} | "
        f"{match['home_team']} - "
        f"{match['away_team']}"
    )

    print("=" * 100)


    if not details["games"]:

        print(
            "Ingen individuelle kampe "
            "fundet endnu."
        )

        return


    for game in details["games"]:

        print()

        print(
            game[
                "match_label"
            ]
        )


        print(
            "  H:",
            " / ".join(
                format_player(
                    player
                )
                for player
                in game[
                    "home_players"
                ]
            )
        )


        print(
            "  U:",
            " / ".join(
                format_player(
                    player
                )
                for player
                in game[
                    "away_players"
                ]
            )
        )


        score_text = [
            game_set[
                "raw"
            ]
            for game_set
            in game[
                "sets"
            ]
        ]


        print(
            "  Sæt:",
            " | ".join(
                score_text
            )
            if score_text
            else "-"
        )


        print(
            "  Vinder:",
            game[
                "winner_side"
            ]
            or "-"
        )


        if game[
            "winner_wo_raw"
        ]:

            print(
                "  W.O.:",
                game[
                    "winner_wo_raw"
                ]
            )


# =========================================================
# FETCH ALL MATCHES FOR TEAM
# =========================================================

def fetch_all_match_details_for_team(
    club_id,
    season_id,
    league_group_id,
):

    matches = (
        get_saved_team_matches(
            club_id=
                club_id,

            season_id=
                season_id,

            league_group_id=
                league_group_id,
        )
    )


    if not matches:

        print(
            "Ingen kampe fundet i Azure."
        )

        return []


    print()
    print("=" * 100)
    print(
        "HENTER INDIVIDUELLE KAMPE"
    )
    print("=" * 100)

    print(
        "Hold:",
        matches[0][
            "club_team_name"
        ]
    )

    print(
        "Række:",
        matches[0][
            "league_name"
        ]
    )

    print(
        "League group:",
        league_group_id
    )

    print(
        "Holdkampe:",
        len(matches)
    )


    session = create_session()


    callback_context = (
        get_callback_context(
            session
        )
    )


    results = []


    for index, match in enumerate(
        matches,
        start=1
    ):

        print()

        print(
            f"[{index}/{len(matches)}] "
            f"Henter kamp "
            f"{match['league_match_id']}..."
        )


        try:

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


            print_match_details(
                match,
                details
            )


            results.append(
                {
                    "match":
                        match,

                    "details":
                        details,

                    "success":
                        True,
                }
            )


        except Exception as e:

            print(
                "FEJL:",
                e
            )


            results.append(
                {
                    "match":
                        match,

                    "details":
                        None,

                    "success":
                        False,

                    "error":
                        str(e),
                }
            )


    total_games = sum(
        len(
            result[
                "details"
            ][
                "games"
            ]
        )

        for result
        in results

        if (
            result[
                "success"
            ]
            and result[
                "details"
            ]
        )
    )


    matches_with_games = sum(
        1

        for result
        in results

        if (
            result[
                "success"
            ]
            and result[
                "details"
            ]
            and result[
                "details"
            ][
                "games"
            ]
        )
    )


    print()
    print("=" * 100)
    print("SUMMARY")
    print("=" * 100)

    print(
        "Holdkampe:",
        len(
            matches
        )
    )

    print(
        "Holdkampe med individuelle kampe:",
        matches_with_games
    )

    print(
        "Individuelle kampe fundet:",
        total_games
    )


    return results


# =========================================================
# LOCAL TEST
# =========================================================

if __name__ == "__main__":

    fetch_all_match_details_for_team(
        club_id=
            1148,

        season_id=
            2026,

        league_group_id=
            18844,
    )