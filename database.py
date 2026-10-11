import os

import pyodbc
from dotenv import load_dotenv


load_dotenv()


SERVER = os.getenv("DB_SERVER")
DATABASE = os.getenv("DB_DATABASE")
USERNAME = os.getenv("DB_USERNAME")
PASSWORD = os.getenv("DB_PASSWORD")
DRIVER = os.getenv(
    "DB_DRIVER",
    "ODBC Driver 18 for SQL Server"
)


def get_connection():

    required = {
        "DB_SERVER": SERVER,
        "DB_DATABASE": DATABASE,
        "DB_USERNAME": USERNAME,
        "DB_PASSWORD": PASSWORD,
    }

    missing = [
        key
        for key, value in required.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Manglende database environment variables: "
            + ", ".join(missing)
        )

    connection_string = (
        f"DRIVER={{{DRIVER}}};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        f"UID={USERNAME};"
        f"PWD={PASSWORD};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=no;"
        f"Connection Timeout=30;"
    )

    return pyodbc.connect(
        connection_string
    )