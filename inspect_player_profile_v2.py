import json
import re
import sys
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from badmintonplayer import create_session, get_callback_context


BASE_URL = "https://www.badmintonplayer.dk"
PROFILE_PATH = "/DBF/Spiller/VisSpiller/"
WEBSERVICE_JS = "/SportsResults/Components/WebService1.asmx/js"
WEBSERVICE_BASE = "/SportsResults/Components/WebService1.asmx"


KEYWORDS = (
    "birth",
    "birthdate",
    "født",
    "fodt",
    "alder",
    "age",
    "ranking",
    "rank",
    "rating",
    "point",
    "playerpoint",
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
    print("=" * 90)
    print(title)
    print("=" * 90)


def contains_interesting(text):
    lowered = text.casefold()
    return any(keyword.casefold() in lowered for keyword in KEYWORDS)


def print_relevant_hidden_fields(soup):
    section("RELEVANTE HIDDEN / INPUT FELTER")

    found = 0

    for inp in soup.find_all("input"):
        name = inp.get("name") or ""
        input_id = inp.get("id") or ""
        value = inp.get("value") or ""

        combined = f"{name} {input_id} {value}"

        if contains_interesting(combined):
            found += 1
            print(
                f"{found}.",
                {
                    "type": inp.get("type"),
                    "id": input_id,
                    "name": name,
                    "value": value,
                },
            )

    if found == 0:
        print("Ingen relevante inputfelter fundet.")


def print_relevant_visible_text(soup):
    section("RELEVANT SYNLIG PROFILTEKST")

    rows = []
    seen = set()

    for tag in soup.find_all(
        ["tr", "td", "th", "div", "span", "li", "p", "label"]
    ):
        text = clean_text(
            tag.get_text(" ", strip=True)
        )

        if (
            not text
            or text in seen
            or not contains_interesting(text)
        ):
            continue

        seen.add(text)

        # Undgå hele siden som én kæmpe blok.
        if len(text) <= 500:
            rows.append(text)

    if not rows:
        print("Ingen tydelig alder/ranking/point-tekst på den statiske profilside.")
        return

    for row in rows[:50]:
        print("-", row)


def get_scripts(soup, response_url):
    urls = []

    for script in soup.find_all("script"):
        src = script.get("src")

        if not src:
            continue

        url = urljoin(response_url, src)

        if "badmintonplayer.dk" in urlparse(url).netloc.casefold():
            urls.append(url)

    return list(dict.fromkeys(urls))


def inspect_webservice_proxy(session):
    section("RELEVANTE WEBSERVICE-METODER")

    url = urljoin(BASE_URL, WEBSERVICE_JS)

    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        js = response.text
    except Exception as exc:
        print("Kunne ikke hente WebService proxy:")
        print(exc)
        return []

    # Find alle metode-signaturer i den genererede ASP.NET AJAX proxy.
    pattern = re.compile(
        r"([A-Za-z0-9_]+):function\((.*?)\)\s*\{(.*?)\},",
        re.S,
    )

    interesting = []

    for match in pattern.finditer(js):
        method_name = match.group(1)
        params = clean_text(match.group(2))
        body = clean_text(match.group(3))

        blob = f"{method_name} {params} {body}"

        if contains_interesting(blob) or "player" in blob.casefold():
            interesting.append(
                {
                    "method": method_name,
                    "params": params,
                    "body": body[:900],
                }
            )

    if not interesting:
        print("Ingen relevante metoder fundet i proxyen.")
        return []

    # Print kun de mest interessante.
    ranked = sorted(
        interesting,
        key=lambda item: (
            0 if contains_interesting(item["method"]) else 1,
            0 if "player" in item["method"].casefold() else 1,
            item["method"],
        ),
    )

    shown = []

    for item in ranked[:30]:
        shown.append(item["method"])
        print()
        print("Metode:", item["method"])
        print("Parametre:", item["params"])

        if contains_interesting(item["body"]):
            print("Relevant body:", item["body"])

    return list(dict.fromkeys(shown))


def try_search_player(session, callback_context, player_id):
    section("TEST AF SEARCHPLAYER WEBSERVICE")

    url = urljoin(
        BASE_URL,
        WEBSERVICE_BASE + "/SearchPlayer",
    )

    payload = {
        "callbackcontextkey": callback_context,
        "selectfunctionname": "",
        "name": "",
        "clubid": "",
        "playerid": str(player_id),
        "gender": "",
        "agegroup": "",
        "searchteam": False,
        "licenseonly": False,
        "agegroupcontext": "",
        "tournamentdate": "",
    }

    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": urljoin(BASE_URL, PROFILE_PATH),
    }

    try:
        response = session.post(
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )

        print("HTTP status:", response.status_code)

        raw = response.text

        try:
            data = response.json()
            print("JSON-svar:")

            # Print kompakt - max ca. 10k tegn.
            formatted = json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            )
            print(formatted[:10000])

            lowered = formatted.casefold()

            found = [
                keyword
                for keyword in KEYWORDS
                if keyword.casefold() in lowered
            ]

            print()
            print("Interessante nøgleord i svar:", found or "ingen")

        except Exception:
            print("Ikke JSON. Første del af svar:")
            print(clean_text(raw)[:5000])

    except Exception as exc:
        print("SearchPlayer-kald fejlede:")
        print(exc)


