import os
import pyodbc
from dotenv import load_dotenv

load_dotenv()

server = os.getenv("SERVER")
database = os.getenv("DATABASE")
username = os.getenv("USERNAME")
password = os.getenv("PASSWORD")
driver = os.getenv("DRIVER")

connection_string = (
    f"DRIVER={driver};SERVER=tcp:{server};PORT=1433;"
    f"DATABASE={database};UID={username};PWD={password}"
)

def get_db_connection():
    return pyodbc.connect(connection_string)
