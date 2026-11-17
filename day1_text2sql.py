"""Day 1: plain-Python Text-to-SQL. No frameworks, no agent loop yet."""
import os
import re

import duckdb
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()  # reads GEMINI_API_KEY and GEMINI_MODEL from .env

DB_PATH = "data/chinook.duckdb"
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options=types.HttpOptions(timeout=30000),  # 30 seconds, in milliseconds
)

# read_only=True: even if the LLM writes DROP TABLE, DuckDB will refuse it.
con = duckdb.connect(DB_PATH, read_only=True)


def get_schema_text() -> str:
    """Return the schema as one line per table: Table(col type, col type, ...)."""
    rows = con.execute(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'main'
        ORDER BY table_name, ordinal_position
        """
    ).fetchall()

    tables = {}
    for table, column, dtype in rows:
        tables.setdefault(table, []).append(f"{column} {dtype}")

    return "\n".join(f"{t}({', '.join(cols)})" for t, cols in tables.items())


def ask_llm_for_sql(question: str, schema: str) -> str:
    """Send schema + question to the LLM and return its raw text reply."""
    system_prompt = (
        "You are a SQL expert for a DuckDB database. "
        "Given the schema and a question, reply with exactly ONE SQL SELECT query "
        "and nothing else. No explanation, no markdown."
    )
    user_prompt = f"Schema:\n{schema}\n\nQuestion: {question}"

    response = client.models.generate_content(
        model=MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0,  # we want consistent SQL, not creativity
        ),
    )
    return response.text


def clean_sql(text: str) -> str:
    """LLMs sometimes wrap SQL in ```sql fences. Strip them."""
    text = text.strip()
    text = re.sub(r"^```(?:sql)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def run_sql(sql: str):
    cursor = con.execute(sql)
    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    return columns, rows


def main():
    question = input("Ask a question about the Chinook database: ").strip()

    schema = get_schema_text()
    raw = ask_llm_for_sql(question, schema)
    sql = clean_sql(raw)
    print("\n--- Generated SQL ---")
    print(sql)

    try:
        columns, rows = run_sql(sql)
    except Exception as e:  # Day 3 turns this into a retry loop
        print("\n--- SQL error ---")
        print(e)
        return

    print("\n--- Result ---")
    print(columns)
    for row in rows[:20]:
        print(row)
    print(f"({len(rows)} rows)")


if __name__ == "__main__":
    main()