"""Export a reporting table for the Power BI dashboard: one row per invoice line.

Run: python export_for_powerbi.py   ->   powerbi/sales.csv
The export is reconciled against the source (row count and total revenue)
before anyone builds a report on it.
"""
import csv
import sys
from pathlib import Path

import duckdb

DB_PATH = Path("data/chinook.duckdb")
OUT_FILE = Path("powerbi/sales.csv")

SALES_SQL = """
SELECT
    il.InvoiceLineId                                    AS invoice_line_id,
    i.InvoiceId                                         AS invoice_id,
    CAST(i.InvoiceDate AS DATE)                         AS invoice_date,
    CAST(DATE_TRUNC('month', i.InvoiceDate) AS DATE)    AS invoice_month,
    YEAR(i.InvoiceDate)                                 AS invoice_year,
    i.BillingCountry                                    AS country,
    c.CustomerId                                        AS customer_id,
    c.FirstName || ' ' || c.LastName                    AS customer,
    e.FirstName || ' ' || e.LastName                    AS support_rep,
    g.Name                                              AS genre,
    ar.Name                                             AS artist,
    al.Title                                            AS album,
    t.Name                                              AS track,
    mt.Name                                             AS media_type,
    il.Quantity                                         AS quantity,
    il.UnitPrice                                        AS unit_price,
    ROUND(il.UnitPrice * il.Quantity, 2)                AS revenue
FROM InvoiceLine il
JOIN Invoice i         ON i.InvoiceId = il.InvoiceId
JOIN Customer c        ON c.CustomerId = i.CustomerId
LEFT JOIN Employee e   ON e.EmployeeId = c.SupportRepId
JOIN Track t           ON t.TrackId = il.TrackId
LEFT JOIN Genre g      ON g.GenreId = t.GenreId
LEFT JOIN Album al     ON al.AlbumId = t.AlbumId
LEFT JOIN Artist ar    ON ar.ArtistId = al.ArtistId
JOIN MediaType mt      ON mt.MediaTypeId = t.MediaTypeId
ORDER BY invoice_line_id
"""


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    cursor = con.execute(SALES_SQL)
    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    source_rows, source_revenue = con.execute(
        "SELECT (SELECT COUNT(*) FROM InvoiceLine), "
        "(SELECT ROUND(SUM(Total), 2) FROM Invoice)"
    ).fetchall()[0]
    con.close()

    OUT_FILE.parent.mkdir(exist_ok=True)
    # utf-8-sig adds a marker so Power BI and Excel read names like "Holý" correctly
    with OUT_FILE.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)

    # Reconcile: same number of rows as InvoiceLine, same revenue as Invoice totals.
    revenue_col = columns.index("revenue")
    exported_revenue = round(sum(row[revenue_col] for row in rows), 2)
    print(f"Rows:    exported {len(rows)}, source {source_rows}")
    print(f"Revenue: exported {exported_revenue}, source {source_revenue}")
    if len(rows) != source_rows or exported_revenue != round(source_revenue, 2):
        print("Reconciliation FAILED")
        sys.exit(1)
    print(f"Reconciled. Wrote {OUT_FILE}")


if __name__ == "__main__":
    main()