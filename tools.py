"""Tools the agent can call: get_schema, validate_sql and run_query.

Each tool returns plain data (a string or a dict) instead of raising,
so the agent can hand any error message straight back to the LLM.
"""
import threading
from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parent / "data" / "chinook.duckdb"
MAX_ROWS = 100
QUERY_TIMEOUT_S = 10
SAMPLE_ROWS = 3

# Layer 1 of defense in depth: the database refuses all writes, and with
# external access off, SQL cannot touch files on disk (read_csv, COPY, ATTACH).
con = duckdb.connect(
    str(DB_PATH),
    read_only=True,
    config={"enable_external_access": False},
)


def _error(error_type: str, message: str) -> dict:
    """error_type is 'blocked' (unsafe), 'sql_error' (fixable) or 'timeout'."""
    return {"ok": False, "error_type": error_type, "error": message}


def get_schema() -> str:
    """Describe every table: row count, columns with types, and sample rows."""
    columns = con.execute(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'main'
        ORDER BY table_name, ordinal_position
        """
    ).fetchall()

    tables = {}
    for table, column, dtype in columns:
        tables.setdefault(table, []).append(f"{column} {dtype}")

    blocks = []
    for table, cols in tables.items():
        row_count = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchall()[0][0]
        samples = con.execute(
            f'SELECT * FROM "{table}" LIMIT {SAMPLE_ROWS}'
        ).fetchall()
        lines = [
            f"Table {table} ({row_count} rows)",
            f"  Columns: {', '.join(cols)}",
            "  Sample rows:",
        ]
        lines += ["    " + " | ".join(str(value) for value in row) for row in samples]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def validate_sql(sql: str) -> dict:
    """Allow exactly one SELECT statement that DuckDB can plan."""
    # Step 1: parse with DuckDB's own parser, not keyword matching.
    try:
        statements = con.extract_statements(sql)
    except duckdb.Error as e:
        return _error("sql_error", f"Could not parse SQL: {e}")

    # Step 2: exactly one statement, so "SELECT 1; DROP TABLE x" is rejected.
    if len(statements) != 1:
        return _error(
            "blocked", f"Exactly one statement is allowed, got {len(statements)}."
        )

    # Step 3: only SELECT. A WITH ... SELECT query also parses as SELECT.
    statement_type = statements[0].type
    if statement_type != duckdb.StatementType.SELECT:
        return _error(
            "blocked", f"Only SELECT queries are allowed, got {statement_type.name}."
        )

    # Step 4: EXPLAIN plans the query without running it, so wrong table or
    # column names fail here, before anything executes.
    try:
        con.execute(f"EXPLAIN {sql}").fetchall()
    except duckdb.PermissionException as e:
        return _error("blocked", f"Blocked by database permissions: {e}")
    except duckdb.Error as e:
        return _error("sql_error", str(e))

    return {"ok": True}


def run_query(sql: str, timeout_s: float = QUERY_TIMEOUT_S) -> dict:
    """Validate, then run sql with a time limit, returning at most MAX_ROWS rows."""
    # Defense in depth: validate again even if the caller already did.
    check = validate_sql(sql)
    if not check["ok"]:
        return check

    # A fresh cursor per query: DuckDB 2.0 keeps a connection busy while a
    # result is still open, so each query gets its own and closes it at the end.
    cur = con.cursor()
    # If the query is still running after timeout_s, the timer interrupts it.
    timer = threading.Timer(timeout_s, cur.interrupt)
    timer.start()
    try:
        cur.execute(sql)
        columns = [col[0] for col in cur.description]
        rows = cur.fetchmany(MAX_ROWS + 1)  # one extra row shows if there were more
    except duckdb.InterruptException:
        return _error(
            "timeout", f"Query took longer than {timeout_s} seconds and was stopped."
        )
    except duckdb.Error as e:
        return _error("sql_error", str(e))
    finally:
        timer.cancel()
        cur.close()

    return {
        "ok": True,
        "columns": columns,
        "rows": rows[:MAX_ROWS],
        "row_count": min(len(rows), MAX_ROWS),
        "truncated": len(rows) > MAX_ROWS,
    }