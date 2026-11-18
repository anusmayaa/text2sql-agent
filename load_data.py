"""Load Chinook from SQLite into DuckDB, then run data-quality checks.

Exits with code 1 if any check fails, so a bad load never goes unnoticed.
"""
import sys
from pathlib import Path

import duckdb

from quality import print_report, run_all_checks

SQLITE_FILE = Path("data/Chinook_Sqlite.sqlite")
DUCKDB_FILE = Path("data/chinook.duckdb")

TABLES = [
    "Album", "Artist", "Customer", "Employee", "Genre", "Invoice",
    "InvoiceLine", "MediaType", "Playlist", "PlaylistTrack", "Track",
]


def main():
    if DUCKDB_FILE.exists():
        DUCKDB_FILE.unlink()  # start fresh so the script is re-runnable

    con = duckdb.connect(str(DUCKDB_FILE))
    con.execute("INSTALL sqlite")  # needs internet the first time only
    con.execute("LOAD sqlite")
    con.execute(f"ATTACH '{SQLITE_FILE.as_posix()}' AS src (TYPE sqlite)")

    for table in TABLES:
        con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM src."{table}"')
        print(f"Loaded {table}")

    # CREATE TABLE AS copies the data but not the keys/constraints,
    # so we verify keys, required values and relationships ourselves.
    results = run_all_checks(con, TABLES)
    con.close()
    print(f"\nCreated {DUCKDB_FILE}")

    if not print_report(results):
        sys.exit(1)


if __name__ == "__main__":
    main()