import re
import sys
import argparse

from database import get_connection

from fantasy_points_database import (
    ensure_fantasy_point_tables,
)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8"
    )


# =========================================================
# POINT CONFIG
# =========================================================

POINTS = {

    # Match result
    "RESULT_WIN_2_0": 5,
    "RESULT_WIN_2_1": 4,
    "RESULT_LOSS_1_2": 2,
    "RESULT_LOSS_0_2": 1,

    # Walkover
    "WALKOVER_WIN": 1,
    "WALKOVER_LOSS": 0,

    # Set score
    "SET_WIN_0_5": 4,
    "SET_WIN_6_8": 2,

    "SET_LOSS_0_5": -4,
    "SET_LOSS_6_8": -2,

    # Long matches
    "LONG_MATCH": 2,
    "SET_REACHES_21": 1,

    # Team result
    "TEAM_WIN": 1,

    "TEAM_WIN_13_0": 3,
    "TEAM_LOSS_0_13": -3,

    # Hero bonus
    "HERO_LOSS_1_12": 4,
    "HERO_LOSS_2_11": 3,
}


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


def normalize_key(value):

    return normalize_text(
        value
    ).casefold()


def parse_team_result(value):

    """
    Fx:
        8-5
        13 - 0

    Returnerer:
        (8, 5)
    """

    value = normalize_text(
        value
    )

    match = re.search(
        r"(\d+)\s*-\s*(\d+)",
        value
    )

    if not match:
        return None


    return (
        int(
            match.group(1)
        ),
        int(
            match.group(2)
        ),
    )


# =========================================================
# DETERMINE CLUB SIDE
# =========================================================

def determine_club_side(
    club_team_name,
    home_team,
    away_team,
):

    club_key = normalize_key(
        club_team_name
    )

    home_key = normalize_key(
        home_team
    )

    away_key = normalize_key(
        away_team
    )


    if club_key == home_key:
        return "home"


    if club_key == away_key:
        return "away"


    # Fallback hvis BadmintonPlayer har lidt ekstra tekst
    if (
        home_key.startswith(
            club_key
        )
        and not away_key.startswith(
            club_key
        )
    ):
        return "home"


    if (
        away_key.startswith(
            club_key
        )
        and not home_key.startswith(
            club_key
        )
    ):
        return "away"


    raise RuntimeError(
        f"Kunne ikke afgøre klubbens side: "
        f"{club_team_name} | "
        f"{home_team} - {away_team}"
    )


# =========================================================
# EFFECTIVE WINNER
# =========================================================

def get_game_winner(
    winner_side,
    winner_wo_raw,
):

    """
    BadmintonPlayer bruger fx:

        (1) = første side / home
        (2) = anden side / away

    Ved W.O. bruger vi denne værdi fremfor
    sætscoren.
    """

    winner_wo_raw = normalize_text(
        winner_wo_raw
    )


    if winner_wo_raw:

        if "(1)" in winner_wo_raw:
            return "home"

        if "(2)" in winner_wo_raw:
            return "away"


    return winner_side


# =========================================================
# LOAD MATCH
# =========================================================

def get_match(
    cursor,
    club_match_id,
):

    cursor.execute(
        """
        SELECT
            id,
            club_id,
            season_id,

            club_team_name,

            home_team,
            away_team,

            result

        FROM dbo.club_matches

        WHERE id = ?
        """,

        club_match_id
    )


    row = cursor.fetchone()


    if row is None:

        raise RuntimeError(
            f"club_match_id {club_match_id} findes ikke."
        )


    return {
        "id":
            row.id,

        "club_id":
            row.club_id,

        "season_id":
            row.season_id,

        "club_team_name":
            row.club_team_name,

        "home_team":
            row.home_team,

        "away_team":
            row.away_team,

        "result":
            row.result,
    }


# =========================================================
# LOAD GAMES
# =========================================================