def inspect_profile_page(session, player_id):
    section("SPILLERPROFIL")

    url = (
        f"{BASE_URL}{PROFILE_PATH}"
        f"#{player_id}"
    )

    print("Player ID:", player_id)
    print("URL:", url)

    response = session.get(
        url,
        timeout=30,
        allow_redirects=True,
    )
    response.raise_for_status()

    print("HTTP status:", response.status_code)
    print("Final URL:", response.url)
    print("HTML længde:", len(response.text))

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    title = (
        clean_text(soup.title.get_text(" ", strip=True))
        if soup.title
        else "-"
    )

    print("Titel:", title)

    print_relevant_visible_text(soup)
    print_relevant_hidden_fields(soup)

    return soup, response.url


def inspect_relevant_javascript(session, soup, response_url):
    section("RELEVANTE PROFIL-JAVASCRIPTS")

    urls = get_scripts(
        soup=soup,
        response_url=response_url,
    )

    hits = 0

    for url in urls:
        # Skip enorme generiske bundles hvor muligt.
        lower_url = url.casefold()

        if any(
            token in lower_url
            for token in (
                "vendors",
                "scriptresource.axd",
                "jquery",
                "bootstrap",
            )
        ):
            continue

        try:
            response = session.get(
                url,
                timeout=30,
            )
            response.raise_for_status()
            js = response.text
        except Exception:
            continue

        if not contains_interesting(js):
            continue

        hits += 1

        print()
        print("JS:", url)

        lines = clean_text(js)

        # Find kun korte snippets omkring relevante ord.
        for keyword in KEYWORDS:
            pos = lines.casefold().find(
                keyword.casefold()
            )

            if pos < 0:
                continue

            start = max(0, pos - 180)
            end = min(
                len(lines),
                pos + 550,
            )

            print(
                f"  {keyword}:",
                lines[start:end],
            )
            break

    if hits == 0:
        print("Ingen målrettede JS-hits ud over WebService-proxyen.")


def main():
    if len(sys.argv) != 2:
        print("Brug:")
        print("python inspect_player_profile_v2.py BADMINTONPLAYER_ID")
        print()
        print("Eksempel:")
        print("python inspect_player_profile_v2.py 72496")
        sys.exit(1)

    player_id = int(sys.argv[1])

    session = create_session()

    try:
        callback_context = get_callback_context(
            session
        )
    except Exception as exc:
        callback_context = None
        print(
            "Kunne ikke hente callback context:",
            exc,
        )

    soup, response_url = inspect_profile_page(
        session=session,
        player_id=player_id,
    )

    inspect_relevant_javascript(
        session=session,
        soup=soup,
        response_url=response_url,
    )

    inspect_webservice_proxy(
        session=session,
    )

    if callback_context:
        try_search_player(
            session=session,
            callback_context=callback_context,
            player_id=player_id,
        )
    else:
        section("SEARCHPLAYER TEST")
        print(
            "Sprunget over fordi callback context "
            "ikke kunne hentes."
        )


if __name__ == "__main__":
    main()
