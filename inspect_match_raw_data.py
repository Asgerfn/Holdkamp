import re
import sys
from bs4 import BeautifulSoup

from database import get_connection
from badmintonplayer import create_session, get_callback_context
from team_matches import call_badmintonplayer


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def get_match_by_league_match_id(league_match_id):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT TOP 1
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
            "club_team_name": row.club_team_name,
            "league_name": row.league_name,
            "league_group_id": row.league_group_id,
            "age_group_id": row.age_group_id,
            "region_id": row.region_id,
            "league_group_team_id": row.league_group_team_id,
            "league_match_id": row.league_match_id,
            "match_time": row.match_time,
            "home_team": row.home_team,
            "away_team": row.away_team,
            "result": row.result,
            "points": row.points,
        }

    finally:
        cursor.close()
        conn.close()


def compact_text(value):
    return " ".join(str(value).replace("\xa0", " ").split()).strip()


def print_section(title):
    print()
    print("=" * 110)
    print(title)
    print("=" * 110)


def print_match_metadata(match):
    print_section("MATCH FRA DATABASEN")

    for key, value in match.items():
        print(f"{key:24}: {value}")


def inspect_raw_html(html_content):
    soup = BeautifulSoup(html_content, "html.parser")

    print_section("HTML OVERBLIK")
    print("HTML længde:", len(html_content))
    print("Antal tags:", len(soup.find_all(True)))
    print("Antal tabeller:", len(soup.find_all("table")))
    print("Antal links:", len(soup.find_all("a")))
    print("Antal inputs:", len(soup.find_all("input")))
    print("Antal scripts:", len(soup.find_all("script")))

    print_section("ALLE PLAYER-LINKS + ATTRIBUTTER")

    player_links = []

    for a in soup.find_all("a"):
        href = a.get("href") or ""
        text = compact_text(a.get_text(" ", strip=True))

        if (
            "player" in href.lower()
            or "spiller" in href.lower()
            or re.search(r"\d{3,}", href)
        ):
            player_links.append(a)

    if not player_links:
        print("Ingen oplagte player-links fundet.")
    else:
        for i, a in enumerate(player_links, start=1):
            print()
            print(f"[{i}] TEXT: {compact_text(a.get_text(' ', strip=True))}")
            print("    href:", a.get("href"))
            print("    attrs:", dict(a.attrs))

            parent = a.parent
            if parent:
                print(
                    "    parent:",
                    compact_text(parent.get_text(" ", strip=True))[:500]
                )

            row = a.find_parent("tr")
            if row:
                print(
                    "    row:",
                    compact_text(row.get_text(" ", strip=True))[:1000]
                )

    print_section("DATA-* ATTRIBUTTER")

    found_data_attrs = False

    for tag in soup.find_all(True):
        data_attrs = {
            key: value
            for key, value in tag.attrs.items()
            if key.lower().startswith("data-")
        }

        if data_attrs:
            found_data_attrs = True
            text = compact_text(tag.get_text(" ", strip=True))

            print(
                f"<{tag.name}>",
                data_attrs,
                "| text:",
                text[:400]
            )

    if not found_data_attrs:
        print("Ingen data-* attributter fundet.")

    print_section("TEKSTLINJER MED MULIGE POINT / ALDER / FØDSELSDATA")

    keywords = (
        "point",
        "rating",
        "rang",
        "rank",
        "alder",
        "født",
        "fodt",
        "birth",
        "år",
        "years",
    )

    seen = set()
    matches = []

    for tag in soup.find_all(["td", "th", "div", "span", "li", "p", "a"]):
        text = compact_text(tag.get_text(" ", strip=True))

        if not text or text in seen:
            continue

        lowered = text.casefold()

        if any(keyword in lowered for keyword in keywords):
            seen.add(text)
            matches.append(text)

    if not matches:
        print("Ingen tydelige tekstfelter med de søgeord blev fundet.")
    else:
        for line in matches[:200]:
            print("-", line[:1000])

    print_section("TAL-RIGE FELTER TÆT PÅ SPILLERE")

    numeric_candidates = []

    for a in player_links:
        row = a.find_parent("tr")
        container = row or a.parent

        if not container:
            continue

        text = compact_text(container.get_text(" ", strip=True))

        if re.search(r"\b\d{2,5}\b", text):
            numeric_candidates.append(text)

    if not numeric_candidates:
        print("Ingen oplagte tal-rige spillerfelter fundet.")
    else:
        for line in dict.fromkeys(numeric_candidates):
            print("-", line[:1500])

    print_section("SCRIPT / JAVASCRIPT MATCHES")

    script_hits = []

    for script in soup.find_all("script"):
        script_text = script.string or script.get_text(" ", strip=True) or ""

        if any(
            token in script_text.casefold()
            for token in (
                "player",
                "spiller",
                "point",
                "rating",
                "rank",
                "birth",
                "alder",
            )
        ):
            script_hits.append(script_text)

    if not script_hits:
        print("Ingen relevante scripts fundet.")
    else:
        for i, script_text in enumerate(script_hits[:20], start=1):
            print()
            print(f"--- SCRIPT {i} ---")
            print(script_text[:5000])

    print_section("HTML SNIPPETS OMKRING SØGEORD")

    raw_lower = html_content.casefold()

    for keyword in (
        "point",
        "rating",
        "ranking",
        "rank",
        "alder",
        "født",
        "fodt",
        "birth",
    ):
        positions = [
            match.start()
            for match in re.finditer(re.escape(keyword), raw_lower)
        ]

        if not positions:
            continue

        print()
        print(f"### {keyword.upper()} ({len(positions)} hits)")

        for pos in positions[:10]:
            start = max(0, pos - 350)
            end = min(len(html_content), pos + 700)
            snippet = compact_text(html_content[start:end])
            print("-", snippet)


def main():
    if len(sys.argv) != 2:
        print("Brug:")
        print("python inspect_match_raw_data.py LEAGUE_MATCH_ID")
        print()
        print("Eksempel:")
        print("python inspect_match_raw_data.py 123456")
        sys.exit(1)

    league_match_id = int(sys.argv[1])

    match = get_match_by_league_match_id(
        league_match_id=league_match_id
    )

    print_match_metadata(match)

    print_section("HENTER RAW MATCH-HTML")

    session = create_session()
    callback_context = get_callback_context(session)

    html_content = call_badmintonplayer(
        session=session,
        callback_context=callback_context,
        sub_page=5,
        season_id=match["season_id"],
        club_id=match["club_id"],
        league_group_id=match["league_group_id"],
        age_group_id=match["age_group_id"],
        region_id=match["region_id"],
        league_group_team_id=None,
        league_match_id=match["league_match_id"],
    )

    print("Raw HTML hentet OK.")

    inspect_raw_html(
        html_content=html_content
    )


if __name__ == "__main__":
    main()