def get_games(
    cursor,
    club_match_id,
):

    cursor.execute(
        """
        SELECT
            id,
            match_number,
            match_type,
            match_label,

            winner_side,
            winner_wo_raw

        FROM dbo.club_match_games

        WHERE club_match_id = ?

        ORDER BY id
        """,

        club_match_id
    )


    rows = cursor.fetchall()


    return [
        {
            "id":
                row.id,

            "match_number":
                row.match_number,

            "match_type":
                row.match_type,

            "match_label":
                row.match_label,

            "winner_side":
                row.winner_side,

            "winner_wo_raw":
                row.winner_wo_raw,
        }

        for row in rows
    ]


# =========================================================
# LOAD GAME PLAYERS
# =========================================================

def get_game_players(
    cursor,
    game_id,
):

    cursor.execute(
        """
        SELECT
            side,
            player_order,

            player_name_snapshot,

            badmintonplayer_id,
            badminton_id

        FROM dbo.club_match_game_players

        WHERE game_id = ?

        ORDER BY
            CASE
                WHEN side = 'home'
                THEN 1
                ELSE 2
            END,

            player_order
        """,

        game_id
    )


    rows = cursor.fetchall()


    return [
        {
            "side":
                row.side,

            "player_order":
                row.player_order,

            "player_name":
                row.player_name_snapshot,

            "badmintonplayer_id":
                row.badmintonplayer_id,

            "badminton_id":
                row.badminton_id,
        }

        for row in rows
    ]


# =========================================================
# LOAD SETS
# =========================================================

def get_game_sets(
    cursor,
    game_id,
):

    cursor.execute(
        """
        SELECT
            set_number,
            home_score,
            away_score,
            raw_score

        FROM dbo.club_match_game_sets

        WHERE game_id = ?

        ORDER BY set_number
        """,

        game_id
    )


    rows = cursor.fetchall()


    return [
        {
            "set_number":
                row.set_number,

            "home_score":
                row.home_score,

            "away_score":
                row.away_score,

            "raw_score":
                row.raw_score,
        }

        for row in rows
    ]


# =========================================================
# EVENT KEY
# =========================================================

def make_event_key(
    club_match_id,
    player,
    event_code,
    game_id=None,
    set_number=None,
):

    player_key = (
        player.get(
            "badminton_id"
        )
        or
        f"BP{player.get('badmintonplayer_id')}"
    )


    game_key = (
        game_id
        if game_id is not None
        else 0
    )


    set_key = (
        set_number
        if set_number is not None
        else 0
    )


    return (
        f"M{club_match_id}"
        f":G{game_key}"
        f":P{player_key}"
        f":E{event_code}"
        f":S{set_key}"
    )


# =========================================================
# INSERT POINT EVENT
# =========================================================

def insert_event(
    cursor,
    match,
    player,
    event_code,
    description,
    game_id=None,
    set_number=None,
):

    if event_code not in POINTS:

        raise RuntimeError(
            f"Ukendt event_code: {event_code}"
        )


    points = POINTS[
        event_code
    ]


    event_key = make_event_key(
        club_match_id=
            match["id"],

        player=
            player,

        event_code=
            event_code,

        game_id=
            game_id,

        set_number=
            set_number,
    )


    cursor.execute(
        """
        INSERT INTO dbo.fantasy_point_events (

            club_id,
            season_id,

            club_match_id,

            game_id,
            set_number,

            badmintonplayer_id,
            badminton_id,

            player_name_snapshot,

            event_code,
            points,

            description,

            event_key

        )

        VALUES (
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?
        )
        """,

        match["club_id"],
        match["season_id"],

        match["id"],

        game_id,
        set_number,

        player.get(
            "badmintonplayer_id"
        ),

        player.get(
            "badminton_id"
        ),

        player.get(
            "player_name"
        ),

        event_code,
        points,

        description,

        event_key,
    )


# =========================================================
# CALCULATE SET SCORE
# =========================================================

def calculate_set_wins(
    sets
):

    home_sets = 0
    away_sets = 0


    for game_set in sets:

        home_score = game_set[
            "home_score"
        ]

        away_score = game_set[
            "away_score"
        ]


        if (
            home_score is None
            or away_score is None
        ):
            continue


        if home_score > away_score:
            home_sets += 1

        elif away_score > home_score:
            away_sets += 1


    return (
        home_sets,
        away_sets
    )


