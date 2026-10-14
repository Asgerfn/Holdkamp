import json
import sys

from bs4 import BeautifulSoup

from badmintonplayer import create_session, get_callback_context


BASE_URL = "https://www.badmintonplayer.dk"
SEARCHPLAYER_URL = (
    BASE_URL
    + "/SportsResults/Components/WebService1.asmx/SearchPlayer"
)


def section(title):
    print()
    print("=" * 90)
    print(title)
    print("=" * 90)


def clean_text(value):
    return " ".join(
        str(value)
        .replace("\xa0", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .split()
    ).strip()


def inspect_html(html):
    soup = BeautifulSoup(html, "html.parser")

    section("SEARCHPLAYER HTML - KOMPAKT")

    text = clean_text(soup.get_text(" ", strip=True))
    print(text[:12000] if text else "(ingen synlig tekst)")

    section("LINKS / ONCLICK / DATA")

    found = 0

    for tag in soup.find_all(True):
        attrs = dict(tag.attrs)

        interesting = {}

        for key, value in attrs.items():
            key_lower = key.lower()

            if (
                key_lower in {"href", "onclick", "id", "name", "value"}
                or key_lower.startswith("data-")
            ):
                interesting[key] = value

        blob = (
            clean_text(tag.get_text(" ", strip=True))
            + " "
            + str(interesting)
        ).casefold()

        if any(
            token in blob
            for token in (
                "player",
                "spiller",
                "72496",
                "point",
                "rank",
                "age",
                "birth",
            )
        ):
            found += 1
            print()
            print(f"[{found}] <{tag.name}>")
            print("text :", clean_text(tag.get_text(" ", strip=True))[:1000])
            print("attrs:", interesting)

    if found == 0:
        print("Ingen oplagte relevante tags fundet.")


def main():
    if len(sys.argv) != 2:
        print("Brug:")
        print("python inspect_player_profile.py PLAYER_NUMBER")
        print()
        print("Eksempel:")
        print("python inspect_player_profile.py 72496")
        sys.exit(1)

    player_number = str(sys.argv[1]).strip()

    session = create_session()
    callback_context = get_callback_context(session)

    section("SEARCHPLAYER - KORREKT PARAMETERLISTE")

    payload = {
        "callbackcontextkey": callback_context,
        "selectfunction": "TEST",
        "name": "",
        "clubid": "",
        "playernumber": player_number,
        "gender": "",
        "agegroupid": "",
        "searchteam": False,
        "licenseonly": False,
        "agegroupcontext": "",
        "tournamentdate": "",
    }

    print("Player number:", player_number)
    print("Endpoint:", SEARCHPLAYER_URL)
    print()
    print("Payload:")
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
    )

    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": BASE_URL + "/DBF/Spiller/VisSpiller/",
    }

    response = session.post(
        SEARCHPLAYER_URL,
        headers=headers,
        json=payload,
        timeout=30,
    )

    section("HTTP SVAR")
    print("Status:", response.status_code)
    print("Content-Type:", response.headers.get("Content-Type"))

    section("RAW SVAR")
    print(response.text[:30000])

    try:
        data = response.json()
    except Exception as exc:
        section("JSON PARSE FEJL")
        print(exc)
        return

    section("PARSET JSON")
    print(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )[:30000]
    )

    result = data.get("d") if isinstance(data, dict) else None

    if isinstance(result, dict):
        section("TOP-LEVEL FELTER I d")

        for key, value in result.items():
            if key == "Html":
                print("Html: <udeladt her - vises nedenfor>")
            else:
                print(f"{key}: {value}")

        html = result.get("Html")

        if html:
            inspect_html(html)

    section("INTERESSANTE NØGLEORD I HELE SVARET")

    dumped = json.dumps(
        data,
        ensure_ascii=False,
    ).casefold()

    keywords = [
        "birth",
        "birthdate",
        "født",
        "fodt",
        "age",
        "alder",
        "rank",
        "ranking",
        "rating",
        "point",
        "playerid",
        "playernumber",
        "club",
        "gender",
    ]

    found = [
        keyword
        for keyword in keywords
        if keyword.casefold() in dumped
    ]

    print(found if found else "Ingen")


if __name__ == "__main__":
    main()
