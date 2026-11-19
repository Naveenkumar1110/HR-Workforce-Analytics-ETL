
from sqlalchemy import create_engine, URL, text
from getpass import getpass

username = input("PostgreSQL username: ")
password = getpass("PostgreSQL password: ")

db_url = URL.create(
    drivername="postgresql+psycopg",
    username=username,
    password=password,
    host="localhost",
    port=5432,
    database="workforce_db"
)

engine = create_engine(db_url, connect_args={"connect_timeout": 5})

try:
    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT current_database(), current_user")
        )
        print("Connected successfully!")
        print("Database and user:", result.fetchone())

except Exception as error:
    print("Connection failed!")
    print(error)

finally:
    engine.dispose()
