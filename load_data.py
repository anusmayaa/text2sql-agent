"""One-time script: copy Chinook tables from SQLite into a DuckDB file."""
from pathlib import Path

import duckdb

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
        count = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        print(f"{table:15} {count} rows")

    con.close()
    print(f"\nDone. Created {DUCKDB_FILE}")


if __name__ == "__main__":
    main()