# =========================================================
# RESULT POINTS
# =========================================================

def add_result_points(
    cursor,
    match,
    game,
    own_players,
    own_side,
    sets,
):

    home_sets, away_sets = (
        calculate_set_wins(
            sets
        )
    )


    if own_side == "home":

        own_sets = home_sets
        opponent_sets = away_sets

    else:

        own_sets = away_sets
        opponent_sets = home_sets


    if (
        own_sets == 2
        and opponent_sets == 0
    ):

        event_code = (
            "RESULT_WIN_2_0"
        )

        description = (
            "Sejr 2-0"
        )


    elif (
        own_sets == 2
        and opponent_sets == 1
    ):

        event_code = (
            "RESULT_WIN_2_1"
        )

        description = (
            "Sejr 2-1"
        )


    elif (
        own_sets == 1
        and opponent_sets == 2
    ):

        event_code = (
            "RESULT_LOSS_1_2"
        )

        description = (
            "Nederlag 1-2"
        )


    elif (
        own_sets == 0
        and opponent_sets == 2
    ):

        event_code = (
            "RESULT_LOSS_0_2"
        )

        description = (
            "Nederlag 0-2"
        )


    else:

        return


    for player in own_players:

        insert_event(
            cursor=cursor,
            match=match,
            player=player,

            event_code=
                event_code,

            description=
                description,

            game_id=
                game["id"],
        )


# =========================================================
# WALKOVER POINTS
# =========================================================

def add_walkover_points(
    cursor,
    match,
    game,
    own_players,
    own_side,
):

    winner_side = (
        get_game_winner(
            winner_side=
                game[
                    "winner_side"
                ],

            winner_wo_raw=
                game[
                    "winner_wo_raw"
                ],
        )
    )


    if winner_side == own_side:

        event_code = (
            "WALKOVER_WIN"
        )

        description = (
            "W.O.-sejr"
        )


    else:

        event_code = (
            "WALKOVER_LOSS"
        )

        description = (
            "W.O.-nederlag"
        )


    for player in own_players:

        insert_event(
            cursor=cursor,
            match=match,
            player=player,

            event_code=
                event_code,

            description=
                description,

            game_id=
                game["id"],
        )


# =========================================================
# SET BONUSES / PENALTIES
# =========================================================

def add_set_points(
    cursor,
    match,
    game,
    own_players,
    own_side,
    sets,
):

    for game_set in sets:

        set_number = (
            game_set[
                "set_number"
            ]
        )

        home_score = (
            game_set[
                "home_score"
            ]
        )

        away_score = (
            game_set[
                "away_score"
            ]
        )


        if (
            home_score is None
            or away_score is None
        ):
            continue


        if own_side == "home":

            own_score = home_score
            opponent_score = away_score

        else:

            own_score = away_score
            opponent_score = home_score


        # =============================================
        # OWN SIDE WON SET
        # =============================================

        if own_score > opponent_score:

            if opponent_score <= 5:

                event_code = (
                    "SET_WIN_0_5"
                )

                description = (
                    f"Stor sætsejr "
                    f"{own_score}-{opponent_score}"
                )


            elif opponent_score <= 8:

                event_code = (
                    "SET_WIN_6_8"
                )

                description = (
                    f"Klar sætsejr "
                    f"{own_score}-{opponent_score}"
                )


            else:

                continue


        # =============================================
        # OWN SIDE LOST SET
        # =============================================

        elif opponent_score > own_score:

            if own_score <= 5:

                event_code = (
                    "SET_LOSS_0_5"
                )

                description = (
                    f"Stort sætnederlag "
                    f"{own_score}-{opponent_score}"
                )


            elif own_score <= 8:

                event_code = (
                    "SET_LOSS_6_8"
                )

                description = (
                    f"Klart sætnederlag "
                    f"{own_score}-{opponent_score}"
                )


            else:

                continue


        else:

            continue


        for player in own_players:

            insert_event(
                cursor=cursor,
                match=match,
                player=player,

                event_code=
                    event_code,

                description=
                    description,

                game_id=
                    game["id"],

                set_number=
                    set_number,
            )


