"""Data-quality checks for the Chinook tables.

Used by load_data.py after every load, and by tests/test_data_quality.py.
Each check returns (name, passed, detail) so results are easy to print and test.
"""

PRIMARY_KEYS = {
    "Album": ["AlbumId"],
    "Artist": ["ArtistId"],
    "Customer": ["CustomerId"],
    "Employee": ["EmployeeId"],
    "Genre": ["GenreId"],
    "Invoice": ["InvoiceId"],
    "InvoiceLine": ["InvoiceLineId"],
    "MediaType": ["MediaTypeId"],
    "Playlist": ["PlaylistId"],
    "PlaylistTrack": ["PlaylistId", "TrackId"],
    "Track": ["TrackId"],
}

# Columns that must never be empty (primary keys are checked separately).
REQUIRED_COLUMNS = {
    "Album": ["Title", "ArtistId"],
    "Customer": ["FirstName", "LastName", "Email"],
    "Invoice": ["CustomerId", "InvoiceDate", "Total"],
    "InvoiceLine": ["InvoiceId", "TrackId", "UnitPrice", "Quantity"],
    "Track": ["Name", "MediaTypeId", "Milliseconds", "UnitPrice"],
}

# (child table, child column, parent table, parent column)
FOREIGN_KEYS = [
    ("Album", "ArtistId", "Artist", "ArtistId"),
    ("Track", "AlbumId", "Album", "AlbumId"),
    ("Track", "GenreId", "Genre", "GenreId"),
    ("Track", "MediaTypeId", "MediaType", "MediaTypeId"),
    ("Invoice", "CustomerId", "Customer", "CustomerId"),
    ("InvoiceLine", "InvoiceId", "Invoice", "InvoiceId"),
    ("InvoiceLine", "TrackId", "Track", "TrackId"),
    ("Customer", "SupportRepId", "Employee", "EmployeeId"),
    ("Employee", "ReportsTo", "Employee", "EmployeeId"),
    ("PlaylistTrack", "PlaylistId", "Playlist", "PlaylistId"),
    ("PlaylistTrack", "TrackId", "Track", "TrackId"),
]

# Each query counts the rows that break the rule, so 0 means the rule holds.
BUSINESS_RULES = {
    "invoice totals match the sum of their lines": """
        SELECT COUNT(*) FROM Invoice i
        WHERE ROUND(i.Total, 2) <> (
            SELECT ROUND(SUM(il.UnitPrice * il.Quantity), 2)
            FROM InvoiceLine il WHERE il.InvoiceId = i.InvoiceId)
    """,
    "no negative prices or zero quantities": """
        SELECT COUNT(*) FROM InvoiceLine WHERE UnitPrice < 0 OR Quantity <= 0
    """,
}


def scalar(con, sql: str):
    """Run a query that returns one value."""
    return con.execute(sql).fetchall()[0][0]


def check_row_counts(con, tables: list, source: str = "src") -> list:
    """Reconcile row counts between the source database and the loaded tables."""
    results = []
    for table in tables:
        source_rows = scalar(con, f'SELECT COUNT(*) FROM {source}."{table}"')
        target_rows = scalar(con, f'SELECT COUNT(*) FROM main."{table}"')
        results.append(
            (
                f"row count {table}",
                source_rows == target_rows,
                f"source {source_rows}, target {target_rows}",
            )
        )
    return results


def check_primary_keys(con, primary_keys: dict = PRIMARY_KEYS) -> list:
    """Primary keys must be unique and never NULL."""
    results = []
    for table, cols in primary_keys.items():
        col_list = ", ".join(f'"{c}"' for c in cols)
        duplicates = scalar(
            con,
            f'SELECT COUNT(*) FROM (SELECT {col_list} FROM "{table}" '
            f"GROUP BY {col_list} HAVING COUNT(*) > 1)",
        )
        null_filter = " OR ".join(f'"{c}" IS NULL' for c in cols)
        nulls = scalar(con, f'SELECT COUNT(*) FROM "{table}" WHERE {null_filter}')
        results.append(
            (
                f"primary key {table}({', '.join(cols)})",
                duplicates == 0 and nulls == 0,
                f"{duplicates} duplicates, {nulls} nulls",
            )
        )
    return results


def check_required_columns(con, required: dict = REQUIRED_COLUMNS) -> list:
    """Required columns must have no NULLs."""
    results = []
    for table, cols in required.items():
        for col in cols:
            nulls = scalar(con, f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" IS NULL')
            results.append((f"not null {table}.{col}", nulls == 0, f"{nulls} nulls"))
    return results


def check_foreign_keys(con, foreign_keys: list = FOREIGN_KEYS) -> list:
    """Every foreign key value must exist in its parent table (NULLs are allowed)."""
    results = []
    for child, col, parent, parent_col in foreign_keys:
        orphans = scalar(
            con,
            f'SELECT COUNT(*) FROM "{child}" c WHERE c."{col}" IS NOT NULL '
            f'AND NOT EXISTS (SELECT 1 FROM "{parent}" p '
            f'WHERE p."{parent_col}" = c."{col}")',
        )
        results.append(
            (
                f"foreign key {child}.{col} -> {parent}.{parent_col}",
                orphans == 0,
                f"{orphans} orphan rows",
            )
        )
    return results


def check_business_rules(con, rules: dict = BUSINESS_RULES) -> list:
    results = []
    for name, sql in rules.items():
        bad_rows = scalar(con, sql)
        results.append((name, bad_rows == 0, f"{bad_rows} bad rows"))
    return results


def run_all_checks(con, tables: list) -> list:
    return (
        check_row_counts(con, tables)
        + check_primary_keys(con)
        + check_required_columns(con)
        + check_foreign_keys(con)
        + check_business_rules(con)
    )


def print_report(results: list) -> bool:
    """Print one line per check. Returns True if every check passed."""
    print("\n=== Data-quality checks ===")
    for name, passed, detail in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {name:<48} {detail}")
    passed_count = sum(1 for _, passed, _ in results if passed)
    print(f"\n{passed_count}/{len(results)} checks passed")
    return passed_count == len(results)