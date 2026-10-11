import json
import re
import sys

import requests
from bs4 import BeautifulSoup

# =========================================================
# WINDOWS UTF-8
# =========================================================

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8",
        errors="replace"
    )


# =========================================================
# TEST SETTINGS
# =========================================================

CLUB_ID = 1148
SEASON_ID = 2026

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


# =========================================================
# CALLBACK KEY
# =========================================================
def find_callback_context_key(html_text):

    patterns = [

        # BadmintonPlayers faktiske format
        r"var\s+SR_CallbackContext\s*=\s*['\"]([^'\"]+)['\"]",

        # Fallbacks
        r'"callbackcontextkey"\s*:\s*"([^"]+)"',
        r"'callbackcontextkey'\s*:\s*'([^']+)'",
        r'callbackcontextkey\s*[:=]\s*"([^"]+)"',
        r"callbackcontextkey\s*[:=]\s*'([^']+)'",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            html_text,
            re.IGNORECASE
        )

        if match:

            return match.group(1)

    return None

# =========================================================
# DEBUG CALLBACK OCCURRENCES
# =========================================================

def print_callback_snippets(html_text):

    print("\nSøger efter 'callback' i HTML...\n")

    lower = html_text.lower()

    positions = [
        match.start()
        for match in re.finditer(
            "callback",
            lower
        )
    ]

    if not positions:

        print("Ingen 'callback'-tekst fundet i HTML.")
        return


    print(
        f"Fundet {len(positions)} forekomster.\n"
    )


    for number, position in enumerate(
        positions[:10],
        start=1
    ):

        start = max(
            0,
            position - 200
        )

        end = min(
            len(html_text),
            position + 400
        )

        snippet = (
            html_text[start:end]
            .replace("\n", " ")
            .replace("\r", " ")
        )

        print(
            f"--- CALLBACK {number} ---"
        )

        print(snippet)

        print()


# =========================================================
# STEP 1
# LOAD NORMAL PAGE
# =========================================================

print("=" * 90)
print("STEP 1 - HENTER NORMAL BADMINTONPLAYER-SIDE")
print("=" * 90)

response = session.get(
    PAGE_URL,
    timeout=30
)


print(
    "Status:",
    response.status_code
)

print(
    "Endelig URL:",
    response.url
)

print(
    "HTML længde:",
    len(response.text)
)

print(
    "Cookies:",
    session.cookies.get_dict()
)


response.raise_for_status()


# =========================================================
# STEP 2
# FIND CALLBACK KEY
# =========================================================

print()
print("=" * 90)
print("STEP 2 - FIND CALLBACKCONTEXTKEY")
print("=" * 90)


callback_key = find_callback_context_key(
    response.text
)


if callback_key:

    print(
        "\nCallback context key fundet:"
    )

    print(
        callback_key
    )

else:

    print(
        "\nIngen callbackcontextkey fundet direkte."
    )

    print_callback_snippets(
        response.text
    )


# =========================================================
# STEP 3
# CALL API
# =========================================================

print()
print("=" * 90)
print("STEP 3 - KALDER GETLEAGUESTANDING")
print("=" * 90)


payload = {
    "ageGroupID": None,
    "callbackcontextkey": callback_key or "",
    "clubID": str(CLUB_ID),
    "leagueGroupID": None,
    "leagueGroupTeamID": None,
    "leagueMatchID": None,
    "playerID": None,
    "regionID": None,
    "seasonID": str(SEASON_ID),
    "subPage": 6
}


headers = {
    "Accept": "application/json, text/javascript, */*; q=0.01",

    "Content-Type":
        "application/json; charset=UTF-8",

    "Origin":
        "https://www.badmintonplayer.dk",

    "Referer":
        PAGE_URL,

    "X-Requested-With":
        "XMLHttpRequest",
}


print(
    "\nPayload:"
)

print(
    json.dumps(
        payload,
        indent=4,
        ensure_ascii=False
    )
)