# =========================================================
# LONG MATCH
# =========================================================

def add_long_match_bonus(
    cursor,
    match,
    game,
    own_players,
    sets,
):

    completed_sets = [
        game_set

        for game_set in sets

        if (
            game_set[
                "home_score"
            ]
            is not None

            and game_set[
                "away_score"
            ]
            is not None
        )
    ]


    set_count = len(
        completed_sets
    )


    total_points = sum(

        game_set[
            "home_score"
        ]
        +
        game_set[
            "away_score"
        ]

        for game_set
        in completed_sets
    )


    qualifies = False


    if (
        set_count == 2
        and total_points >= 60
    ):

        qualifies = True


    elif (
        set_count == 3
        and total_points >= 80
    ):

        qualifies = True


    if not qualifies:
        return


    for player in own_players:

        insert_event(
            cursor=cursor,
            match=match,
            player=player,

            event_code=
                "LONG_MATCH",

            description=
                f"Lang kamp med "
                f"{total_points} spillede point",

            game_id=
                game["id"],
        )


# =========================================================
# 21 POINT BONUS
# =========================================================

def add_21_bonus(
    cursor,
    match,
    game,
    own_players,
    sets,
):

    reaches_21 = any(

        (
            game_set[
                "home_score"
            ]
            is not None

            and game_set[
                "away_score"
            ]
            is not None

            and max(
                game_set[
                    "home_score"
                ],

                game_set[
                    "away_score"
                ]
            ) >= 21
        )

        for game_set
        in sets
    )


    if not reaches_21:
        return


    for player in own_players:

        insert_event(
            cursor=cursor,
            match=match,
            player=player,

            event_code=
                "SET_REACHES_21",

            description=
                "Mindst ét sæt nåede 21 point",

            game_id=
                game["id"],
        )


# =========================================================
# TEAM EVENTS
# =========================================================

def add_team_events(
    cursor,
    match,
    own_side,
    all_own_players,
    own_winning_games,
):

    parsed_result = (
        parse_team_result(
            match[
                "result"
            ]
        )
    )


    if parsed_result is None:

        return


    home_score, away_score = (
        parsed_result
    )


    if own_side == "home":

        own_score = home_score
        opponent_score = away_score

    else:

        own_score = away_score
        opponent_score = home_score


    # =====================================================
    # NORMAL TEAM WIN
    # =====================================================

    if own_score > opponent_score:

        for player in all_own_players.values():

            insert_event(
                cursor=cursor,
                match=match,
                player=player,

                event_code=
                    "TEAM_WIN",

                description=
                    f"Holdsejr "
                    f"{own_score}-{opponent_score}",
            )


    # =====================================================
    # 13-0
    # =====================================================

    if (
        own_score == 13
        and opponent_score == 0
    ):

        for player in all_own_players.values():

            insert_event(
                cursor=cursor,
                match=match,
                player=player,

                event_code=
                    "TEAM_WIN_13_0",

                description=
                    "Holdet vandt 13-0",
            )


    # =====================================================
    # 0-13
    # =====================================================

    if (
        own_score == 0
        and opponent_score == 13
    ):

        for player in all_own_players.values():

            insert_event(
                cursor=cursor,
                match=match,
                player=player,

                event_code=
                    "TEAM_LOSS_0_13",

                description=
                    "Holdet tabte 0-13",
            )


    # =====================================================
    # HERO BONUS 1-12
    # =====================================================

    if (
        own_score == 1
        and opponent_score == 12
        and len(
            own_winning_games
        ) == 1
    ):

        only_win_players = (
            own_winning_games[0]
        )


        for badminton_id in (
            only_win_players
        ):

            player = (
                all_own_players.get(
                    badminton_id
                )
            )


            if player:

                insert_event(
                    cursor=cursor,
                    match=match,
                    player=player,

                    event_code=
                        "HERO_LOSS_1_12",

                    description=
                        "Spilleren var med i "
                        "holdets eneste sejr "
                        "i et 1-12 nederlag",
                )


    # =====================================================
    # HERO BONUS 2-11
    # =====================================================

    if (
        own_score == 2
        and opponent_score == 11
        and len(
            own_winning_games
        ) == 2
    ):

        common_players = (
            own_winning_games[0]
            &
            own_winning_games[1]
        )


        for badminton_id in (
            common_players
        ):

            player = (
                all_own_players.get(
                    badminton_id
                )
            )


            if player:

                insert_event(
                    cursor=cursor,
                    match=match,
                    player=player,

                    event_code=
                        "HERO_LOSS_2_11",

                    description=
                        "Spilleren var med i "
                        "begge holdets sejre "
                        "i et 2-11 nederlag",
                )


