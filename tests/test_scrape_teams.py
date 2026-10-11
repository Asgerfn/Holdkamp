import re
import sys

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait


# =========================================================
# UTF-8 I WINDOWS TERMINAL
# =========================================================

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8",
        errors="replace"
    )


# =========================================================
# SETTINGS
# =========================================================

CLUB_ID = 1148
CLUB_NAME = "Herlev/Hjorten"
SEASON_ID = 2026


params = [
    "6",
    str(SEASON_ID),
    "",
    "",
    "",
    "",
    "",
    str(CLUB_ID),
    ""
]


URL = (
    "https://www.badmintonplayer.dk/"
    "DBF/HoldTurnering/Stilling/#"
    + ",".join(params)
)


# =========================================================
# SHOWSTANDING ARGS
# =========================================================

def extract_showstanding_args(onclick):

    if not onclick:
        return None

    match = re.search(
        r"ShowStanding\((.*?)\)",
        onclick
    )

    if not match:
        return None

    return re.findall(
        r"'([^']*)'",
        match.group(1)
    )


# =========================================================
# FIND TEAM NAME
# =========================================================

def find_team_name(driver, link):

    text = driver.execute_script("""
        const link = arguments[0];
        const clubName = arguments[1];

        let element = link.parentElement;

        for (let i = 0; i < 8 && element; i++) {

            const text =
                (element.innerText || "")
                .replace(/\\s+/g, " ")
                .trim();

            if (
                text.includes(clubName) &&
                text.length < 500
            ) {
                return text;
            }

            element = element.parentElement;
        }

        return "";
    """, link, CLUB_NAME)


    text = " ".join(
        text.split()
    )


    pattern = (
        rf"{re.escape(CLUB_NAME)}"
        rf"(?:\s+\d+)?"
    )


    match = re.search(
        pattern,
        text
    )


    if match:
        return match.group(0)


    return ""


# =========================================================
# FIND SECTION HEADINGS ON PAGE
# =========================================================

def get_section_headings(driver):

    """
    Finder synlige overskrifter som:

    U11
    U13
    U15
    U17/U19
    SEN
    SEN+50
    MOT
    VET

    Vi gemmer deres y-position på siden.
    """

    headings = driver.execute_script("""
        const regex =
            /^(U\\d+(?:\\/U\\d+)?|SEN|SEN\\+50|MOT|VET)$/i;

        const elements =
            Array.from(
                document.querySelectorAll("body *")
            );

        const result = [];

        for (const el of elements) {

            if (el.offsetParent === null) {
                continue;
            }

            const text =
                (el.innerText || "")
                .replace(/\\s+/g, " ")
                .trim();

            if (!regex.test(text)) {
                continue;
            }

            // Undgå store parent-elementer,
            // hvor hele sektionen tilfældigvis matcher.
            const matchingChild =
                Array.from(el.children).some(child => {

                    const childText =
                        (child.innerText || "")
                        .replace(/\\s+/g, " ")
                        .trim();

                    return regex.test(childText);

                });

            if (matchingChild) {
                continue;
            }

            const rect =
                el.getBoundingClientRect();

            result.push({
                text: text,
                y: rect.top + window.scrollY
            });
        }

        return result;
    """)


    # Fjern dubletter
    cleaned = []

    seen = set()


    for heading in headings:

        key = (
            heading["text"].upper(),
            round(heading["y"])
        )

        if key in seen:
            continue

        seen.add(key)

        cleaned.append(
            heading
        )


    cleaned.sort(
        key=lambda x: x["y"]
    )


    return cleaned


# =========================================================
# FIND SECTION FOR LINK
# =========================================================

def find_section_for_link(
    driver,
    link,
    headings
):

    link_y = driver.execute_script("""
        const rect =
            arguments[0]
            .getBoundingClientRect();

        return rect.top + window.scrollY;
    """, link)


    previous_heading = None


    for heading in headings:

        if heading["y"] <= link_y:

            previous_heading = heading

        else:

            break


    if previous_heading:

        return previous_heading["text"].upper()


    return None


# =========================================================
# MAP SECTION
# =========================================================

def map_department(
    section,
    league_name
):

    """
    Returnerer:

    department
    sub_department

    Fx:

    U15
    ->
    U
    U15

    SEN
    ->
    SEN
    None

    SEN+50
    ->
    VET
    None
    """

    if section:

        section = section.upper()


        # ---------------------------------------------
        # YOUTH
        # ---------------------------------------------

        if re.fullmatch(
            r"U\d+(?:/U\d+)?",
            section
        ):

            return "U", section


        # ---------------------------------------------
        # SENIOR
        # ---------------------------------------------

        if section == "SEN":

            return "SEN", None


        # ---------------------------------------------
        # VETERAN
        # ---------------------------------------------

        if section in {
            "VET",
            "SEN+50"
        }:

            return "VET", None


        # ---------------------------------------------
        # MOTIONIST
        # ---------------------------------------------

        if section == "MOT":

            return "MOT", None


    # =================================================
    # FALLBACK
    # =================================================

    youth = re.search(
        r"\bU\d+(?:/U\d+)?\b",
        league_name.upper()
    )


    if youth:

        return (
            "U",
            youth.group(0)
        )


    if re.search(
        r"\bMOT\b",
        league_name,
        re.IGNORECASE
    ):

        return (
            "MOT",
            None
        )


    # Hvis vi ikke kan afgøre andet,
    # betragter vi rækken som SEN.
    return (
        "SEN",
        None
    )


# =========================================================
# START SELENIUM
# =========================================================

options = Options()

options.add_argument(
    "--start-maximized"
)


driver = webdriver.Chrome(
    options=options
)