api_response = session.post(
    API_URL,
    headers=headers,
    json=payload,
    timeout=30
)


print()
print(
    "API status:",
    api_response.status_code
)

print(
    "Content-Type:",
    api_response.headers.get(
        "Content-Type"
    )
)

print(
    "Svar længde:",
    len(api_response.text)
)


# =========================================================
# STEP 4
# SHOW RESPONSE
# =========================================================

print()
print("=" * 90)
print("STEP 4 - SVAR")
print("=" * 90)


print(
    api_response.text[:3000]
)


# =========================================================
# TRY JSON
# =========================================================
# =========================================================
# PARSE JSON + HTML WITH BEAUTIFULSOUP
# =========================================================

data = api_response.json()

print()
print("=" * 90)
print("JSON MODTAGET")
print("=" * 90)

print("JSON type:", type(data).__name__)
print("Keys:", list(data.keys()))


# =========================================================
# GET HTML
# =========================================================

result = data.get("d")

if not isinstance(result, dict):

    raise RuntimeError(
        f"data['d'] havde uventet type: "
        f"{type(result).__name__}"
    )


html_content = result.get("html")

if not html_content:

    raise RuntimeError(
        "Kunne ikke finde HTML i data['d']['html']"
    )


print()
print("HTML fundet!")
print("HTML længde:", len(html_content))


# =========================================================
# BEAUTIFULSOUP
# =========================================================

soup = BeautifulSoup(
    html_content,
    "html.parser"
)


# =========================================================
# FIND ALL ROWS
# =========================================================

rows = soup.find_all("tr")

print()
print("Antal <tr> i alt:", len(rows))


# =========================================================
# PARSE SECTIONS + TEAMS
# =========================================================

current_section = None

teams = []


for row in rows:

    classes = row.get(
        "class",
        []
    )


    # -----------------------------------------------------
    # SECTION HEADER
    # -----------------------------------------------------

    if "agegrouprow" in classes:

        heading = row.find("h3")

        if heading:

            current_section = heading.get_text(
                " ",
                strip=True
            )

            print()
            print(
                f"--- SEKTION: {current_section} ---"
            )

        continue


    # -----------------------------------------------------
    # TEAM ROW
    # -----------------------------------------------------

    if "grouprow" not in classes:

        continue


    cells = row.find_all("td")

    if len(cells) < 2:

        continue


    team_name = cells[0].get_text(
        " ",
        strip=True
    )


    link = cells[1].find(
        "a",
        onclick=True
    )


    if not link:

        continue


    league_name = link.get_text(
        " ",
        strip=True
    )


    onclick = link.get(
        "onclick",
        ""
    )


    # -----------------------------------------------------
    # EXTRACT SHOWSTANDING ARGS
    # -----------------------------------------------------

    match = re.search(
        r"ShowStanding\((.*?)\)",
        onclick
    )


    if not match:

        continue


    args = re.findall(
        r"'([^']*)'",
        match.group(1)
    )


    if len(args) < 8:

        continue


    season_id = args[1]
    league_group_id = args[2]
    league_group_team_id = args[3]
    club_id = args[7]


    team = {
        "section": current_section,
        "team_name": team_name,
        "league_name": league_name,
        "season_id": season_id,
        "league_group_id": league_group_id,
        "league_group_team_id": league_group_team_id,
        "club_id": club_id,
    }


    teams.append(team)


    print()
    print("Hold:      ", team_name)
    print("Sektion:   ", current_section)
    print("Række:     ", league_name)
    print("Group ID:  ", league_group_id)
    print("Team ID:   ", league_group_team_id)
    print("Club ID:   ", club_id)


# =========================================================
# SUMMARY
# =========================================================

print()
print("=" * 90)
print("SUMMARY")
print("=" * 90)

print(
    "Antal hold/rækker:",
    len(teams)
)


print()
print("=" * 90)
print("TEST FÆRDIG")
print("=" * 90)