# =========================================================
# RECALCULATE ONE MATCH
# =========================================================

def recalculate_match_points(
    club_match_id,
):

    ensure_fantasy_point_tables()


    conn = get_connection()
    cursor = conn.cursor()


    try:

        match = get_match(
            cursor=cursor,
            club_match_id=
                club_match_id,
        )


        games = get_games(
            cursor=cursor,
            club_match_id=
                club_match_id,
        )


        if not games:

            print(
                f"Kamp {club_match_id}: "
                f"ingen delkampe."
            )

            return {
                "club_match_id":
                    club_match_id,

                "games":
                    0,

                "events":
                    0,
            }


        own_side = (
            determine_club_side(
                club_team_name=
                    match[
                        "club_team_name"
                    ],

                home_team=
                    match[
                        "home_team"
                    ],

                away_team=
                    match[
                        "away_team"
                    ],
            )
        )


        # =================================================
        # DELETE OLD EVENTS
        # =================================================

        cursor.execute(
            """
            DELETE FROM dbo.fantasy_point_events

            WHERE club_match_id = ?
            """,

            club_match_id
        )


        # =================================================
        # TRACK TEAM PLAYERS / WINS
        # =================================================

        all_own_players = {}

        own_winning_games = []


        # =================================================
        # GAME LOOP
        # =================================================

        for game in games:

            players = (
                get_game_players(
                    cursor=
                        cursor,

                    game_id=
                        game["id"],
                )
            )


            sets = (
                get_game_sets(
                    cursor=
                        cursor,

                    game_id=
                        game["id"],
                )
            )


            # ---------------------------------------------
            # ONLY OWN CLUB PLAYERS WITH CANONICAL ID
            # ---------------------------------------------

            own_players = [

                player

                for player in players

                if (
                    player["side"]
                    == own_side

                    and player[
                        "badminton_id"
                    ]
                    is not None
                )
            ]


            if not own_players:

                continue


            for player in own_players:

                all_own_players[
                    player[
                        "badminton_id"
                    ]
                ] = player


            is_walkover = bool(
                normalize_text(
                    game[
                        "winner_wo_raw"
                    ]
                )
            )


            # =============================================
            # WALKOVER
            # =============================================

            if is_walkover:

                add_walkover_points(
                    cursor=
                        cursor,

                    match=
                        match,

                    game=
                        game,

                    own_players=
                        own_players,

                    own_side=
                        own_side,
                )

                # Ingen andre individuelle bonusser
                # på en W.O.-kamp.
                continue


            # =============================================
            # NORMAL MATCH RESULT
            # =============================================

            add_result_points(
                cursor=
                    cursor,

                match=
                    match,

                game=
                    game,

                own_players=
                    own_players,

                own_side=
                    own_side,

                sets=
                    sets,
            )


            # =============================================
            # SET BONUSES
            # =============================================

            add_set_points(
                cursor=
                    cursor,

                match=
                    match,

                game=
                    game,

                own_players=
                    own_players,

                own_side=
                    own_side,

                sets=
                    sets,
            )


            # =============================================
            # LONG MATCH
            # =============================================

            add_long_match_bonus(
                cursor=
                    cursor,

                match=
                    match,

                game=
                    game,

                own_players=
                    own_players,

                sets=
                    sets,
            )


            # =============================================
            # 21 BONUS
            # =============================================

            add_21_bonus(
                cursor=
                    cursor,

                match=
                    match,

                game=
                    game,

                own_players=
                    own_players,

                sets=
                    sets,
            )


            # =============================================
            # TRACK OWN CLUB GAME WINS
            # =============================================

            winner_side = (
                get_game_winner(
                    winner_side=
                        game[
                            "winner_side"
                        ],

                    winner_wo_raw=
                        game[
                            "winner_wo_raw"
                        ],
                )
            )


            if winner_side == own_side:

                own_winning_games.append(
                    {
                        player[
                            "badminton_id"
                        ]

                        for player
                        in own_players
                    }
                )


        # =================================================
        # TEAM EVENTS
        # =================================================

        add_team_events(
            cursor=
                cursor,

            match=
                match,

            own_side=
                own_side,

            all_own_players=
                all_own_players,

            own_winning_games=
                own_winning_games,
        )


        conn.commit()


        # =================================================
        # COUNT EVENTS
        # =================================================

        cursor.execute(
            """
            SELECT COUNT(*)

            FROM dbo.fantasy_point_events

            WHERE club_match_id = ?
            """,

            club_match_id
        )


        event_count = (
            cursor.fetchone()[0]
        )


        return {
            "club_match_id":
                club_match_id,

            "games":
                len(games),

            "events":
                event_count,
        }


    except Exception:

        conn.rollback()
        raise


    finally:

        cursor.close()
        conn.close()


