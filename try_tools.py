"""Manual check for tools.py. Run from the project folder: python try_tools.py"""
from tools import get_schema, run_query, validate_sql

results = []  # one True/False per check


def check(label, result, expected):
    """expected is 'ok' or the error_type we expect: blocked, sql_error, timeout."""
    outcome = "ok" if result["ok"] else result["error_type"]
    passed = outcome == expected
    results.append(passed)
    print(f"[{'PASS' if passed else 'FAIL'}] {label:<28} -> {outcome}")
    if not result["ok"]:
        print(f"       {result['error'].splitlines()[0][:90]}")


def check_rows(label, result, expected_rows, expected_truncated):
    passed = (
        result["ok"]
        and result["row_count"] == expected_rows
        and result["truncated"] == expected_truncated
    )
    results.append(passed)
    if result["ok"]:
        got = f"{result['row_count']} rows, truncated={result['truncated']}"
    else:
        got = f"{result['error_type']}: {result['error']}"
    print(f"[{'PASS' if passed else 'FAIL'}] {label:<28} -> {got}")


print("=== get_schema ===")
schema = get_schema()
print(schema.split("\n\n")[0])  # the first table, as an example
table_count = sum(line.startswith("Table ") for line in schema.splitlines())
print(f"Tables found: {table_count}")
results.append(table_count == 11)

print("\n=== validate_sql ===")
cte_sql = (
    "WITH g AS (SELECT GenreId, COUNT(*) AS n FROM Track GROUP BY GenreId) "
    "SELECT * FROM g ORDER BY n DESC"
)
check("simple SELECT", validate_sql("SELECT COUNT(*) FROM Track"), "ok")
check("WITH (CTE) query", validate_sql(cte_sql), "ok")
check("DROP TABLE", validate_sql("DROP TABLE Customer"), "blocked")
check("DELETE", validate_sql("DELETE FROM Invoice"), "blocked")
check("INSERT", validate_sql("INSERT INTO Genre VALUES (99, 'x')"), "blocked")
check("SELECT then DROP", validate_sql("SELECT 1; DROP TABLE Customer"), "blocked")
check("typo in keyword", validate_sql("SELEC * FROM Track"), "sql_error")
check("nonexistent column", validate_sql("SELECT Colour FROM Track"), "sql_error")
csv_sql = "SELECT * FROM read_csv('load_data.py')"
check("read_csv on a local file", validate_sql(csv_sql), "blocked")

print("\n=== run_query ===")
check_rows("SELECT * FROM Track", run_query("SELECT * FROM Track"), 100, True)
genre_sql = "SELECT Name FROM Genre ORDER BY Name LIMIT 5"
check_rows("5 genres", run_query(genre_sql), 5, False)
check("DROP via run_query", run_query("DROP TABLE Customer"), "blocked")
slow_sql = (
    "SELECT SUM(a.Milliseconds + b.Milliseconds + c.Milliseconds) "
    "FROM Track a, Track b, Track c"
)
check("slow query, 2s timeout", run_query(slow_sql, timeout_s=2), "timeout")
count_sql = "SELECT COUNT(*) FROM Track"
check_rows("works again after timeout", run_query(count_sql), 1, False)

print(f"\n{sum(results)}/{len(results)} checks passed")