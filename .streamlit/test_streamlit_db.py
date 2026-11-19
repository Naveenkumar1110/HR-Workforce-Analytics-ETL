
# ============================================================
# TEST STREAMLIT POSTGRESQL CONNECTION
# Purpose: Verify credentials stored in secrets.toml
# ============================================================

import tomllib
from pathlib import Path
from sqlalchemy import create_engine, URL, text

secrets_path = (
    Path(__file__).resolve().parent
    / ".streamlit"
    / "secrets.toml"
)

with open(secrets_path, "rb") as file:
    config = tomllib.load(file)["database"]

url = URL.create(
    drivername="postgresql+psycopg",
    username=config["user"],
    password=config["password"],
    host=config["host"],
    port=config["port"],
    database=config["dbname"]
)

engine = create_engine(
    url,
    connect_args={"connect_timeout": 5}
)

try:
    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT current_user, current_database()")
        )

        print("Connected successfully!")
        print("User and Database:", result.fetchone())

except Exception as error:
    print("Connection failed!")
    print(type(error).__name__)

finally:
    engine.dispose()