# =========================================================
# PRINT POINTS FOR MATCH
# =========================================================

def print_match_points(
    club_match_id,
):

    conn = get_connection()
    cursor = conn.cursor()


    try:

        cursor.execute(
            """
            SELECT
                player_name_snapshot,
                badminton_id,
                SUM(points) AS total_points

            FROM dbo.fantasy_point_events

            WHERE club_match_id = ?

            GROUP BY
                player_name_snapshot,
                badminton_id

            ORDER BY
                total_points DESC,
                player_name_snapshot
            """,

            club_match_id
        )


        rows = (
            cursor.fetchall()
        )


        print()
        print("=" * 100)
        print("FANTASY POINT")
        print("=" * 100)


        for row in rows:

            print(
                f"{row.player_name_snapshot}: "
                f"{row.total_points} point "
                f"[{row.badminton_id}]"
            )


    finally:

        cursor.close()
        conn.close()


# =========================================================
# FIND MATCH BY LEAGUE MATCH ID
# =========================================================

def recalculate_by_league_match_id(
    league_match_id,
):

    conn = get_connection()
    cursor = conn.cursor()


    try:

        cursor.execute(
            """
            SELECT id

            FROM dbo.club_matches

            WHERE league_match_id = ?

            ORDER BY id
            """,

            league_match_id
        )


        match_ids = [
            row.id
            for row
            in cursor.fetchall()
        ]


    finally:

        cursor.close()
        conn.close()


    if not match_ids:

        print(
            f"Ingen club_match fundet for "
            f"league_match_id {league_match_id}."
        )

        return


    for club_match_id in match_ids:

        print()
        print("=" * 100)

        print(
            f"Beregner point for "
            f"league_match_id {league_match_id}"
        )

        print(
            f"club_match_id: {club_match_id}"
        )

        print("=" * 100)


        result = (
            recalculate_match_points(
                club_match_id=
                    club_match_id
            )
        )


        print(
            "Delkampe:",
            result[
                "games"
            ]
        )

        print(
            "Point-events:",
            result[
                "events"
            ]
        )


        print_match_points(
            club_match_id=
                club_match_id
        )


# =========================================================
# CLI
# =========================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "league_match_id",
        type=int,
        help="BadmintonPlayer league_match_id"
    )


    args = parser.parse_args()


    recalculate_by_league_match_id(
        league_match_id=
            args.league_match_id
    )