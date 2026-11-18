"""Safety tests for tools.py. No API key needed, so these also run in CI."""
import duckdb
import pytest

from tools import MAX_ROWS, con, run_query, validate_sql

UNSAFE_SQL = [
    "DROP TABLE Customer",
    "DELETE FROM Invoice",
    "INSERT INTO Genre VALUES (99, 'x')",
    "UPDATE Customer SET Email = 'x'",
    "CREATE TABLE hack AS SELECT 1",
    "ALTER TABLE Customer ADD COLUMN x INTEGER",
    "SELECT 1; DROP TABLE Customer",
    "ATTACH 'other.duckdb' AS other",
    "COPY Customer TO 'customers.csv'",
    "INSTALL httpfs",
    "SELECT * FROM read_csv('load_data.py')",
]


@pytest.mark.parametrize("sql", UNSAFE_SQL)
def test_unsafe_sql_is_blocked(sql):
    result = validate_sql(sql)
    assert result["ok"] is False
    assert result["error_type"] == "blocked"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) FROM Track",
        "WITH t AS (SELECT GenreId FROM Track) SELECT COUNT(*) FROM t",
    ],
)
def test_valid_select_passes(sql):
    assert validate_sql(sql)["ok"] is True


def test_wrong_column_is_a_fixable_error_not_a_block():
    result = validate_sql("SELECT Colour FROM Track")
    assert result["error_type"] == "sql_error"


def test_run_query_returns_at_most_max_rows():
    result = run_query("SELECT * FROM Track")  # the table has 3503 rows
    assert result["row_count"] == MAX_ROWS
    assert result["truncated"] is True


def test_slow_query_times_out():
    slow_sql = (
        "SELECT SUM(a.Milliseconds + b.Milliseconds + c.Milliseconds) "
        "FROM Track a, Track b, Track c"
    )
    result = run_query(slow_sql, timeout_s=1)
    assert result["error_type"] == "timeout"


def test_database_refuses_writes_even_without_the_validator():
    # Layer 1 of defense in depth: skip validate_sql and go straight to DuckDB.
    cur = con.cursor()
    try:
        with pytest.raises(duckdb.Error):
            cur.execute("DELETE FROM Invoice")
    finally:
        cur.close()
    assert con.execute("SELECT COUNT(*) FROM Invoice").fetchall()[0][0] == 412