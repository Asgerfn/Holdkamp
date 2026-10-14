import re
import sys
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from database import get_connection
from badmintonplayer import create_session, get_callback_context
from team_matches import call_badmintonplayer


BASE_URL = "https://www.badmintonplayer.dk"

KEYWORDS = (
    "rang",
    "rank",
    "point",
    "alder",
    "age",
    "født",
    "fodt",
    "birth",
    "klasse",
    "niveau",
    "licens",
)


def clean_text(value):
    return " ".join(
        str(value)
        .replace("\xa0", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .split()
    ).strip()


def section(title):
    print()
    print("=" * 110)
    print(title)
    print("=" * 110)


def get_match(league_match_id):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT TOP 1
                id,
                club_id,
                season_id,
                league_group_id,
                age_group_id,
                region_id,
                league_group_team_id,
                league_match_id,
                home_team,
                away_team,
                match_time
            FROM dbo.club_matches
            WHERE league_match_id = ?
            ORDER BY id DESC
            """,
            league_match_id,
        )

        row = cursor.fetchone()

        if row is None:
            raise RuntimeError(
                f"Ingen club_match fundet for league_match_id {league_match_id}"
            )

        return {
            "id": row.id,
            "club_id": row.club_id,
            "season_id": row.season_id,
            "league_group_id": row.league_group_id,
            "age_group_id": row.age_group_id,
            "region_id": row.region_id,
            "league_group_team_id": row.league_group_team_id,
            "league_match_id": row.league_match_id,
            "home_team": row.home_team,
            "away_team": row.away_team,
            "match_time": row.match_time,
        }

    finally:
        cursor.close()
        conn.close()


def summarize_html(label, html):
    soup = BeautifulSoup(html, "html.parser")
    visible = clean_text(soup.get_text(" ", strip=True))

    print()
    print("-" * 110)
    print(label)
    print("-" * 110)
    print("HTML længde:", len(html))
    print("Synlig tekst længde:", len(visible))
    print("Tabeller:", len(soup.find_all("table")))
    print("Links:", len(soup.find_all("a")))
    print("Inputs:", len(soup.find_all("input")))

    lowered = html.casefold()

    hits = {
        keyword: lowered.count(keyword.casefold())
        for keyword in KEYWORDS
        if keyword.casefold() in lowered
    }

    print("Keyword hits:", hits if hits else "ingen")

    interesting_rows = []

    for row in soup.find_all("tr"):
        text = clean_text(row.get_text(" ", strip=True))

        if not text:
            continue

        low = text.casefold()

        if any(keyword.casefold() in low for keyword in KEYWORDS):
            interesting_rows.append(text)

    if interesting_rows:
        print()
        print("Interessante tabelrækker:")
        for row in interesting_rows[:30]:
            print("  -", row[:1600])

    # Find links med spiller / print / kamprelaterede endpoints.
    links = []

    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        text = clean_text(a.get_text(" ", strip=True))

        if any(
            token in href.casefold()
            for token in (
                "spiller",
                "match",
                "kamp",
                "hold",
                "taeller",
                "dommer",
                "print",
                "udskriv",
            )
        ):
            links.append((text, href))

    if links:
        print()
        print("Relevante links:")
        for text, href in links[:50]:
            print(f"  - {text!r} -> {href}")

    # Snippets omkring konkrete keywords.
    snippets_found = 0

    for keyword in KEYWORDS:
        positions = [
            m.start()
            for m in re.finditer(
                re.escape(keyword),
                lowered,
            )
        ]

        if not positions:
            continue

        for pos in positions[:3]:
            start = max(0, pos - 250)
            end = min(len(html), pos + 700)
            snippet = clean_text(html[start:end])

            print()
            print(f"[{keyword}] {snippet}")

            snippets_found += 1

            if snippets_found >= 20:
                return


def fetch_subpages(session, callback_context, match):
    section("TESTER BADMINTONPLAYER SUBPAGES 0-10")

    for sub_page in range(0, 11):
        try:
            html = call_badmintonplayer(
                session=session,
                callback_context=callback_context,
                sub_page=sub_page,
                season_id=match["season_id"],
                club_id=match["club_id"],
                league_group_id=match["league_group_id"],
                age_group_id=match["age_group_id"],
                region_id=match["region_id"],
                league_group_team_id=match["league_group_team_id"],
                league_match_id=match["league_match_id"],
            )

            summarize_html(
                f"SUBPAGE {sub_page}",
                html,
            )

        except Exception as exc:
            print()
            print(f"SUBPAGE {sub_page}: FEJL -> {exc}")


def fetch_print_pages(session, match):
    section("TESTER PRINT-/HOLDSEDDEL-ENDPOINTS")

    match_id = match["league_match_id"]

    paths = [
        f"/DBF/HoldTurnering/UdskrivHoldkamp/?match={match_id}",
        f"/DBF/HoldTurnering/UdskrivTaellerKort/?match={match_id}",
        f"/DBF/HoldTurnering/UdskrivDommerseddel/?match={match_id}",
    ]

    for path in paths:
        url = urljoin(BASE_URL, path)

        try:
            response = session.get(
                url,
                timeout=30,
                allow_redirects=True,
            )

            print()
            print("URL:", url)
            print("Status:", response.status_code)
            print("Final URL:", response.url)

            summarize_html(
                path,
                response.text,
            )

        except Exception as exc:
            print()
            print("FEJL:", url, exc)


def main():
    if len(sys.argv) != 2:
        print("Brug:")
        print("python inspect_match_more_data.py LEAGUE_MATCH_ID")
        print()
        print("Eksempel:")
        print("python inspect_match_more_data.py 507496")
        sys.exit(1)

    league_match_id = int(sys.argv[1])

    match = get_match(
        league_match_id=league_match_id
    )

    section("MATCH")
    for key, value in match.items():
        print(f"{key:24}: {value}")

    session = create_session()
    callback_context = get_callback_context(session)

    fetch_subpages(
        session=session,
        callback_context=callback_context,
        match=match,
    )

    fetch_print_pages(
        session=session,
        match=match,
    )


if __name__ == "__main__":
    main()
