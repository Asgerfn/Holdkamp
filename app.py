import os

from functools import wraps
from players_database import sync_club_players
from threading import Thread
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    abort,
)

from active_team_sync import (
    sync_club_active_teams,
)
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user,
)


from werkzeug.security import (
    generate_password_hash,
    check_password_hash,
)


from database import get_connection


from badmintonplayer import (
    get_club_teams,
    create_session,
    get_callback_context,
)


from team_matches import (
    resolve_team_ids,
    get_team_matches,
)


from matches_data import (
    save_matches_to_azure,
)


# =========================================================
# APP
# =========================================================

app = Flask(__name__)


app.config["SECRET_KEY"] = os.getenv(
    "FLASK_SECRET_KEY",
    "dev-secret-key-change-before-production"
)


# BadmintonPlayer season
CURRENT_SEASON = 2026

# =========================================================
# BACKGROUND PLAYER SYNC
# =========================================================

def sync_club_players_background(
    club_id,
    season_id,
):
    """
    Henter alle spillere for klubben fra BadmintonPlayer
    og gemmer/opdaterer dem i Azure.

    Køres efter oprettelse af den første bruger/admin
    i en klub.
    """

    try:

        print()
        print("=" * 100)
        print("BACKGROUND PLAYER SYNC")
        print("=" * 100)

        print(
            "Club ID:",
            club_id
        )

        print(
            "Season:",
            season_id
        )


        players = sync_club_players(
            club_id=club_id,
            season_id=season_id,
            ranking_list_id=287,
        )


        print()
        print(
            f"BACKGROUND PLAYER SYNC FÆRDIG: "
            f"{len(players)} spillere"
        )


    except Exception as e:

        # VIGTIGT:
        # Registreringen må ikke fejle bare fordi
        # BadmintonPlayer midlertidigt er nede.
        print()
        print(
            "FEJL I BACKGROUND PLAYER SYNC:"
        )

        print(e)


def start_club_player_sync(
    club_id,
    season_id,
):

    thread = Thread(
        target=sync_club_players_background,
        args=(
            club_id,
            season_id,
        ),
        daemon=True,
    )

    thread.start()
# =========================================================
# FLASK LOGIN
# =========================================================

login_manager = LoginManager()

login_manager.init_app(app)

login_manager.login_view = "login"

login_manager.login_message = (
    "Log ind for at fortsætte."
)


# =========================================================
# USER MODEL
# =========================================================

class User(UserMixin):

    def __init__(
        self,
        user_id,
        email,
        display_name,
        club_id,
        club_role,
    ):

        self.id = str(user_id)

        self.email = email

        self.display_name = display_name

        self.club_id = club_id

        self.club_role = club_role


    @property
    def is_club_admin(self):

        return self.club_role == "admin"


# =========================================================
# GET USER
# =========================================================