try:

    print("\nÅbner:")
    print(URL)


    driver.get(URL)


    # =====================================================
    # WAIT
    # =====================================================

    wait = WebDriverWait(
        driver,
        20
    )


    wait.until(
        lambda d: len(
            d.find_elements(
                By.CSS_SELECTOR,
                "a[onclick*='ShowStanding']"
            )
        ) > 0
    )


    # =====================================================
    # FIND HEADINGS
    # =====================================================

    headings = get_section_headings(
        driver
    )


    print("\nSektioner fundet:")


    for heading in headings:

        print(
            f"  {heading['text']}"
        )


    # =====================================================
    # FIND LINKS
    # =====================================================

    raw_links = driver.find_elements(
        By.CSS_SELECTOR,
        "a[onclick*='ShowStanding']"
    )


    print(
        f"\nRå ShowStanding-links: {len(raw_links)}"
    )


    teams = []

    seen = set()


    # =====================================================
    # LOOP
    # =====================================================

    for link in raw_links:


        # ---------------------------------------------
        # KUN SYNLIGE LINKS
        # ---------------------------------------------

        if not link.is_displayed():
            continue


        league_name = " ".join(
            link.text.split()
        )


        if not league_name:
            continue


        onclick = link.get_attribute(
            "onclick"
        )


        args = extract_showstanding_args(
            onclick
        )


        if not args:
            continue


        if len(args) < 8:
            continue


        # ---------------------------------------------
        # RIGTIG SÆSON
        # ---------------------------------------------

        if args[1] != str(SEASON_ID):
            continue


        # ---------------------------------------------
        # RIGTIG KLUB
        # ---------------------------------------------

        if args[7] != str(CLUB_ID):
            continue


        # ---------------------------------------------
        # FJERN HJÆLPELINKS
        #
        # Fx:
        # "Indberettede spilletider..."
        # "Slutspilstider..."
        # ---------------------------------------------

        if re.search(
            r"indberettede spilletider|slutspilstider",
            league_name,
            re.IGNORECASE
        ):
            continue


        # ---------------------------------------------
        # KUN TURNERINGSRÆKKER
        #
        # Vi beholder:
        # Pulje
        # Finale
        # Kampen om ...
        # ---------------------------------------------

        if not re.search(
            r"\b(Pulje|Finale|Kampen om)\b",
            league_name,
            re.IGNORECASE
        ):
            continue


        # ---------------------------------------------
        # TEAM NAME
        # ---------------------------------------------

        team_name = find_team_name(
            driver,
            link
        )


        if not team_name:
            continue


        # ---------------------------------------------
        # SECTION
        # ---------------------------------------------

        section = find_section_for_link(
            driver,
            link,
            headings
        )


        department, sub_department = (
            map_department(
                section,
                league_name
            )
        )


        # ---------------------------------------------
        # IDS
        # ---------------------------------------------

        league_group_id = args[2]

        league_group_team_id = args[3]


        # ---------------------------------------------
        # DUPLICATES
        # ---------------------------------------------

        unique_key = (
            team_name,
            league_group_id,
            league_name
        )


        if unique_key in seen:
            continue


        seen.add(
            unique_key
        )


        # ---------------------------------------------
        # SAVE
        # ---------------------------------------------

        teams.append(
            {
                "department":
                    department,

                "sub_department":
                    sub_department,

                "section":
                    section,

                "team_name":
                    team_name,

                "league_name":
                    league_name,

                "season_id":
                    args[1],

                "league_group_id":
                    league_group_id,

                "league_group_team_id":
                    league_group_team_id,

                "club_id":
                    args[7]
            }
        )


    # =====================================================
    # SORT
    # =====================================================

    department_order = {
        "U": 1,
        "SEN": 2,
        "MOT": 3,
        "VET": 4
    }


    youth_order = {
        "U9": 1,
        "U11": 2,
        "U13": 3,
        "U15": 4,
        "U17/U19": 5
    }


    def sort_key(team):

        return (
            department_order.get(
                team["department"],
                99
            ),

            youth_order.get(
                team["sub_department"],
                99
            ),

            team["team_name"],

            team["league_name"]
        )


    teams.sort(
        key=sort_key
    )


    # =====================================================
    # PRINT RESULTS
    # =====================================================

    print("\n")
    print("=" * 110)
    print("HOLD FUND")
    print("=" * 110)


    current_department = None

    current_sub_department = None


    for team in teams:


        # =================================================
        # MAIN DEPARTMENT
        # =================================================

        if (
            team["department"]
            != current_department
        ):

            current_department = (
                team["department"]
            )

            current_sub_department = None


            print()
            print()
            print(
                "#" * 70
            )

            print(
                f"# {current_department}"
            )

            print(
                "#" * 70
            )


        # =================================================
        # YOUTH SUB DEPARTMENT
        # =================================================

        if (
            team["department"] == "U"
            and team["sub_department"]
            != current_sub_department
        ):

            current_sub_department = (
                team["sub_department"]
            )


            print()
            print(
                f"--- {current_sub_department} ---"
            )


        # =================================================
        # TEAM
        # =================================================

        print()

        print(
            f"Hold:       {team['team_name']}"
        )

        print(
            f"Afdeling:   {team['department']}"
        )

        print(
            f"Underafd.:  {team['sub_department']}"
        )

        print(
            f"Række:      {team['league_name']}"
        )

        print(
            f"Group ID:   {team['league_group_id']}"
        )

        print(
            f"Team ID:    {team['league_group_team_id']}"
        )

        print(
            f"Club ID:    {team['club_id']}"
        )


    # =====================================================
    # SUMMARY
    # =====================================================

    print("\n")
    print("=" * 110)
    print("SUMMARY")
    print("=" * 110)


    for department in [
        "U",
        "SEN",
        "MOT",
        "VET"
    ]:

        count = sum(
            1
            for team in teams
            if team["department"]
            == department
        )


        print(
            f"{department:<5}: {count}"
        )


    print(
        f"\nTOTAL: {len(teams)}"
    )


    input(
        "\nTryk ENTER for at lukke..."
    )


finally:

    driver.quit()