def get_user_by_id(user_id):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT

                user_id,
                email,
                display_name,
                club_id,
                club_role

            FROM dbo.users

            WHERE user_id = ?
            """,

            user_id
        )


        row = cursor.fetchone()


        if row is None:

            return None


        return User(

            user_id=row.user_id,

            email=row.email,

            display_name=row.display_name,

            club_id=row.club_id,

            club_role=row.club_role,
        )


    finally:

        cursor.close()
        conn.close()


# =========================================================
# USER LOADER
# =========================================================

@login_manager.user_loader
def load_user(user_id):

    return get_user_by_id(
        user_id
    )


# =========================================================
# ADMIN DECORATOR
# =========================================================

def admin_required(view_function):

    @wraps(view_function)
    def wrapped_view(*args, **kwargs):

        if not current_user.is_authenticated:

            return login_manager.unauthorized()


        if current_user.club_role != "admin":

            abort(403)


        return view_function(
            *args,
            **kwargs
        )


    return wrapped_view


# =========================================================
# DASHBOARD TEAMS TABLE
# =========================================================
def ensure_dashboard_teams_table():

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # =================================================
        # 1. CREATE TABLE IF IT DOES NOT EXIST
        # =================================================

        cursor.execute(
            """
            IF OBJECT_ID(
                N'dbo.club_dashboard_teams',
                N'U'
            ) IS NULL
            BEGIN

                CREATE TABLE dbo.club_dashboard_teams (

                    id INT IDENTITY(1,1)
                        PRIMARY KEY,

                    club_id INT NOT NULL,

                    season_id INT NOT NULL,

                    department NVARCHAR(20)
                        NOT NULL,

                    sub_department NVARCHAR(30)
                        NULL,

                    team_name NVARCHAR(255)
                        NOT NULL,

                    league_name NVARCHAR(500)
                        NOT NULL,

                    league_group_id INT
                        NOT NULL,

                    age_group_id INT
                        NULL,

                    region_id INT
                        NULL,

                    league_group_team_id INT
                        NULL,

                    is_active BIT NOT NULL
                        CONSTRAINT DF_dashboard_team_active
                        DEFAULT 0,

                    updated_at DATETIME2 NOT NULL
                        CONSTRAINT DF_dashboard_team_updated
                        DEFAULT SYSUTCDATETIME(),

                    CONSTRAINT UQ_dashboard_team_v2
                    UNIQUE (
                        club_id,
                        season_id,
                        league_group_id,
                        team_name
                    ),

                    CONSTRAINT FK_dashboard_team_club
                    FOREIGN KEY (club_id)
                    REFERENCES dbo.badminton_clubs(club_id)

                );

            END
            """
        )

        conn.commit()


        # =================================================
        # 2. CHECK AGE_GROUP_ID
        # =================================================

        cursor.execute(
            """
            SELECT COL_LENGTH(
                'dbo.club_dashboard_teams',
                'age_group_id'
            )
            """
        )

        age_group_exists = (
            cursor.fetchone()[0]
            is not None
        )


        # =================================================
        # 3. ADD AGE_GROUP_ID IF MISSING
        # =================================================

        if not age_group_exists:

            print(
                "Tilføjer age_group_id "
                "til club_dashboard_teams..."
            )

            cursor.execute(
                """
                ALTER TABLE dbo.club_dashboard_teams
                ADD age_group_id INT NULL
                """
            )

            conn.commit()


            # ---------------------------------------------
            # IMPORTANT
            #
            # Den gamle kolonne
            # league_group_team_id indeholdt reelt
            # age_group_id fra vores gamle parser.
            # ---------------------------------------------

            cursor.execute(
                """
                UPDATE dbo.club_dashboard_teams

                SET age_group_id =
                    league_group_team_id
                """
            )

            conn.commit()


            # ---------------------------------------------
            # Clear wrong old values
            # ---------------------------------------------

            cursor.execute(
                """
                UPDATE dbo.club_dashboard_teams

                SET league_group_team_id =
                    NULL
                """
            )

            conn.commit()


        # =================================================
        # 4. CHECK REGION_ID
        # =================================================

        cursor.execute(
            """
            SELECT COL_LENGTH(
                'dbo.club_dashboard_teams',
                'region_id'
            )
            """
        )

        region_exists = (
            cursor.fetchone()[0]
            is not None
        )


        # =================================================
        # 5. ADD REGION_ID IF MISSING
        # =================================================

        if not region_exists:

            print(
                "Tilføjer region_id "
                "til club_dashboard_teams..."
            )

            cursor.execute(
                """
                ALTER TABLE dbo.club_dashboard_teams
                ADD region_id INT NULL
                """
            )

            conn.commit()


        # =================================================
        # 6. REMOVE OLD UNIQUE CONSTRAINT
        # =================================================

        cursor.execute(
            """
            SELECT COUNT(*)

            FROM sys.key_constraints

            WHERE
                name = 'UQ_dashboard_team'

                AND parent_object_id =
                    OBJECT_ID(
                        'dbo.club_dashboard_teams'
                    )
            """
        )


        old_constraint_exists = (
            cursor.fetchone()[0] > 0
        )


        if old_constraint_exists:

            print(
                "Fjerner gammel "
                "UQ_dashboard_team constraint..."
            )

            cursor.execute(
                """
                ALTER TABLE dbo.club_dashboard_teams

                DROP CONSTRAINT
                    UQ_dashboard_team
                """
            )

            conn.commit()


        # =================================================
        # 7. ADD NEW UNIQUE CONSTRAINT
        # =================================================

        cursor.execute(
            """
            SELECT COUNT(*)

            FROM sys.key_constraints

            WHERE
                name = 'UQ_dashboard_team_v2'

                AND parent_object_id =
                    OBJECT_ID(
                        'dbo.club_dashboard_teams'
                    )
            """
        )


        new_constraint_exists = (
            cursor.fetchone()[0] > 0
        )


        if not new_constraint_exists:

            print(
                "Tilføjer ny "
                "UQ_dashboard_team_v2 constraint..."
            )

            cursor.execute(
                """
                ALTER TABLE dbo.club_dashboard_teams

                ADD CONSTRAINT UQ_dashboard_team_v2

                UNIQUE (
                    club_id,
                    season_id,
                    league_group_id,
                    team_name
                )
                """
            )

            conn.commit()


    except Exception:

        conn.rollback()
        raise


    finally:

        cursor.close()
        conn.close()

# =========================================================
# LOGIN
# =========================================================
# =========================================================
# PLAYERS
# =========================================================

# =========================================================
# PLAYERS
# =========================================================

@app.route("/players")
@login_required
def players():

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # =================================================
        # CLUB
        # =================================================

        cursor.execute(
            """
            SELECT
                club_id,
                club_name

            FROM dbo.badminton_clubs

            WHERE club_id = ?
            """,

            current_user.club_id
        )

        club_row = cursor.fetchone()


        # =================================================
        # PLAYERS + FANTASY POINTS
        # =================================================

        cursor.execute(
            """
            SELECT

                p.badminton_id,
                p.player_name,

                cp.is_active,

                r.ranking_position,
                r.national_position,
                r.ranking_class,
                r.points_raw AS ranking_points,

                COALESCE(
                    fp.fantasy_points,
                    0
                ) AS fantasy_points

            FROM dbo.club_players cp


            INNER JOIN dbo.badminton_players p

                ON p.badminton_id =
                    cp.badminton_id


            LEFT JOIN dbo.player_rankings r

                ON r.badminton_id =
                    cp.badminton_id

                AND r.club_id =
                    cp.club_id

                AND r.season_id =
                    cp.season_id


            LEFT JOIN (

                SELECT
                    badminton_id,
                    club_id,
                    season_id,
                    SUM(points) AS fantasy_points

                FROM dbo.fantasy_point_events

                WHERE
                    badminton_id IS NOT NULL

                GROUP BY
                    badminton_id,
                    club_id,
                    season_id

            ) fp

                ON fp.badminton_id =
                    cp.badminton_id

                AND fp.club_id =
                    cp.club_id

                AND fp.season_id =
                    cp.season_id


            WHERE

                cp.club_id = ?

                AND cp.season_id = ?

                AND cp.is_active = 1


            ORDER BY

                COALESCE(
                    fp.fantasy_points,
                    0
                ) DESC,

                CASE
                    WHEN r.national_position IS NULL
                    THEN 999999
                    ELSE r.national_position
                END ASC,

                p.player_name ASC
            """,

            current_user.club_id,
            CURRENT_SEASON
        )

        player_rows = cursor.fetchall()


    finally:

        cursor.close()
        conn.close()


    # =====================================================
    # CLUB
    # =====================================================

    club = None


    if club_row is not None:

        club = {
            "id":
                club_row.club_id,

            "name":
                club_row.club_name
        }


    # =====================================================
    # PLAYERS
    # =====================================================

    players = [

        {
            "badminton_id":
                row.badminton_id,

            "player_name":
                row.player_name,

            "ranking_position":
                row.ranking_position,

            "national_position":
                row.national_position,

            "ranking_class":
                row.ranking_class,

            "ranking_points":
                row.ranking_points,

            "points":
                row.fantasy_points,
        }

        for row in player_rows
    ]


    return render_template(
        "players.html",

        club=club,

        players=players,

        player_count=len(players),

        current_season=CURRENT_SEASON
    )

@app.route(
    "/",
    methods=["GET", "POST"]
)

# =========================================================
# ADMIN - MANUAL RESULT SYNC
# =========================================================

@app.route(
    "/admin/results/refresh",
    methods=["POST"]
)
@login_required
@admin_required
def refresh_match_results():

    try:

        result = (
            sync_club_active_teams(
                club_id=
                    current_user.club_id,

                season_id=
                    CURRENT_SEASON,
            )
        )


        flash(
            f"Kampdata opdateret. "
            f"{result['active_teams']} hold, "
            f"{result['matches']} holdkampe og "
            f"{result['games']} delkampe.",
            "success"
        )


    except Exception as e:

        print()
        print(
            "FEJL VED MANUEL RESULT SYNC:"
        )

        print(e)


        flash(
            "Kampdata kunne ikke opdateres.",
            "error"
        )


    return redirect(
        url_for(
            "admin_dashboard"
        )
    )

@app.route(
    "/admin/players/refresh",
    methods=["POST"]
)
@login_required
def refresh_players():

    if current_user.club_role != "admin":
        abort(403)

    players = sync_club_players(
        club_id=current_user.club_id,
        season_id=CURRENT_SEASON,
        ranking_list_id=287,
    )

    flash(
        f"{len(players)} spillere blev hentet/opdateret.",
        "success"
    )

    return redirect(
        url_for("players")
    )

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if current_user.is_authenticated:

        return redirect(
            url_for("dashboard")
        )


    if request.method == "POST":

        email = (
            request.form
            .get("email", "")
            .strip()
            .lower()
        )


        password = request.form.get(
            "password",
            ""
        )


        if not email or not password:

            flash(
                "Indtast både email og password.",
                "error"
            )

            return render_template(
                "login.html"
            )


        conn = get_connection()
        cursor = conn.cursor()


        try:

            cursor.execute(
                """
                SELECT

                    user_id,
                    email,
                    password_hash,
                    display_name,
                    club_id,
                    club_role

                FROM dbo.users

                WHERE LOWER(email) = ?
                """,

                email
            )


            row = cursor.fetchone()


        finally:

            cursor.close()
            conn.close()


        if (
            row is None

            or not check_password_hash(
                row.password_hash,
                password
            )
        ):

            flash(
                "Forkert email eller password.",
                "error"
            )

            return render_template(
                "login.html"
            )


        user = User(

            user_id=row.user_id,

            email=row.email,

            display_name=row.display_name,

            club_id=row.club_id,

            club_role=row.club_role,
        )


        login_user(
            user,
            remember=True
        )


        return redirect(
            url_for("dashboard")
        )


    return render_template(
        "login.html"
    )


# =========================================================
# REGISTER
# =========================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if current_user.is_authenticated:

        return redirect(
            url_for("dashboard")
        )


    if request.method == "POST":

        display_name = (
            request.form
            .get("display_name", "")
            .strip()
        )


        email = (
            request.form
            .get("email", "")
            .strip()
            .lower()
        )


        password = request.form.get(
            "password",
            ""
        )


        password_confirm = request.form.get(
            "password_confirm",
            ""
        )


        club_id_raw = (
            request.form
            .get("club_id", "")
            .strip()
        )


        # =================================================
        # VALIDATION
        # =================================================

        if len(display_name) < 2:

            flash(
                "Indtast dit navn.",
                "error"
            )

            return render_template(
                "register.html"
            )


        if "@" not in email:

            flash(
                "Indtast en gyldig email.",
                "error"
            )

            return render_template(
                "register.html"
            )


        if len(password) < 8:

            flash(
                "Password skal være mindst 8 tegn.",
                "error"
            )

            return render_template(
                "register.html"
            )


        if password != password_confirm:

            flash(
                "De to passwords er ikke ens.",
                "error"
            )

            return render_template(
                "register.html"
            )


        try:

            club_id = int(
                club_id_raw
            )

        except ValueError:

            flash(
                "Vælg en klub fra listen.",
                "error"
            )

            return render_template(
                "register.html"
            )


        # =================================================
        # DATABASE
        # =================================================

        conn = get_connection()
        cursor = conn.cursor()


        try:

            # ---------------------------------------------
            # Validate club
            # ---------------------------------------------

            cursor.execute(
                """
                SELECT

                    club_id,
                    club_name

                FROM dbo.badminton_clubs

                WHERE
                    club_id = ?
                    AND club_id > 0
                """,

                club_id
            )


            club = cursor.fetchone()


            if club is None:

                flash(
                    "Den valgte klub findes ikke.",
                    "error"
                )

                return render_template(
                    "register.html"
                )


            # ---------------------------------------------
            # Existing email
            # ---------------------------------------------

            cursor.execute(
                """
                SELECT
                    user_id

                FROM dbo.users

                WHERE LOWER(email) = ?
                """,

                email
            )


            existing_user = (
                cursor.fetchone()
            )


            if existing_user is not None:

                flash(
                    "Der findes allerede en profil "
                    "med denne email.",
                    "error"
                )

                return render_template(
                    "register.html"
                )


            # ---------------------------------------------
            # First club user = admin
            # ---------------------------------------------

            cursor.execute(
                """
                SELECT COUNT(*)

                FROM dbo.users
                    WITH (UPDLOCK, HOLDLOCK)

                WHERE club_id = ?
                """,

                club_id
            )


            club_user_count = (
                cursor.fetchone()[0]
            )


            if club_user_count == 0:

                club_role = "admin"

            else:

                club_role = "member"


            # ---------------------------------------------
            # Password
            # ---------------------------------------------

            password_hash = (
                generate_password_hash(
                    password
                )
            )


            # ---------------------------------------------
            # Insert
            # ---------------------------------------------

            cursor.execute(
                """
                INSERT INTO dbo.users (

                    email,
                    password_hash,
                    display_name,
                    club_id,
                    club_role

                )

                OUTPUT
                    INSERTED.user_id

                VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?
                )
                """,

                email,
                password_hash,
                display_name,
                club_id,
                club_role
            )


            new_user_id = (
                cursor.fetchone()[0]
            )


            conn.commit()


        except Exception:

            conn.rollback()

            raise


        finally:

            cursor.close()
            conn.close()


        # =================================================
        # AUTO LOGIN
        # =================================================

        user = User(

            user_id=new_user_id,

            email=email,

            display_name=display_name,

            club_id=club_id,

            club_role=club_role,
        )


        login_user(
            user,
            remember=True
        )


        if club_role == "admin":
            start_club_player_sync(
                club_id=club_id,
                season_id=CURRENT_SEASON,
            )
            flash(
                f"Velkommen, {display_name}! "
                "Du er den første bruger i klubben "
                "og er derfor blevet administrator.",
                "success"
            )

        else:

            flash(
                f"Velkommen, {display_name}!",
                "success"
            )


        return redirect(
            url_for("dashboard")
        )


    return render_template(
        "register.html"
    )


# =========================================================
# ADMIN - TEAM BUILDER RULES
# =========================================================

@app.route(
    "/admin/team-builder",
    methods=["GET", "POST"]
)
@login_required
@admin_required
def admin_team_builder():

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # =================================================
        # CLUB
        # =================================================

        cursor.execute(
            """
            SELECT
                club_id,
                club_name

            FROM dbo.badminton_clubs

            WHERE club_id = ?
            """,
            current_user.club_id
        )

        club_row = cursor.fetchone()

        if club_row is None:
            abort(404)


        # =================================================
        # SAVE RULES
        # =================================================

        if request.method == "POST":

            try:

                male_players = int(
                    request.form.get(
                        "male_players",
                        0
                    )
                )

                female_players = int(
                    request.form.get(
                        "female_players",
                        0
                    )
                )

                max_substitutions = int(
                    request.form.get(
                        "max_substitutions",
                        0
                    )
                )

            except (
                TypeError,
                ValueError
            ):

                flash(
                    "Alle værdier skal være hele tal.",
                    "error"
                )

                return redirect(
                    url_for(
                        "admin_team_builder"
                    )
                )


            # =============================================
            # VALIDATION
            # =============================================

            if male_players < 0:

                flash(
                    "Antal herrer kan ikke være negativt.",
                    "error"
                )

                return redirect(
                    url_for(
                        "admin_team_builder"
                    )
                )


            if female_players < 0:

                flash(
                    "Antal damer kan ikke være negativt.",
                    "error"
                )

                return redirect(
                    url_for(
                        "admin_team_builder"
                    )
                )


            if (
                male_players
                +
                female_players
                == 0
            ):

                flash(
                    "Et hold skal indeholde mindst én spiller.",
                    "error"
                )

                return redirect(
                    url_for(
                        "admin_team_builder"
                    )
                )


            if max_substitutions < 0:

                flash(
                    "Antal udskiftninger kan ikke være negativt.",
                    "error"
                )

                return redirect(
                    url_for(
                        "admin_team_builder"
                    )
                )


            # =============================================
            # UPSERT RULES
            # =============================================

            cursor.execute(
                """
                MERGE dbo.fantasy_team_rules AS target

                USING (
                    SELECT
                        ? AS club_id,
                        ? AS season_id
                ) AS source

                ON
                    target.club_id =
                        source.club_id

                    AND target.season_id =
                        source.season_id


                WHEN MATCHED THEN

                    UPDATE SET

                        male_players = ?,
                        female_players = ?,

                        captain_count = 1,

                        max_substitutions = ?,

                        captain_multiplier = 2.00,

                        updated_at =
                            SYSUTCDATETIME()


                WHEN NOT MATCHED THEN

                    INSERT (
                        club_id,
                        season_id,

                        male_players,
                        female_players,

                        captain_count,
                        max_substitutions,
                        captain_multiplier
                    )

                    VALUES (
                        source.club_id,
                        source.season_id,

                        ?,
                        ?,

                        1,
                        ?,
                        2.00
                    );
                """,

                current_user.club_id,
                CURRENT_SEASON,

                male_players,
                female_players,
                max_substitutions,

                male_players,
                female_players,
                max_substitutions,
            )

            conn.commit()


            flash(
                "Holdreglerne er gemt.",
                "success"
            )

            return redirect(
                url_for(
                    "admin_team_builder"
                )
            )


        # =================================================
        # LOAD RULES
        # =================================================

        cursor.execute(
            """
            SELECT
                male_players,
                female_players,
                captain_count,
                max_substitutions,
                captain_multiplier

            FROM dbo.fantasy_team_rules

            WHERE
                club_id = ?
                AND season_id = ?
            """,

            current_user.club_id,
            CURRENT_SEASON
        )

        rules_row = cursor.fetchone()


    finally:

        cursor.close()
        conn.close()


    # =====================================================
    # CLUB
    # =====================================================

    club = {
        "id":
            club_row.club_id,

        "name":
            club_row.club_name,
    }


    # =====================================================
    # DEFAULT RULES
    # =====================================================

    if rules_row is None:

        rules = {
            "male_players": 6,
            "female_players": 4,
            "captain_count": 1,
            "max_substitutions": 3,
            "captain_multiplier": 2,
        }

    else:

        rules = {
            "male_players":
                rules_row.male_players,

            "female_players":
                rules_row.female_players,

            "captain_count":
                rules_row.captain_count,

            "max_substitutions":
                rules_row.max_substitutions,

            "captain_multiplier":
                rules_row.captain_multiplier,
        }


    return render_template(
        "admin_team_builder.html",

        club=club,
        rules=rules,
        current_season=CURRENT_SEASON,
    )

# =========================================================
# CLUB AUTOCOMPLETE
# =========================================================

# =========================================================
# FANTASY - PLAYER GENDER
# =========================================================

def get_fantasy_player_gender(
    ranking_class
):

    if not ranking_class:
        return None

    value = (
        str(ranking_class)
        .strip()
        .upper()
    )


    # Eksempler:
    # SEN M
    # SEN K
    # M
    # K

    parts = value.split()

    if not parts:
        return None


    last_part = parts[-1]


    if last_part == "M":
        return "male"


    if last_part == "K":
        return "female"


    return None


# =========================================================
# MY TEAM
# =========================================================

@app.route(
    "/my-team",
    methods=["GET", "POST"]
)
@login_required
def my_team():



    conn = get_connection()

    cursor = conn.cursor()



    try:



        # =================================================

        # CLUB

        # =================================================



        cursor.execute(

            """

            SELECT

                club_id,

                club_name



            FROM dbo.badminton_clubs



            WHERE club_id = ?

            """,

            current_user.club_id

        )



        club_row = cursor.fetchone()





        if club_row is None:

            abort(404)





        club = {

            "id":

                club_row.club_id,



            "name":

                club_row.club_name,

        }





        # =================================================

        # RULES

        # =================================================



        cursor.execute(

            """

            SELECT

                male_players,

                female_players,

                captain_count,

                max_substitutions,

                captain_multiplier



            FROM dbo.fantasy_team_rules



            WHERE

                club_id = ?

                AND season_id = ?

            """,

            current_user.club_id,

            CURRENT_SEASON

        )



        rules_row = cursor.fetchone()





        # =================================================

        # NO RULES YET

        # =================================================



        if rules_row is None:



            return render_template(

                "my_team.html",



                club=club,



                rules=None,



                team=None,



                players=[],



                selected_players=[],



                substitutions_used=0,



                current_season=

                    CURRENT_SEASON,

            )





        rules = {

            "male_players":

                int(

                    rules_row.male_players

                ),



            "female_players":

                int(

                    rules_row.female_players

                ),



            "captain_count":

                int(

                    rules_row.captain_count

                ),



            "max_substitutions":

                int(

                    rules_row.max_substitutions

                ),



            "captain_multiplier":

                float(

                    rules_row.captain_multiplier

                ),

        }





        # =================================================

        # ALL ACTIVE CLUB PLAYERS

        # =================================================



        cursor.execute(

            """

            SELECT

                p.badminton_id,

                p.player_name,

                p.gender,



                r.ranking_position,

                r.national_position,

                r.ranking_class,



                COALESCE(

                    fp.fantasy_points,

                    0

                ) AS fantasy_points



            FROM dbo.club_players cp



            INNER JOIN dbo.badminton_players p

                ON p.badminton_id =

                    cp.badminton_id



            OUTER APPLY (

                SELECT TOP 1

                    pr.ranking_position,

                    pr.national_position,

                    pr.ranking_class



                FROM dbo.player_rankings pr



                WHERE

                    pr.badminton_id =

                        cp.badminton_id



                    AND pr.club_id =

                        cp.club_id



                    AND pr.season_id     =

                        cp.season_id



                ORDER BY

                    pr.id DESC



            ) r



            LEFT JOIN (

                SELECT

                    badminton_id,

                    club_id,

                    season_id,



                    SUM(points)

                        AS fantasy_points



                FROM dbo.fantasy_point_events



                WHERE

                    badminton_id IS NOT NULL



                GROUP BY

                    badminton_id,

                    club_id,

                    season_id



            ) fp

                ON fp.badminton_id =

                    cp.badminton_id



                AND fp.club_id =

                    cp.club_id



                AND fp.season_id =

                    cp.season_id



            WHERE

                cp.club_id = ?



                AND cp.season_id = ?



                AND cp.is_active = 1



                AND p.gender IN (

                    'M',

                    'K'

                )



            ORDER BY



                CASE

                    WHEN p.gender = 'M'

                    THEN 0

                    ELSE 1

                END,



                CASE

                    WHEN r.national_position

                        IS NULL

                    THEN 999999



                    ELSE

                        r.national_position

                END,



                p.player_name

            """,

            current_user.club_id,

            CURRENT_SEASON

        )



        player_rows = (

            cursor.fetchall()

        )





        players = []



        player_lookup = {}





        for row in player_rows:



            player = {

                "badminton_id":

                    row.badminton_id,



                "player_name":

                    row.player_name,



                "gender":

                    row.gender,



                "ranking_position":

                    row.ranking_position,



                "national_position":

                    row.national_position,



                "ranking_class":

                    row.ranking_class,



                "fantasy_points":

                    row.fantasy_points,

            }





            players.append(

                player

            )





            player_lookup[

                row.badminton_id

            ] = player





        # =================================================

        # CURRENT USER TEAM

        # =================================================



        cursor.execute(

            """

            SELECT

                id,

                team_name,

                status,

                activated_at,

                created_at,

                updated_at



            FROM dbo.fantasy_teams



            WHERE

                user_id = ?



                AND club_id = ?



                AND season_id = ?

            """,

            int(

                current_user.id

            ),



            current_user.club_id,



            CURRENT_SEASON

        )



        team_row = (

            cursor.fetchone()

        )





        team = None





        if team_row is not None:



            team = {

                "id":

                    team_row.id,



                "team_name":

                    team_row.team_name,



                "status":

                    team_row.status,



                "activated_at":

                    team_row.activated_at,



                "created_at":

                    team_row.created_at,



                "updated_at":

                    team_row.updated_at,

            }





        # =================================================

        # HANDLE POST

        # =================================================



        if request.method == "POST":

            action = (
                request.form
                .get(
                    "action",
                    "save"
                )
                .strip()
                .lower()
            )


            if action not in {
                "save",
                "activate",
                "substitute",
            }:

                action = "save"


            # =====================================================
            # SUBSTITUTION
            # =====================================================

            if action == "substitute":

                # -------------------------------------------------
                # TEAM MUST BE ACTIVE
                # -------------------------------------------------

                if (
                    team is None
                    or
                    team["status"] != "active"
                ):

                    flash(
                        "Udskiftninger kan kun laves "
                        "på et aktivt hold.",
                        "error"
                    )

                    return redirect(
                        url_for(
                            "my_team"
                        )
                    )


                # -------------------------------------------------
                # CHECK NUMBER OF SUBSTITUTIONS
                # -------------------------------------------------

                cursor.execute(
                    """
                    SELECT COUNT(*)

                    FROM dbo.fantasy_team_substitutions

                    WHERE
                        fantasy_team_id = ?
                    """,
                    team["id"]
                )


                substitutions_used_now = (
                    cursor.fetchone()[0]
                )


                if (
                    substitutions_used_now
                    >=
                    rules["max_substitutions"]
                ):

                    flash(
                        "Du har allerede brugt alle "
                        f"{rules['max_substitutions']} "
                        "udskiftninger.",
                        "error"
                    )

                    return redirect(
                        url_for(
                            "my_team"
                        )
                    )


                # -------------------------------------------------
                # FORM VALUES
                # -------------------------------------------------

                player_out_id = (
                    request.form
                    .get(
                        "player_out",
                        ""
                    )
                    .strip()
                )


                player_in_id = (
                    request.form
                    .get(
                        "player_in",
                        ""
                    )
                    .strip()
                )


                if (
                    not player_out_id
                    or
                    not player_in_id
                ):

                    flash(
                        "Du skal vælge både en spiller "
                        "ud og en spiller ind.",
                        "error"
                    )

                    return redirect(
                        url_for(
                            "my_team"
                        )
                    )


                if (
                    player_out_id
                    ==
                    player_in_id
                ):

                    flash(
                        "Du kan ikke skifte en spiller "
                        "med sig selv.",
                        "error"
                    )

                    return redirect(
                        url_for(
                            "my_team"
                        )
                    )


                # -------------------------------------------------
                # FIND CURRENT OUTGOING PLAYER
                # -------------------------------------------------

                cursor.execute(
                    """
                    SELECT TOP 1
                        ftp.id,
                        ftp.badminton_id,
                        ftp.is_captain,

                        p.player_name,
                        p.gender

                    FROM dbo.fantasy_team_players ftp

                    INNER JOIN dbo.badminton_players p
                        ON p.badminton_id =
                            ftp.badminton_id

                    WHERE
                        ftp.fantasy_team_id = ?

                        AND ftp.badminton_id = ?

                        AND ftp.active_to IS NULL
                    """,
                    team["id"],
                    player_out_id
                )


                outgoing_row = (
                    cursor.fetchone()
                )


                if outgoing_row is None:

                    flash(
                        "Spilleren du prøver at skifte ud "
                        "er ikke på dit nuværende hold.",
                        "error"
                    )

                    return redirect(
                        url_for(
                            "my_team"
                        )
                    )


                # -------------------------------------------------
                # FIND INCOMING PLAYER
                # -------------------------------------------------

                incoming_player = (
                    player_lookup.get(
                        player_in_id
                    )
                )


                if incoming_player is None:

                    flash(
                        "Den nye spiller kan ikke vælges "
                        "til dette hold.",
                        "error"
                    )

                    return redirect(
                        url_for(
                            "my_team"
                        )
                    )


                # -------------------------------------------------
                # SAME GENDER
                # -------------------------------------------------

                if (
                    outgoing_row.gender
                    !=
                    incoming_player["gender"]
                ):

                    flash(
                        "En herrespiller skal erstattes "
                        "af en herrespiller, og en dame "
                        "af en dame.",
                        "error"
                    )

                    return redirect(
                        url_for(
                            "my_team"
                        )
                    )


                # -------------------------------------------------
                # INCOMING PLAYER MAY NOT ALREADY BE ACTIVE
                # -------------------------------------------------

                cursor.execute(
                    """
                    SELECT COUNT(*)

                    FROM dbo.fantasy_team_players

                    WHERE
                        fantasy_team_id = ?

                        AND badminton_id = ?

                        AND active_to IS NULL
                    """,
                    team["id"],
                    player_in_id
                )


                already_on_team = (
                    cursor.fetchone()[0]
                    >
                    0
                )


                if already_on_team:

                    flash(
                        "Den spiller er allerede på dit hold.",
                        "error"
                    )

                    return redirect(
                        url_for(
                            "my_team"
                        )
                    )


                # -------------------------------------------------
                # ONE SHARED TIMESTAMP
                # -------------------------------------------------

                cursor.execute(
                    """
                    SELECT SYSUTCDATETIME()
                    """
                )


                effective_at = (
                    cursor.fetchone()[0]
                )


                # -------------------------------------------------
                # CREATE SUBSTITUTION EVENT
                # -------------------------------------------------

                cursor.execute(
                    """
                    INSERT INTO
                        dbo.fantasy_team_substitutions
                    (
                        fantasy_team_id,
                        player_out_badminton_id,
                        player_in_badminton_id,
                        effective_at
                    )

                    OUTPUT INSERTED.id

                    VALUES (
                        ?,
                        ?,
                        ?,
                        ?
                    )
                    """,
                    team["id"],
                    player_out_id,
                    player_in_id,
                    effective_at
                )


                substitution_id = (
                    cursor.fetchone()[0]
                )


                # -------------------------------------------------
                # CLOSE OLD PLAYER PERIOD
                # -------------------------------------------------

                cursor.execute(
                    """
                    UPDATE dbo.fantasy_team_players

                    SET
                        active_to = ?,

                        updated_at =
                            SYSUTCDATETIME()

                    WHERE
                        id = ?

                        AND active_to IS NULL
                    """,
                    effective_at,
                    outgoing_row.id
                )


                # -------------------------------------------------
                # ADD NEW PLAYER
                #
                # If outgoing player was captain,
                # incoming player becomes captain.
                # -------------------------------------------------

                cursor.execute(
                    """
                    INSERT INTO
                        dbo.fantasy_team_players
                    (
                        fantasy_team_id,
                        badminton_id,
                        is_captain,
                        active_from,
                        active_to,
                        selection_type,
                        substitution_id
                    )

                    VALUES (
                        ?,
                        ?,
                        ?,
                        ?,
                        NULL,
                        'substitution',
                        ?
                    )
                    """,

                    team["id"],

                    player_in_id,

                    1
                    if outgoing_row.is_captain
                    else 0,

                    effective_at,

                    substitution_id
                )


                # -------------------------------------------------
                # TOUCH TEAM
                # -------------------------------------------------

                cursor.execute(
                    """
                    UPDATE dbo.fantasy_teams

                    SET
                        updated_at =
                            SYSUTCDATETIME()

                    WHERE
                        id = ?
                    """,
                    team["id"]
                )


                conn.commit()


                flash(
                    f"{outgoing_row.player_name} er skiftet ud "
                    f"med {incoming_player['player_name']}. "
                    f"Du har nu brugt "
                    f"{substitutions_used_now + 1} af "
                    f"{rules['max_substitutions']} udskiftninger.",
                    "success"
                )


                return redirect(
                    url_for(
                        "my_team"
                    )
                )


            # =====================================================
            # ACTIVE TEAM CANNOT BE EDITED AS DRAFT
            # =====================================================

            if (
                team is not None
                and
                team["status"] == "active"
            ):

                flash(
                    "Holdet er allerede aktiveret. "
                    "Ændringer skal laves som udskiftninger.",
                    "error"
                )

                return redirect(
                    url_for(
                        "my_team"
                    )
                )


            # =============================================

            # TEAM NAME

            # =============================================



            team_name = (

                request.form

                .get(

                    "team_name",

                    ""

                )

                .strip()

            )





            if not team_name:



                flash(

                    "Du skal give holdet et navn.",

                    "error"

                )



                return redirect(

                    url_for(

                        "my_team"

                    )

                )





            if len(team_name) > 100:



                flash(

                    "Holdnavnet må maksimalt "

                    "være 100 tegn.",

                    "error"

                )



                return redirect(

                    url_for(

                        "my_team"

                    )

                )





            # =============================================

            # SELECTED PLAYERS

            # =============================================



            selected_ids = (

                request.form.getlist(

                    "selected_players"

                )

            )





            # Fjern eventuelle duplicates,

            # men behold rækkefølgen.



            selected_ids = list(

                dict.fromkeys(

                    selected_ids

                )

            )





            captain_id = (

                request.form

                .get(

                    "captain_id",

                    ""

                )

                .strip()

            )





            # =============================================

            # VALIDATE PLAYERS

            # =============================================



            chosen_players = []





            for badminton_id in selected_ids:



                player = (

                    player_lookup.get(

                        badminton_id

                    )

                )





                if player is None:



                    flash(

                        "En af de valgte spillere "

                        "kan ikke vælges til dette hold.",

                        "error"

                    )



                    return redirect(

                        url_for(

                            "my_team"

                        )

                    )





                chosen_players.append(

                    player

                )





            # =============================================

            # COUNTS

            # =============================================



            male_count = sum(

                1



                for player

                in chosen_players



                if player["gender"] == "M"

            )





            female_count = sum(

                1



                for player

                in chosen_players



                if player["gender"] == "K"

            )





            # =============================================

            # NEVER ALLOW MORE THAN RULE LIMIT

            # =============================================



            if (

                male_count

                >

                rules["male_players"]

            ):



                flash(

                    "Du kan maksimalt vælge "

                    f"{rules['male_players']} herrer.",

                    "error"

                )



                return redirect(

                    url_for(

                        "my_team"

                    )

                )





            if (

                female_count

                >

                rules["female_players"]

            ):



                flash(

                    "Du kan maksimalt vælge "

                    f"{rules['female_players']} damer.",

                    "error"

                )



                return redirect(

                    url_for(

                        "my_team"

                    )

                )





            # =============================================

            # CAPTAIN MUST BE SELECTED PLAYER

            # =============================================



            if (

                captain_id

                and

                captain_id

                not in selected_ids

            ):



                flash(

                    "Kaptajnen skal være en spiller "

                    "på dit hold.",

                    "error"

                )



                return redirect(

                    url_for(

                        "my_team"

                    )

                )





            # =============================================

            # ACTIVATION VALIDATION

            # =============================================



            if action == "activate":



                if (

                    male_count

                    !=

                    rules["male_players"]

                ):



                    flash(

                        "Holdet skal have præcis "

                        f"{rules['male_players']} herrer "

                        "før det kan aktiveres.",

                        "error"

                    )



                    return redirect(

                        url_for(

                            "my_team"

                        )

                    )





                if (

                    female_count

                    !=

                    rules["female_players"]

                ):



                    flash(

                        "Holdet skal have præcis "

                        f"{rules['female_players']} damer "

                        "før det kan aktiveres.",

                        "error"

                    )



                    return redirect(

                        url_for(

                            "my_team"

                        )

                    )





                if not captain_id:



                    flash(

                        "Du skal vælge én kaptajn "

                        "før holdet kan aktiveres.",

                        "error"

                    )



                    return redirect(

                        url_for(

                            "my_team"

                        )

                    )





            # =============================================

            # CREATE / UPDATE TEAM

            # =============================================



            if team is None:



                cursor.execute(

                    """

                    INSERT INTO dbo.fantasy_teams (

                        user_id,

                        club_id,

                        season_id,

                        team_name,

                        status

                    )



                    OUTPUT INSERTED.id



                    VALUES (

                        ?,

                        ?,

                        ?,

                        ?,

                        'draft'

                    )

                    """,

                    int(

                        current_user.id

                    ),



                    current_user.club_id,



                    CURRENT_SEASON,



                    team_name

                )





                fantasy_team_id = (

                    cursor.fetchone()[0]

                )





            else:



                fantasy_team_id = (

                    team["id"]

                )





                cursor.execute(

                    """

                    UPDATE dbo.fantasy_teams



                    SET

                        team_name = ?,



                        updated_at =

                            SYSUTCDATETIME()



                    WHERE

                        id = ?

                    """,

                    team_name,

                    fantasy_team_id

                )





                # Draft kan frit overskrives.

                # Historik starter først,

                # når holdet aktiveres.



                cursor.execute(

                    """

                    DELETE FROM

                        dbo.fantasy_team_players



                    WHERE

                        fantasy_team_id = ?

                    """,

                    fantasy_team_id

                )





            # =============================================

            # INSERT CURRENT DRAFT PLAYERS

            # =============================================



            for player in chosen_players:



                cursor.execute(

                    """

                    INSERT INTO

                        dbo.fantasy_team_players

                    (

                        fantasy_team_id,

                        badminton_id,

                        is_captain,

                        active_from,

                        active_to,

                        selection_type

                    )



                    VALUES (

                        ?,

                        ?,

                        ?,

                        SYSUTCDATETIME(),

                        NULL,

                        'initial'

                    )

                    """,

                    fantasy_team_id,



                    player[

                        "badminton_id"

                    ],



                    1

                    if (

                        captain_id

                        and

                        player[

                            "badminton_id"

                        ]

                        ==

                        captain_id

                    )

                    else 0

                )





            # =============================================

            # ACTIVATE

            # =============================================



            if action == "activate":



                cursor.execute(

                    """

                    UPDATE dbo.fantasy_teams



                    SET

                        status = 'active',



                        activated_at =

                            SYSUTCDATETIME(),



                        updated_at =

                            SYSUTCDATETIME()



                    WHERE

                        id = ?

                    """,

                    fantasy_team_id

                )





                # Alle initiale spillere starter deres

                # fantasy-periode ved aktiveringen.



                cursor.execute(

                    """

                    UPDATE dbo.fantasy_team_players



                    SET

                        active_from =

                            SYSUTCDATETIME(),



                        updated_at =

                            SYSUTCDATETIME()



                    WHERE

                        fantasy_team_id = ?



                        AND active_to IS NULL

                    """,

                    fantasy_team_id

                )





                conn.commit()





                flash(

                    "Dit fantasy-hold er aktiveret.",

                    "success"

                )





            else:



                conn.commit()





                flash(

                    "Din holdkladde er gemt.",

                    "success"

                )





            return redirect(

                url_for(

                    "my_team"

                )

            )





        # =================================================

        # CURRENT SELECTED PLAYERS

        # =================================================



        selected_players = []





        if team is not None:



            cursor.execute(

                """

                SELECT

                    ftp.badminton_id,

                    ftp.is_captain,



                    p.player_name,

                    p.gender,



                    r.ranking_position,

                    r.national_position,

                    r.ranking_class,



                    COALESCE(

                        fp.fantasy_points,

                        0

                    ) AS fantasy_points



                FROM dbo.fantasy_team_players ftp



                INNER JOIN dbo.badminton_players p

                    ON p.badminton_id =

                        ftp.badminton_id



                OUTER APPLY (

                    SELECT TOP 1

                        pr.ranking_position,

                        pr.national_position,

                        pr.ranking_class



                    FROM dbo.player_rankings pr



                    WHERE

                        pr.badminton_id =

                            ftp.badminton_id



                        AND pr.club_id = ?



                        AND pr.season_id = ?



                    ORDER BY

                        pr.id DESC



                ) r



                LEFT JOIN (

                    SELECT

                        badminton_id,

                        club_id,

                        season_id,



                        SUM(points)

                            AS fantasy_points



                    FROM dbo.fantasy_point_events



                    WHERE

                        badminton_id IS NOT NULL



                    GROUP BY

                        badminton_id,

                        club_id,

                        season_id



                ) fp

                    ON fp.badminton_id =

                        ftp.badminton_id



                    AND fp.club_id = ?



                    AND fp.season_id = ?



                WHERE

                    ftp.fantasy_team_id = ?



                    AND ftp.active_to IS NULL



                ORDER BY



                    CASE

                        WHEN p.gender = 'M'

                        THEN 0



                        WHEN p.gender = 'K'

                        THEN 1



                        ELSE 2

                    END,



                    p.player_name

                """,



                current_user.club_id,

                CURRENT_SEASON,



                current_user.club_id,

                CURRENT_SEASON,



                team["id"]

            )





            selected_rows = (

                cursor.fetchall()

            )





            for row in selected_rows:



                selected_players.append(

                    {

                        "badminton_id":

                            row.badminton_id,



                        "player_name":

                            row.player_name,



                        "gender":

                            row.gender,



                        "ranking_position":

                            row.ranking_position,



                        "national_position":

                            row.national_position,



                        "ranking_class":

                            row.ranking_class,



                        "fantasy_points":

                            row.fantasy_points,



                        "is_captain":

                            bool(

                                row.is_captain

                            ),

                    }

                )





        # =================================================

        # SUBSTITUTIONS

        # =================================================



        substitutions_used = 0





        if team is not None:



            cursor.execute(

                """

                SELECT

                    COUNT(*)



                FROM dbo.fantasy_team_substitutions



                WHERE

                    fantasy_team_id = ?

                """,

                team["id"]

            )





            substitutions_used = (

                cursor.fetchone()[0]

            )





        # =================================================

        # RENDER

        # =================================================



        return render_template(

            "my_team.html",



            club=club,



            rules=rules,



            team=team,



            players=players,



            selected_players=

                selected_players,



            substitutions_used=

                substitutions_used,



            current_season=

                CURRENT_SEASON,

        )





    finally:



        cursor.close()

        conn.close()

@app.route("/api/clubs")
def search_clubs():

    query = (
        request.args
        .get("q", "")
        .strip()
    )


    if len(query) < 1:

        return jsonify([])


    conn = get_connection()
    cursor = conn.cursor()


    try:

        contains = (
            f"%{query}%"
        )


        starts_with = (
            f"{query}%"
        )


        cursor.execute(
            """
            SELECT TOP 10

                club_id,
                club_name

            FROM dbo.badminton_clubs

            WHERE

                club_id > 0

                AND club_name LIKE ?

            ORDER BY

                CASE
                    WHEN club_name LIKE ?
                    THEN 0
                    ELSE 1
                END,

                club_name
            """,

            contains,
            starts_with
        )


        rows = cursor.fetchall()


        clubs = [

            {
                "id": row.club_id,
                "name": row.club_name
            }

            for row in rows
        ]


        return jsonify(
            clubs
        )


    finally:

        cursor.close()
        conn.close()
        
@app.route("/statistics")
@login_required
def statistics():

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # =================================================
        # CLUB
        # =================================================

        cursor.execute(
            """
            SELECT
                club_id,
                club_name

            FROM dbo.badminton_clubs

            WHERE club_id = ?
            """,
            current_user.club_id
        )

        club_row = cursor.fetchone()

        if club_row is None:
            abort(404)



        # =================================================
        # SUMMARY KPI'S
        # =================================================

        cursor.execute(
            """
            SELECT

                (
                    SELECT COUNT(*)

                    FROM dbo.club_players cp

                    WHERE
                        cp.club_id = ?
                        AND cp.season_id = ?
                        AND cp.is_active = 1
                ) AS active_players,


                (
                    SELECT COUNT(*)

                    FROM dbo.club_matches cm

                    WHERE
                        cm.club_id = ?
                        AND cm.season_id = ?
                        AND cm.result IS NOT NULL
                        AND LTRIM(RTRIM(cm.result)) <> ''
                ) AS played_team_matches,


                (
                    SELECT COUNT(*)

                    FROM dbo.club_match_games g

                    INNER JOIN dbo.club_matches cm
                        ON cm.id = g.club_match_id

                    WHERE
                        cm.club_id = ?
                        AND cm.season_id = ?
                        AND (
                            g.winner_side IN ('home', 'away')
                            OR g.winner_wo_raw LIKE '%(1)%'
                            OR g.winner_wo_raw LIKE '%(2)%'
                        )
                ) AS individual_games,


                (
                    SELECT COUNT(*)

                    FROM dbo.fantasy_teams ft

                    WHERE
                        ft.club_id = ?
                        AND ft.season_id = ?
                        AND ft.status = 'active'
                ) AS active_fantasy_teams,


                (
                    SELECT COALESCE(SUM(fpe.points), 0)

                    FROM dbo.fantasy_point_events fpe

                    WHERE
                        fpe.club_id = ?
                        AND fpe.season_id = ?
                ) AS total_fantasy_points
            """,

            current_user.club_id,
            CURRENT_SEASON,

            current_user.club_id,
            CURRENT_SEASON,

            current_user.club_id,
            CURRENT_SEASON,

            current_user.club_id,
            CURRENT_SEASON,

            current_user.club_id,
            CURRENT_SEASON,
        )

        summary_row = cursor.fetchone()


        # =================================================
        # PLAYER STATISTICS
        # =================================================
        #
        # Statistik beregnes direkte på kamp- og sætniveau:
        #
        # - kampe / sejre / nederlag / sejr %
        # - antal 3-sætskampe
        # - andel af sejre som gik i 3 sæt
        # - gennemsnitlige modstanderpoint i sejre
        # - gennemsnitlige egne point i nederlag
        # - hjemme- og udebanesejr %
        # - sejre med mindst ét vundet sæt, hvor
        #   modstanderen fik 8 point eller færre
        # - single sejr % (HS / DS)
        # - mix sejr % (XD)
        # - HD/DD sejr % (HD / DD)
        #
        # W.O. tæller med i sejr/nederlag og winrates,
        # men ikke i scorebaserede gennemsnit, hvis der
        # ikke findes sætscorer.
        # =================================================

        cursor.execute(
            """
            WITH PlayerPoints AS (

                SELECT
                    fpe.badminton_id,
                    SUM(fpe.points) AS fantasy_points

                FROM dbo.fantasy_point_events fpe

                WHERE
                    fpe.club_id = ?
                    AND fpe.season_id = ?
                    AND fpe.badminton_id IS NOT NULL

                GROUP BY
                    fpe.badminton_id
            ),

            SetStats AS (

                SELECT
                    s.game_id,

                    COUNT(
                        CASE
                            WHEN
                                s.home_score IS NOT NULL
                                AND s.away_score IS NOT NULL
                            THEN 1
                        END
                    ) AS set_count,

                    SUM(
                        CASE
                            WHEN
                                s.home_score IS NOT NULL
                                AND s.away_score IS NOT NULL
                            THEN s.home_score
                        END
                    ) AS home_points,

                    SUM(
                        CASE
                            WHEN
                                s.home_score IS NOT NULL
                                AND s.away_score IS NOT NULL
                            THEN s.away_score
                        END
                    ) AS away_points,

                    MAX(
                        CASE
                            WHEN
                                s.home_score > s.away_score
                                AND s.away_score <= 8
                            THEN 1
                            ELSE 0
                        END
                    ) AS home_low8_set_win,

                    MAX(
                        CASE
                            WHEN
                                s.away_score > s.home_score
                                AND s.home_score <= 8
                            THEN 1
                            ELSE 0
                        END
                    ) AS away_low8_set_win

                FROM dbo.club_match_game_sets s

                GROUP BY
                    s.game_id
            ),

            GameInfo AS (

                SELECT
                    g.id AS game_id,
                    g.match_type,

                    CASE
                        WHEN g.winner_side IN ('home', 'away')
                            THEN g.winner_side

                        WHEN g.winner_wo_raw LIKE '%(1)%'
                            THEN 'home'

                        WHEN g.winner_wo_raw LIKE '%(2)%'
                            THEN 'away'

                        ELSE NULL
                    END AS effective_winner,

                    COALESCE(ss.set_count, 0)
                        AS set_count,

                    ss.home_points,
                    ss.away_points,

                    COALESCE(
                        ss.home_low8_set_win,
                        0
                    ) AS home_low8_set_win,

                    COALESCE(
                        ss.away_low8_set_win,
                        0
                    ) AS away_low8_set_win

                FROM dbo.club_match_games g

                INNER JOIN dbo.club_matches cm
                    ON cm.id = g.club_match_id

                LEFT JOIN SetStats ss
                    ON ss.game_id = g.id

                WHERE
                    cm.club_id = ?
                    AND cm.season_id = ?
            ),

            PlayerGames AS (

                SELECT
                    gp.badminton_id,
                    gi.game_id,
                    gi.match_type,
                    gp.side,
                    gi.set_count,

                    CASE
                        WHEN gi.effective_winner = gp.side
                            THEN 1
                        ELSE 0
                    END AS is_win,

                    CASE
                        WHEN gp.side = 'home'
                            THEN gi.home_points
                        ELSE gi.away_points
                    END AS own_points,

                    CASE
                        WHEN gp.side = 'home'
                            THEN gi.away_points
                        ELSE gi.home_points
                    END AS opponent_points,

                    CASE
                        WHEN
                            gi.effective_winner = gp.side
                            AND gp.side = 'home'
                            AND gi.home_low8_set_win = 1
                        THEN 1

                        WHEN
                            gi.effective_winner = gp.side
                            AND gp.side = 'away'
                            AND gi.away_low8_set_win = 1
                        THEN 1

                        ELSE 0
                    END AS low8_win

                FROM dbo.club_match_game_players gp

                INNER JOIN GameInfo gi
                    ON gi.game_id = gp.game_id

                WHERE
                    gp.badminton_id IS NOT NULL
                    AND gi.effective_winner IS NOT NULL
            ),

            GameStats AS (

                SELECT
                    pg.badminton_id,

                    COUNT(*) AS matches_played,

                    SUM(pg.is_win) AS wins,

                    SUM(
                        CASE
                            WHEN pg.set_count = 3
                                THEN 1
                            ELSE 0
                        END
                    ) AS three_set_matches,

                    SUM(
                        CASE
                            WHEN
                                pg.is_win = 1
                                AND pg.set_count = 3
                            THEN 1
                            ELSE 0
                        END
                    ) AS three_set_wins,

                    CAST(
                        SUM(
                            CASE
                                WHEN
                                    pg.is_win = 1
                                    AND pg.opponent_points IS NOT NULL
                                    AND pg.set_count > 0
                                THEN pg.opponent_points
                                ELSE 0
                            END
                        )
                        AS DECIMAL(12,2)
                    )
                    /
                    NULLIF(
                        SUM(
                            CASE
                                WHEN
                                    pg.is_win = 1
                                    AND pg.opponent_points IS NOT NULL
                                    AND pg.set_count > 0
                                THEN pg.set_count
                                ELSE 0
                            END
                        ),
                        0
                    ) AS avg_opponent_points_in_wins,

                    CAST(
                        SUM(
                            CASE
                                WHEN
                                    pg.is_win = 0
                                    AND pg.own_points IS NOT NULL
                                    AND pg.set_count > 0
                                THEN pg.own_points
                                ELSE 0
                            END
                        )
                        AS DECIMAL(12,2)
                    )
                    /
                    NULLIF(
                        SUM(
                            CASE
                                WHEN
                                    pg.is_win = 0
                                    AND pg.own_points IS NOT NULL
                                    AND pg.set_count > 0
                                THEN pg.set_count
                                ELSE 0
                            END
                        ),
                        0
                    ) AS avg_own_points_in_losses,
                    SUM(
                        CASE
                            WHEN pg.side = 'home'
                                THEN 1
                            ELSE 0
                        END
                    ) AS home_matches,

                    SUM(
                        CASE
                            WHEN
                                pg.side = 'home'
                                AND pg.is_win = 1
                            THEN 1
                            ELSE 0
                        END
                    ) AS home_wins,

                    SUM(
                        CASE
                            WHEN pg.side = 'away'
                                THEN 1
                            ELSE 0
                        END
                    ) AS away_matches,

                    SUM(
                        CASE
                            WHEN
                                pg.side = 'away'
                                AND pg.is_win = 1
                            THEN 1
                            ELSE 0
                        END
                    ) AS away_wins,

                    SUM(pg.low8_win)
                        AS low8_wins,

                    SUM(
                        CASE
                            WHEN pg.match_type IN (
                                'HS',
                                'DS'
                            )
                            THEN 1
                            ELSE 0
                        END
                    ) AS single_matches,

                    SUM(
                        CASE
                            WHEN
                                pg.match_type IN (
                                    'HS',
                                    'DS'
                                )
                                AND pg.is_win = 1
                            THEN 1
                            ELSE 0
                        END
                    ) AS single_wins,

                    SUM(
                        CASE
                            WHEN pg.match_type = 'XD'
                                THEN 1
                            ELSE 0
                        END
                    ) AS mixed_matches,

                    SUM(
                        CASE
                            WHEN
                                pg.match_type = 'XD'
                                AND pg.is_win = 1
                            THEN 1
                            ELSE 0
                        END
                    ) AS mixed_wins,

                    SUM(
                        CASE
                            WHEN pg.match_type IN (
                                'HD',
                                'DD'
                            )
                            THEN 1
                            ELSE 0
                        END
                    ) AS gender_double_matches,

                    SUM(
                        CASE
                            WHEN
                                pg.match_type IN (
                                    'HD',
                                    'DD'
                                )
                                AND pg.is_win = 1
                            THEN 1
                            ELSE 0
                        END
                    ) AS gender_double_wins

                FROM PlayerGames pg

                GROUP BY
                    pg.badminton_id
            )

            SELECT
                p.badminton_id,
                p.player_name,
                p.gender,

                COALESCE(
                    pp.fantasy_points,
                    0
                ) AS fantasy_points,

                COALESCE(
                    gs.matches_played,
                    0
                ) AS matches_played,

                COALESCE(
                    gs.wins,
                    0
                ) AS wins,

                (
                    COALESCE(
                        gs.matches_played,
                        0
                    )
                    -
                    COALESCE(
                        gs.wins,
                        0
                    )
                ) AS losses,

                CASE
                    WHEN
                        COALESCE(
                            gs.matches_played,
                            0
                        ) = 0
                    THEN NULL

                    ELSE CAST(
                        100.0
                        * gs.wins
                        / gs.matches_played
                        AS DECIMAL(5,1)
                    )
                END AS win_percentage,

                COALESCE(
                    gs.three_set_matches,
                    0
                ) AS three_set_matches,

                CASE
                    WHEN
                        COALESCE(
                            gs.wins,
                            0
                        ) = 0
                    THEN NULL

                    ELSE CAST(
                        100.0
                        * gs.three_set_wins
                        / gs.wins
                        AS DECIMAL(5,1)
                    )
                END AS three_set_win_percentage,

                CAST(
                    gs.avg_opponent_points_in_wins
                    AS DECIMAL(10,1)
                ) AS avg_opponent_points_in_wins,

                CAST(
                    gs.avg_own_points_in_losses
                    AS DECIMAL(10,1)
                ) AS avg_own_points_in_losses,

                CASE
                    WHEN
                        COALESCE(
                            gs.home_matches,
                            0
                        ) = 0
                    THEN NULL

                    ELSE CAST(
                        100.0
                        * gs.home_wins
                        / gs.home_matches
                        AS DECIMAL(5,1)
                    )
                END AS home_win_percentage,

                CASE
                    WHEN
                        COALESCE(
                            gs.away_matches,
                            0
                        ) = 0
                    THEN NULL

                    ELSE CAST(
                        100.0
                        * gs.away_wins
                        / gs.away_matches
                        AS DECIMAL(5,1)
                    )
                END AS away_win_percentage,

                COALESCE(
                    gs.low8_wins,
                    0
                ) AS low8_wins,

                CASE
                    WHEN
                        COALESCE(
                            gs.single_matches,
                            0
                        ) = 0
                    THEN NULL

                    ELSE CAST(
                        100.0
                        * gs.single_wins
                        / gs.single_matches
                        AS DECIMAL(5,1)
                    )
                END AS single_win_percentage,

                CASE
                    WHEN
                        COALESCE(
                            gs.mixed_matches,
                            0
                        ) = 0
                    THEN NULL

                    ELSE CAST(
                        100.0
                        * gs.mixed_wins
                        / gs.mixed_matches
                        AS DECIMAL(5,1)
                    )
                END AS mixed_win_percentage,

                CASE
                    WHEN
                        COALESCE(
                            gs.gender_double_matches,
                            0
                        ) = 0
                    THEN NULL

                    ELSE CAST(
                        100.0
                        * gs.gender_double_wins
                        / gs.gender_double_matches
                        AS DECIMAL(5,1)
                    )
                END AS gender_double_win_percentage

            FROM dbo.club_players cp

            INNER JOIN dbo.badminton_players p
                ON p.badminton_id =
                    cp.badminton_id

            LEFT JOIN PlayerPoints pp
                ON pp.badminton_id =
                    cp.badminton_id

            LEFT JOIN GameStats gs
                ON gs.badminton_id =
                    cp.badminton_id

            WHERE
                cp.club_id = ?
                AND cp.season_id = ?
                AND cp.is_active = 1

            ORDER BY
                COALESCE(
                    pp.fantasy_points,
                    0
                ) DESC,
                COALESCE(
                    gs.wins,
                    0
                ) DESC,
                p.player_name ASC
            """,

            current_user.club_id,
            CURRENT_SEASON,

            current_user.club_id,
            CURRENT_SEASON,

            current_user.club_id,
            CURRENT_SEASON,
        )

        player_rows = cursor.fetchall()


        # =================================================
        # FANTASY TEAM LEADERBOARD
        # =================================================
        #
        # Point beregnes kun for den periode, hvor spilleren
        # faktisk var aktiv på fantasy-holdet.
        #
        # Det betyder:
        # - ingen point før holdet blev aktiveret
        # - udskiftede spillere stopper med at optjene point
        # - nye spillere optjener point fra deres active_from
        # - kaptajnmultiplier følger perioden
        # =================================================

        cursor.execute(
            """
            SELECT
                ft.id,
                ft.team_name,
                u.display_name AS owner_name,

                COALESCE(
                    SUM(
                        COALESCE(pp.player_points, 0)
                        *
                        CASE
                            WHEN ftp.is_captain = 1
                                THEN COALESCE(
                                    ftr.captain_multiplier,
                                    2.00
                                )
                            ELSE 1.00
                        END
                    ),
                    0
                ) AS team_points,

                COALESCE(
                    MAX(sc.substitution_count),
                    0
                ) AS substitutions_used

            FROM dbo.fantasy_teams ft

            INNER JOIN dbo.users u
                ON u.user_id = ft.user_id

            LEFT JOIN dbo.fantasy_team_rules ftr
                ON ftr.club_id = ft.club_id
                AND ftr.season_id = ft.season_id

            LEFT JOIN dbo.fantasy_team_players ftp
                ON ftp.fantasy_team_id = ft.id

            OUTER APPLY (

                SELECT
                    COALESCE(
                        SUM(fpe.points),
                        0
                    ) AS player_points

                FROM dbo.fantasy_point_events fpe

                INNER JOIN dbo.club_matches cm
                    ON cm.id = fpe.club_match_id

                WHERE
                    fpe.badminton_id =
                        ftp.badminton_id

                    AND fpe.club_id =
                        ft.club_id

                    AND fpe.season_id =
                        ft.season_id

                    AND cm.match_time >=
                        ftp.active_from

                    AND (
                        ftp.active_to IS NULL
                        OR cm.match_time <
                            ftp.active_to
                    )

            ) pp

            OUTER APPLY (

                SELECT
                    COUNT(*) AS substitution_count

                FROM dbo.fantasy_team_substitutions fts

                WHERE
                    fts.fantasy_team_id = ft.id

            ) sc

            WHERE
                ft.club_id = ?
                AND ft.season_id = ?
                AND ft.status = 'active'

            GROUP BY
                ft.id,
                ft.team_name,
                u.display_name

            ORDER BY
                team_points DESC,
                ft.team_name ASC
            """,

            current_user.club_id,
            CURRENT_SEASON
        )

        fantasy_team_rows = cursor.fetchall()


    finally:

        cursor.close()
        conn.close()


    # =====================================================
    # SERIALIZE CLUB
    # =====================================================

    club = {
        "id": club_row.club_id,
        "name": club_row.club_name,
    }


    # =====================================================
    # SERIALIZE SUMMARY
    # =====================================================

    summary = {
        "active_players":
            int(summary_row.active_players or 0),

        "played_team_matches":
            int(summary_row.played_team_matches or 0),

        "individual_games":
            int(summary_row.individual_games or 0),

        "active_fantasy_teams":
            int(summary_row.active_fantasy_teams or 0),

        "total_fantasy_points":
            int(summary_row.total_fantasy_points or 0),
    }


    # =====================================================
    # SERIALIZE PLAYERS
    # =====================================================

    def nullable_float(value):

        if value is None:
            return None

        return float(value)


    players = []

    for row in player_rows:

        players.append(
            {
                "badminton_id":
                    row.badminton_id,

                "player_name":
                    row.player_name,

                "gender":
                    row.gender,

                "fantasy_points":
                    int(row.fantasy_points or 0),

                "matches_played":
                    int(row.matches_played or 0),

                "wins":
                    int(row.wins or 0),

                "losses":
                    int(row.losses or 0),

                "win_percentage":
                    nullable_float(
                        row.win_percentage
                    ),

                "three_set_matches":
                    int(
                        row.three_set_matches
                        or 0
                    ),

                "three_set_win_percentage":
                    nullable_float(
                        row.three_set_win_percentage
                    ),

                "avg_opponent_points_in_wins":
                    nullable_float(
                        row.avg_opponent_points_in_wins
                    ),

                "avg_own_points_in_losses":
                    nullable_float(
                        row.avg_own_points_in_losses
                    ),

                "home_win_percentage":
                    nullable_float(
                        row.home_win_percentage
                    ),

                "away_win_percentage":
                    nullable_float(
                        row.away_win_percentage
                    ),

                "low8_wins":
                    int(
                        row.low8_wins
                        or 0
                    ),

                "single_win_percentage":
                    nullable_float(
                        row.single_win_percentage
                    ),

                "mixed_win_percentage":
                    nullable_float(
                        row.mixed_win_percentage
                    ),

                "gender_double_win_percentage":
                    nullable_float(
                        row.gender_double_win_percentage
                    ),
            }
        )


    # =====================================================
    # NORMAL / FUN KPI'S
    # =====================================================

    point_leader = (
        max(
            players,
            key=lambda p: (
                p["fantasy_points"],
                p["wins"],
            )
        )
        if players
        else None
    )


    players_with_matches = [
        player
        for player in players
        if player["matches_played"] > 0
    ]


    most_wins = (
        max(
            players_with_matches,
            key=lambda p: (
                p["wins"],
                (p["win_percentage"] or 0),
                p["fantasy_points"],
            )
        )
        if players_with_matches
        else None
    )


    most_matches = (
        max(
            players_with_matches,
            key=lambda p: (
                p["matches_played"],
                p["wins"],
                p["fantasy_points"],
            )
        )
        if players_with_matches
        else None
    )


    win_rate_candidates = [
        player
        for player in players
        if player["matches_played"] >= 3
    ]


    best_win_rate = (
        max(
            win_rate_candidates,
            key=lambda p: (
                (p["win_percentage"] or 0),
                p["wins"],
                p["fantasy_points"],
            )
        )
        if win_rate_candidates
        else None
    )


    highlights = {
        "point_leader":
            point_leader,

        "most_wins":
            most_wins,

        "most_matches":
            most_matches,

        "best_win_rate":
            best_win_rate,
    }


    # =====================================================
    # FANTASY TEAMS
    # =====================================================

    fantasy_leaderboard = [

        {
            "id":
                row.id,

            "team_name":
                row.team_name,

            "owner_name":
                row.owner_name,

            "points":
                float(row.team_points or 0),

            "substitutions_used":
                int(row.substitutions_used or 0),
        }

        for row in fantasy_team_rows
    ]


    # =====================================================
    # RENDER
    # =====================================================

    return render_template(
        "statistics.html",

        club=club,
        summary=summary,
        players=players,
        highlights=highlights,
        fantasy_leaderboard=fantasy_leaderboard,

        current_season=CURRENT_SEASON,
    )


# =========================================================
# DASHBOARD / HOME
# =========================================================

@login_required
@app.route("/dashboard")
@login_required
def dashboard():

    ensure_dashboard_teams_table()

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # =================================================
        # CLUB
        # =================================================

        cursor.execute(
            """
            SELECT
                club_id,
                club_name

            FROM dbo.badminton_clubs

            WHERE club_id = ?
            """,
            current_user.club_id
        )

        club_row = cursor.fetchone()


        # =================================================
        # ACTIVE DASHBOARD TEAMS
        # =================================================

        cursor.execute(
            """
            SELECT
                id,
                department,
                sub_department,
                team_name,
                league_name,
                league_group_id,
                age_group_id,
                region_id,
                league_group_team_id

            FROM dbo.club_dashboard_teams

            WHERE
                club_id = ?
                AND season_id = ?
                AND is_active = 1

            ORDER BY
                CASE department
                    WHEN 'U' THEN 1
                    WHEN 'SEN' THEN 2
                    WHEN 'MOT' THEN 3
                    WHEN 'VET' THEN 4
                    ELSE 99
                END,
                sub_department,
                team_name,
                league_name
            """,
            current_user.club_id,
            CURRENT_SEASON
        )

        team_rows = cursor.fetchall()


        # =================================================
        # TOP 5 MEN
        # =================================================

        cursor.execute(
            """
            SELECT TOP 5
                p.badminton_id,
                p.player_name,
                COALESCE(SUM(fpe.points), 0) AS fantasy_points

            FROM dbo.club_players cp

            INNER JOIN dbo.badminton_players p
                ON p.badminton_id = cp.badminton_id

            LEFT JOIN dbo.fantasy_point_events fpe
                ON fpe.badminton_id = cp.badminton_id
                AND fpe.club_id = cp.club_id
                AND fpe.season_id = cp.season_id

            WHERE
                cp.club_id = ?
                AND cp.season_id = ?
                AND cp.is_active = 1
                AND p.gender = 'M'

            GROUP BY
                p.badminton_id,
                p.player_name

            ORDER BY
                COALESCE(SUM(fpe.points), 0) DESC,
                p.player_name ASC
            """,
            current_user.club_id,
            CURRENT_SEASON
        )

        top_men_rows = cursor.fetchall()


        # =================================================
        # TOP 5 WOMEN
        # =================================================

        cursor.execute(
            """
            SELECT TOP 5
                p.badminton_id,
                p.player_name,
                COALESCE(SUM(fpe.points), 0) AS fantasy_points

            FROM dbo.club_players cp

            INNER JOIN dbo.badminton_players p
                ON p.badminton_id = cp.badminton_id

            LEFT JOIN dbo.fantasy_point_events fpe
                ON fpe.badminton_id = cp.badminton_id
                AND fpe.club_id = cp.club_id
                AND fpe.season_id = cp.season_id

            WHERE
                cp.club_id = ?
                AND cp.season_id = ?
                AND cp.is_active = 1
                AND p.gender = 'K'

            GROUP BY
                p.badminton_id,
                p.player_name

            ORDER BY
                COALESCE(SUM(fpe.points), 0) DESC,
                p.player_name ASC
            """,
            current_user.club_id,
            CURRENT_SEASON
        )

        top_women_rows = cursor.fetchall()


        # =================================================
        # FANTASY TEAM LEADERBOARD
        # =================================================
        #
        # Denne første version beregner stillingen ud fra den
        # nuværende aktive trup på hvert hold og giver kaptajnen
        # den multiplier, som admin har sat.
        #
        # Når vi senere vil gøre historiske udskiftninger 100 %
        # præcise, skal point-events kobles til selve kampdatoen
        # og sammenholdes med active_from / active_to.
        # =================================================

        cursor.execute(
            """
            SELECT
                ft.id,
                ft.team_name,
                u.display_name AS owner_name,

                COALESCE(
                    SUM(
                        COALESCE(pp.player_points, 0)
                        *
                        CASE
                            WHEN ftp.is_captain = 1
                                THEN COALESCE(ftr.captain_multiplier, 2.00)
                            ELSE 1.00
                        END
                    ),
                    0
                ) AS team_points

            FROM dbo.fantasy_teams ft

            INNER JOIN dbo.users u
                ON u.user_id = ft.user_id

            LEFT JOIN dbo.fantasy_team_rules ftr
                ON ftr.club_id = ft.club_id
                AND ftr.season_id = ft.season_id

            LEFT JOIN dbo.fantasy_team_players ftp
                ON ftp.fantasy_team_id = ft.id
                AND ftp.active_to IS NULL

            OUTER APPLY (
                SELECT
                    COALESCE(SUM(fpe.points), 0) AS player_points

                FROM dbo.fantasy_point_events fpe

                WHERE
                    fpe.badminton_id = ftp.badminton_id
                    AND fpe.club_id = ft.club_id
                    AND fpe.season_id = ft.season_id
            ) pp

            WHERE
                ft.club_id = ?
                AND ft.season_id = ?
                AND ft.status = 'active'

            GROUP BY
                ft.id,
                ft.team_name,
                u.display_name

            ORDER BY
                team_points DESC,
                ft.team_name ASC
            """,
            current_user.club_id,
            CURRENT_SEASON
        )

        fantasy_team_rows = cursor.fetchall()


    finally:
        cursor.close()
        conn.close()


    # =====================================================
    # CLUB
    # =====================================================

    club = None

    if club_row is not None:
        club = {
            "id": club_row.club_id,
            "name": club_row.club_name,
        }


    # =====================================================
    # DASHBOARD TEAMS
    # =====================================================

    teams = [
        {
            "id": row.id,
            "department": row.department,
            "sub_department": row.sub_department,
            "team_name": row.team_name,
            "league_name": row.league_name,
            "league_group_id": row.league_group_id,
            "age_group_id": row.age_group_id,
            "region_id": row.region_id,
            "league_group_team_id": row.league_group_team_id,
        }
        for row in team_rows
    ]


    grouped_teams = {
        "U": {},
        "SEN": [],
        "MOT": [],
        "VET": [],
    }

    for team in teams:

        department = team["department"]

        if department == "U":

            sub_department = (
                team["sub_department"]
                or "Andet"
            )

            if sub_department not in grouped_teams["U"]:
                grouped_teams["U"][sub_department] = []

            grouped_teams["U"][sub_department].append(team)

        elif department in grouped_teams:
            grouped_teams[department].append(team)


    # =====================================================
    # PLAYER LEADERBOARDS
    # =====================================================

    top_men = [
        {
            "badminton_id": row.badminton_id,
            "player_name": row.player_name,
            "points": int(row.fantasy_points or 0),
        }
        for row in top_men_rows
    ]

    top_women = [
        {
            "badminton_id": row.badminton_id,
            "player_name": row.player_name,
            "points": int(row.fantasy_points or 0),
        }
        for row in top_women_rows
    ]


    # =====================================================
    # FANTASY TEAM LEADERBOARD
    # =====================================================

    fantasy_leaderboard = [
        {
            "id": row.id,
            "team_name": row.team_name,
            "owner_name": row.owner_name,
            "points": float(row.team_points or 0),
        }
        for row in fantasy_team_rows
    ]


    return render_template(
        "dashboard.html",
        club=club,
        grouped_teams=grouped_teams,
        team_count=len(teams),
        fantasy_leaderboard=fantasy_leaderboard,
        fantasy_team_count=len(fantasy_leaderboard),
        top_men=top_men,
        top_women=top_women,
        current_season=CURRENT_SEASON,
    )


# =========================================================
# ADMIN DASHBOARD
# =========================================================

@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():

    ensure_dashboard_teams_table()


    conn = get_connection()
    cursor = conn.cursor()


    try:

        # =================================================
        # CLUB
        # =================================================

        cursor.execute(
            """
            SELECT

                club_id,
                club_name

            FROM dbo.badminton_clubs

            WHERE club_id = ?
            """,

            current_user.club_id
        )


        club_row = (
            cursor.fetchone()
        )


        if club_row is None:

            abort(404)


        # =================================================
        # MEMBERS
        # =================================================

        cursor.execute(
            """
            SELECT

                user_id,
                display_name,
                email,
                club_role,
                created_at

            FROM dbo.users

            WHERE club_id = ?

            ORDER BY

                CASE
                    WHEN club_role = 'admin'
                    THEN 0
                    ELSE 1
                END,

                display_name
            """,

            current_user.club_id
        )


        member_rows = (
            cursor.fetchall()
        )


        # =================================================
        # TEAMS
        # =================================================

        cursor.execute(
            """
            SELECT

                id,
                department,
                sub_department,
                team_name,
                league_name,
                league_group_id,
                age_group_id,
                region_id,
                league_group_team_id,
                is_active

            FROM dbo.club_dashboard_teams

            WHERE

                club_id = ?

                AND season_id = ?

            ORDER BY

                CASE department

                    WHEN 'U'
                        THEN 1

                    WHEN 'SEN'
                        THEN 2

                    WHEN 'MOT'
                        THEN 3

                    WHEN 'VET'
                        THEN 4

                    ELSE 99

                END,

                sub_department,
                team_name,
                league_name
            """,

            current_user.club_id,
            CURRENT_SEASON
        )


        team_rows = (
            cursor.fetchall()
        )


    finally:

        cursor.close()
        conn.close()


    # =====================================================
    # CLUB
    # =====================================================

    club = {

        "id":
            club_row.club_id,

        "name":
            club_row.club_name
    }


    # =====================================================
    # MEMBERS
    # =====================================================

    members = [

        {
            "user_id":
                row.user_id,

            "display_name":
                row.display_name,

            "email":
                row.email,

            "club_role":
                row.club_role,

            "created_at":
                row.created_at
        }

        for row in member_rows
    ]


    member_count = len(
        members
    )


    admin_count = sum(

        1

        for member in members

        if member["club_role"] == "admin"
    )


    # =====================================================
    # TEAMS
    # =====================================================

    teams = [

        {
            "id":
                row.id,

            "department":
                row.department,

            "sub_department":
                row.sub_department,

            "team_name":
                row.team_name,

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

            "is_active":
                bool(row.is_active)
        }

        for row in team_rows
    ]


    # =====================================================
    # GROUP TEAMS
    # =====================================================

    grouped_teams = {

        "U": {},

        "SEN": [],

        "MOT": [],

        "VET": []
    }


    for team in teams:

        department = (
            team["department"]
        )


        if department == "U":

            sub_department = (

                team["sub_department"]
                or "Andet"
            )


            if (
                sub_department
                not in grouped_teams["U"]
            ):

                grouped_teams[
                    "U"
                ][
                    sub_department
                ] = []


            grouped_teams[
                "U"
            ][
                sub_department
            ].append(
                team
            )


        elif department in grouped_teams:

            grouped_teams[
                department
            ].append(
                team
            )


    # =====================================================
    # RENDER
    # =====================================================

    return render_template(

        "admin.html",

        club=club,

        members=members,

        member_count=member_count,

        admin_count=admin_count,

        grouped_teams=grouped_teams,

        team_count=len(teams),

        current_season=CURRENT_SEASON
    )


# =========================================================
# ADMIN - REFRESH TEAMS FROM BADMINTONPLAYER
# =========================================================

@app.route(
    "/admin/teams/refresh",
    methods=["POST"]
)
@login_required
@admin_required
def refresh_admin_teams():

    ensure_dashboard_teams_table()


    # =====================================================
    # SCRAPE BADMINTONPLAYER
    # =====================================================

    try:

        teams = get_club_teams(

            club_id=
                current_user.club_id,

            season_id=
                CURRENT_SEASON,

            headless=False
        )


    except Exception as e:

        print()
        print(
            "Fejl ved hentning af hold "
            "fra BadmintonPlayer:"
        )

        print(e)


        flash(
            "Kunne ikke hente hold fra "
            "BadmintonPlayer.",
            "error"
        )


        return redirect(
            url_for("admin_dashboard")
        )


    # =====================================================
    # SAVE
    # =====================================================

    conn = get_connection()
    cursor = conn.cursor()


    try:

        for team in teams:

            league_group_id = int(
                team["league_group_id"]
            )


            # =================================================
            # AGE GROUP
            # =================================================
            #
            # Ny parser:
            #
            # age_group_id
            #
            # Fallback til gammel parser,
            # hvor værdien fejlagtigt hed
            # league_group_team_id.
            # =================================================

            age_group_raw = team.get(
                "age_group_id"
            )


            if age_group_raw in (
                None,
                ""
            ):

                age_group_raw = team.get(
                    "league_group_team_id"
                )


            age_group_id = (

                int(age_group_raw)

                if age_group_raw not in (
                    None,
                    ""
                )

                else None
            )


            cursor.execute(
                """
                MERGE dbo.club_dashboard_teams
                    AS target


                USING (

                    SELECT

                        ? AS club_id,

                        ? AS season_id,

                        ? AS league_group_id,

                        ? AS team_name

                ) AS source


                ON

                    target.club_id =
                        source.club_id

                    AND

                    target.season_id =
                        source.season_id

                    AND

                    target.league_group_id =
                        source.league_group_id

                    AND

                    target.team_name =
                        source.team_name


                WHEN MATCHED THEN

                    UPDATE SET

                        department = ?,

                        sub_department = ?,

                        league_name = ?,

                        age_group_id = ?,

                        updated_at =
                            SYSUTCDATETIME()


                WHEN NOT MATCHED THEN

                    INSERT (

                        club_id,
                        season_id,

                        department,
                        sub_department,

                        team_name,
                        league_name,

                        league_group_id,
                        age_group_id,

                        region_id,

                        league_group_team_id,

                        is_active

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

                        NULL,

                        NULL,

                        0

                    );
                """,


                # =========================================
                # SOURCE
                # =========================================

                current_user.club_id,

                CURRENT_SEASON,

                league_group_id,

                team["team_name"],


                # =========================================
                # UPDATE
                # =========================================

                team["department"],

                team["sub_department"],

                team["league_name"],

                age_group_id,


                # =========================================
                # INSERT
                # =========================================

                current_user.club_id,

                CURRENT_SEASON,

                team["department"],

                team["sub_department"],

                team["team_name"],

                team["league_name"],

                league_group_id,

                age_group_id
            )


        conn.commit()


    except Exception:

        conn.rollback()

        raise


    finally:

        cursor.close()
        conn.close()


    flash(
        f"{len(teams)} hold/rækker blev "
        f"hentet fra BadmintonPlayer.",
        "success"
    )


    return redirect(
        url_for("admin_dashboard")
    )


# =========================================================
# ADMIN - SAVE SELECTED DASHBOARD TEAMS
# =========================================================

# =========================================================
# ADMIN - SAVE SELECTED DASHBOARD TEAMS
# =========================================================

@app.route(
    "/admin/teams/save",
    methods=["POST"]
)
@login_required
@admin_required
def save_admin_teams():

    ensure_dashboard_teams_table()


    # =====================================================
    # SELECTED DATABASE IDS
    # =====================================================

    selected_ids_raw = (
        request.form.getlist(
            "selected_team_ids"
        )
    )


    selected_ids = []


    for value in selected_ids_raw:

        try:

            selected_ids.append(
                int(value)
            )

        except ValueError:

            continue


    # =====================================================
    # SAVE ACTIVE STATUS
    # =====================================================

    conn = get_connection()
    cursor = conn.cursor()


    try:

        # -------------------------------------------------
        # Disable all teams for club/season
        # -------------------------------------------------

        cursor.execute(
            """
            UPDATE dbo.club_dashboard_teams

            SET
                is_active = 0,
                updated_at =
                    SYSUTCDATETIME()

            WHERE
                club_id = ?
                AND season_id = ?
            """,

            current_user.club_id,
            CURRENT_SEASON
        )


        # -------------------------------------------------
        # Activate selected teams
        # -------------------------------------------------

        if selected_ids:

            placeholders = ",".join(
                ["?"] * len(
                    selected_ids
                )
            )


            sql = f"""
                UPDATE dbo.club_dashboard_teams

                SET
                    is_active = 1,
                    updated_at =
                        SYSUTCDATETIME()

                WHERE
                    club_id = ?
                    AND season_id = ?
                    AND id IN (
                        {placeholders}
                    )
            """


            params = [
                current_user.club_id,
                CURRENT_SEASON,
                *selected_ids
            ]


            cursor.execute(
                sql,
                params
            )


        conn.commit()


    except Exception:

        conn.rollback()
        raise


    finally:

        cursor.close()
        conn.close()


    # =====================================================
    # NOTHING SELECTED
    # =====================================================

    if not selected_ids:

        flash(
            "Dashboard opdateret. "
            "Ingen hold er valgt.",
            "success"
        )


        return redirect(
            url_for(
                "admin_dashboard"
            )
        )


    # =====================================================
    # SYNC ALL ACTIVE TEAMS
    # =====================================================

    try:

        result = (
            sync_club_active_teams(
                club_id=
                    current_user.club_id,

                season_id=
                    CURRENT_SEASON,
            )
        )


    except Exception as e:

        print()
        print(
            "=" * 100
        )

        print(
            "FEJL VED KAMPDATA-SYNC"
        )

        print(
            "=" * 100
        )

        print(e)


        flash(
            "Holdvalget blev gemt, "
            "men kampdata kunne ikke opdateres.",
            "error"
        )


        return redirect(
            url_for(
                "admin_dashboard"
            )
        )


    # =====================================================
    # RESULT
    # =====================================================

    if (
        result["failed_teams"]
        or result["failed_matches"]
    ):

        flash(
            f"{result['active_teams']} hold er valgt. "
            f"{result['matches']} holdkampe blev fundet. "
            f"{result['games']} delkampe blev fundet. "
            f"Nogle elementer kunne ikke opdateres.",
            "error"
        )


    else:

        flash(
            f"{result['active_teams']} hold er valgt. "
            f"{result['matches']} holdkampe blev opdateret. "
            f"{result['games']} delkampe blev fundet.",
            "success"
        )


    return redirect(
        url_for(
            "admin_dashboard"
        )
    )

@login_required
@admin_required
def save_admin_teams():

    ensure_dashboard_teams_table()


    # =====================================================
    # SELECTED DATABASE IDS
    # =====================================================

    selected_ids_raw = (

        request.form.getlist(
            "selected_team_ids"
        )

    )


    selected_ids = []


    for value in selected_ids_raw:

        try:

            selected_ids.append(
                int(value)
            )

        except ValueError:

            continue


    # =====================================================
    # SAVE ACTIVE STATUS
    # =====================================================

    conn = get_connection()
    cursor = conn.cursor()


    try:

        # -------------------------------------------------
        # Disable all teams
        # -------------------------------------------------

        cursor.execute(
            """
            UPDATE dbo.club_dashboard_teams

            SET

                is_active = 0,

                updated_at =
                    SYSUTCDATETIME()

            WHERE

                club_id = ?

                AND season_id = ?
            """,

            current_user.club_id,

            CURRENT_SEASON
        )


        # -------------------------------------------------
        # Activate selected rows
        # -------------------------------------------------

        if selected_ids:

            placeholders = ",".join(

                ["?"] * len(
                    selected_ids
                )

            )


            sql = f"""
                UPDATE dbo.club_dashboard_teams

                SET

                    is_active = 1,

                    updated_at =
                        SYSUTCDATETIME()

                WHERE

                    club_id = ?

                    AND season_id = ?

                    AND id IN (
                        {placeholders}
                    )
            """


            params = [

                current_user.club_id,

                CURRENT_SEASON,

                *selected_ids
            ]


            cursor.execute(
                sql,
                params
            )


        conn.commit()


    except Exception:

        conn.rollback()

        raise


    finally:

        cursor.close()
        conn.close()


    # =====================================================
    # NOTHING SELECTED
    # =====================================================

    if not selected_ids:

        flash(
            "Dashboard opdateret. "
            "Ingen hold er valgt.",
            "success"
        )


        return redirect(
            url_for("admin_dashboard")
        )


    # =====================================================
    # READ SELECTED TEAMS
    # =====================================================

    conn = get_connection()
    cursor = conn.cursor()


    try:

        placeholders = ",".join(

            ["?"] * len(
                selected_ids
            )

        )


        sql = f"""
            SELECT

                id,

                team_name,

                league_name,

                league_group_id,

                age_group_id,

                region_id,

                league_group_team_id

            FROM dbo.club_dashboard_teams

            WHERE

                club_id = ?

                AND season_id = ?

                AND is_active = 1

                AND id IN (
                    {placeholders}
                )

            ORDER BY
                id
        """


        params = [

            current_user.club_id,

            CURRENT_SEASON,

            *selected_ids
        ]


        cursor.execute(
            sql,
            params
        )


        rows = (
            cursor.fetchall()
        )


        selected_teams = [

            {
                "id":
                    row.id,

                "team_name":
                    row.team_name,

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
            }

            for row in rows
        ]


    finally:

        cursor.close()
        conn.close()


    # =====================================================
    # BADMINTONPLAYER SESSION
    # =====================================================

    try:

        session = create_session()


        callback_context = (
            get_callback_context(
                session
            )
        )


    except Exception as e:

        print()
        print(
            "Kunne ikke starte "
            "BadmintonPlayer-sync:"
        )

        print(e)


        flash(
            "Dashboard-valg blev gemt, "
            "men kampdata kunne ikke opdateres.",
            "error"
        )


        return redirect(
            url_for("admin_dashboard")
        )


    # =====================================================
    # SYNC SELECTED TEAMS
    # =====================================================

    all_matches = []

    successful_teams = 0

    failed_teams = []


    for team in selected_teams:

        try:

            print()
            print(
                "=" * 80
            )

            print(
                "Synkroniserer:",
                team["team_name"],
                "-",
                team["league_name"]
            )

            print(
                "=" * 80
            )


            # =============================================
            # AGE GROUP REQUIRED
            # =============================================

            if team["age_group_id"] is None:

                raise RuntimeError(
                    "Holdet mangler age_group_id."
                )


            # =============================================
            # RESOLVE TEAM IDS
            # =============================================

            ids = resolve_team_ids(

                session=session,

                callback_context=
                    callback_context,

                club_id=
                    current_user.club_id,

                season_id=
                    CURRENT_SEASON,

                league_group_id=
                    team["league_group_id"],

                age_group_id=
                    team["age_group_id"],

                team_name=
                    team["team_name"],
            )


            region_id = (
                ids["region_id"]
            )


            league_group_team_id = (
                ids[
                    "league_group_team_id"
                ]
            )


            print(
                "Region ID:",
                region_id
            )


            print(
                "League Group Team ID:",
                league_group_team_id
            )


            # =============================================
            # SAVE RESOLVED IDS
            # =============================================

            update_conn = (
                get_connection()
            )

            update_cursor = (
                update_conn.cursor()
            )


            try:

                update_cursor.execute(
                    """
                    UPDATE dbo.club_dashboard_teams

                    SET

                        region_id = ?,

                        league_group_team_id = ?,

                        updated_at =
                            SYSUTCDATETIME()

                    WHERE

                        id = ?

                        AND club_id = ?

                        AND season_id = ?
                    """,

                    region_id,

                    league_group_team_id,

                    team["id"],

                    current_user.club_id,

                    CURRENT_SEASON
                )


                update_conn.commit()


            except Exception:

                update_conn.rollback()

                raise


            finally:

                update_cursor.close()

                update_conn.close()


            # =============================================
            # GET TEAM MATCHES
            # =============================================

            matches = get_team_matches(

                session=session,

                callback_context=
                    callback_context,

                club_id=
                    current_user.club_id,

                season_id=
                    CURRENT_SEASON,

                league_group_id=
                    team["league_group_id"],

                age_group_id=
                    team["age_group_id"],

                region_id=
                    region_id,

                league_group_team_id=
                    league_group_team_id,

                club_team_name=
                    team["team_name"],

                league_name=
                    team["league_name"],
            )


            print(
                f"Kampe fundet: "
                f"{len(matches)}"
            )


            all_matches.extend(
                matches
            )


            successful_teams += 1


        except Exception as e:

            print()
            print(
                "FEJL VED HOLD:"
            )

            print(
                team["team_name"],
                "-",
                team["league_name"]
            )

            print(e)


            failed_teams.append(
                {
                    "team_name":
                        team["team_name"],

                    "league_name":
                        team["league_name"],

                    "error":
                        str(e)
                }
            )


    # =====================================================
    # REMOVE DUPLICATE MATCHES
    # =====================================================

    unique_matches = {}


    for match in all_matches:

        key = (
            match["club_id"],
            match["season_id"],
            match["league_match_id"]
        )


        if key not in unique_matches:

            unique_matches[key] = match


    all_matches = list(
        unique_matches.values()
    )


    # =====================================================
    # SAVE MATCHES TO AZURE
    # =====================================================

    if all_matches:

        try:

            print()
            print(
                f"Gemmer {len(all_matches)} "
                f"unikke kampe i Azure..."
            )


            save_matches_to_azure(
                all_matches
            )


        except Exception as e:

            print()
            print(
                "Fejl ved gemning "
                "af kampe i Azure:"
            )

            print(e)


            flash(
                "Holdene blev valgt, "
                "men kampdata kunne ikke "
                "gemmes i Azure.",
                "error"
            )


            return redirect(
                url_for("admin_dashboard")
            )


    # =====================================================
    # RESULT
    # =====================================================

    if failed_teams:

        flash(
            f"Dashboard opdateret. "
            f"{len(selected_teams)} hold er valgt. "
            f"{successful_teams} hold blev synkroniseret. "
            f"{len(failed_teams)} hold fejlede. "
            f"{len(all_matches)} kampe blev opdateret.",
            "error"
        )


    else:

        flash(
            f"Dashboard opdateret. "
            f"{len(selected_teams)} hold er valgt. "
            f"{len(all_matches)} kampe blev "
            f"gemt/opdateret.",
            "success"
        )


    return redirect(
        url_for("admin_dashboard")
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
@login_required
def logout():

    logout_user()


    flash(
        "Du er nu logget ud.",
        "success"
    )


    return redirect(
        url_for("login")
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )