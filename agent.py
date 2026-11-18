"""Text-to-SQL agent: Gemini chooses tools, we run them, and SQL errors go back
to Gemini so it can fix its own query (up to MAX_SQL_RETRIES times).

Run: python agent.py
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx2
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from tools import get_schema, run_query

load_dotenv()

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
MAX_SQL_RETRIES = 3  # failed queries allowed after the first attempt
MAX_STEPS = 10  # hard cap on Gemini calls per question, so it can never loop forever
API_RETRY_WAITS = [5, 15, 30]  # seconds to wait after a temporary Gemini error
TRANSIENT_CODES = {429, 500, 503, 504}  # rate limit or server busy: worth waiting
FIXABLE_ERRORS = ("sql_error", "timeout")  # tool errors Gemini may try to fix
LOG_FILE = Path(__file__).resolve().parent / "logs" / "agent_log.jsonl"

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options=types.HttpOptions(timeout=30_000),  # milliseconds
)

SYSTEM_PROMPT = """You are a data analyst for a DuckDB database called Chinook
(a music store: customers, employees, invoices, tracks, albums, artists, genres).

How to work:
1. Call get_schema to see the tables, columns and sample rows.
2. Write ONE read-only SELECT query in DuckDB SQL and call run_query.
3. If run_query returns an error, read it, fix the SQL and call run_query again.
4. When you have the rows you need, answer in 1-3 plain-English sentences.

Rules:
- Only SELECT queries. If asked to change or delete data, refuse politely.
- Include the numbers that answer the question as columns (counts, totals).
- Round money values to 2 decimal places in the SQL, e.g. ROUND(SUM(Total), 2).
- Only state facts that are in the query result. Never invent numbers.
- Describe only queries you actually ran and the results they really returned."""

TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="get_schema",
                description="List every table with its columns, types, row count "
                "and 3 sample rows.",
            ),
            types.FunctionDeclaration(
                name="run_query",
                description="Validate and run ONE read-only DuckDB SELECT query. "
                "Returns up to 100 rows, or an error message to fix.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "The SELECT query."}
                    },
                    "required": ["sql"],
                },
            ),
        ]
    )
]

CONFIG = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=TOOLS,
    # We run the tools ourselves, so we can validate, log and count retries.
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
)


def log_event(run_id: str, event: str, **fields) -> None:
    """Append one JSON line to logs/agent_log.jsonl."""
    LOG_FILE.parent.mkdir(exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": run_id,
        "event": event,
        **fields,
    }
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def to_json_safe(result: dict) -> dict:
    """Gemini needs JSON. A JSON round trip turns Decimals and dates into strings."""
    return json.loads(json.dumps(result, default=str))


def call_gemini(contents: list, run_id: str):
    """Call Gemini. On a temporary error (429, 5xx, timeout) wait and try again."""
    for wait in API_RETRY_WAITS + [None]:
        try:
            return client.models.generate_content(
                model=MODEL, contents=contents, config=CONFIG
            )
        except errors.APIError as e:
            if e.code not in TRANSIENT_CODES:
                raise  # e.g. 400 or 404: waiting will not fix it
            error = f"{e.code} {e.message}"
        except httpx2.TransportError as e:  # timeouts and dropped connections
            error = f"{type(e).__name__}: {e}"

        if wait is None:
            raise RuntimeError(f"Gemini kept failing: {error}")
        log_event(run_id, "api_retry", error=error, wait_s=wait)
        print(f"  Gemini temporary error ({error}). Waiting {wait}s...")
        time.sleep(wait)


def run_tool(call, run_id: str) -> dict:
    """Run the tool Gemini asked for and log the call."""
    args = call.args or {}
    start = time.perf_counter()
    if call.name == "get_schema":
        result = {"ok": True, "schema": get_schema()}
    elif call.name == "run_query":
        result = run_query(args.get("sql", ""))
    else:
        result = {
            "ok": False,
            "error_type": "sql_error",
            "error": f"Unknown tool: {call.name}",
        }

    log_event(
        run_id,
        "tool_call",
        tool=call.name,
        sql=args.get("sql"),
        ok=result["ok"],
        error_type=result.get("error_type"),
        error=result.get("error"),
        row_count=result.get("row_count"),
        duration_ms=round((time.perf_counter() - start) * 1000),
    )
    return result


def ask(question: str) -> dict:
    """Answer one question. Returns the answer, final SQL, rows and retry history."""
    run_id = uuid.uuid4().hex[:8]
    log_event(run_id, "question", question=question, model=MODEL)
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=question)])]
    attempts = []  # one entry per run_query call
    last_ok = {}  # the most recent successful run_query result
    status, answer = "failed", f"Stopped after {MAX_STEPS} steps without an answer."

    for _ in range(MAX_STEPS):
        try:
            response = call_gemini(contents, run_id)
        except Exception as e:  # still failing after the waits, or a 400/404
            status, answer = "api_error", f"Gemini API error: {e}"
            break

        if not response.function_calls:  # no tool request means a final answer
            status, answer = "answered", (response.text or "").strip()
            break

        # Send the model's turn back unchanged: Gemini 3 needs its thought signatures.
        contents.append(response.candidates[0].content)
        replies = []
        for call in response.function_calls:
            result = run_tool(call, run_id)
            if call.name == "run_query":
                sql = (call.args or {}).get("sql", "")
                attempts.append(
                    {
                        "sql": sql,
                        "ok": result["ok"],
                        "error_type": result.get("error_type"),
                        "error": result.get("error"),
                    }
                )
                if result["ok"]:
                    last_ok = {"sql": sql, **result}
            replies.append(
                types.Part.from_function_response(
                    name=call.name, response=to_json_safe(result)
                )
            )
        contents.append(types.Content(role="user", parts=replies))

        # Unsafe SQL: stop at once, never retry.
        if any(a["error_type"] == "blocked" for a in attempts):
            status = "blocked"
            answer = "Blocked: only read-only SELECT queries are allowed."
            break
        # Fixable errors: allow the first attempt plus MAX_SQL_RETRIES more.
        sql_errors = [a for a in attempts if a["error_type"] in FIXABLE_ERRORS]
        if len(sql_errors) > MAX_SQL_RETRIES:
            status = "failed"
            answer = f"No working query after {len(sql_errors)} attempts."
            break

    retries = sum(1 for a in attempts if a["error_type"] in FIXABLE_ERRORS)
    log_event(run_id, "final", status=status, retries=retries, answer=answer)
    return {
        "run_id": run_id,
        "question": question,
        "status": status,  # answered, blocked, failed or api_error
        "answer": answer,
        "sql": last_ok.get("sql"),
        "columns": last_ok.get("columns", []),
        "rows": last_ok.get("rows", []),
        "truncated": last_ok.get("truncated", False),
        "attempts": attempts,
        "retries": retries,
    }


def print_result(result: dict) -> None:
    print("\n--- SQL attempts ---")
    for i, a in enumerate(result["attempts"], start=1):
        outcome = "ok" if a["ok"] else f"{a['error_type']}: {a['error'][:120]}"
        print(f"{i}. {a['sql']}\n   -> {outcome}")
    if result["sql"]:
        print("\n--- Result (first 10 rows) ---")
        print(" | ".join(result["columns"]))
        for row in result["rows"][:10]:
            print(" | ".join(str(value) for value in row))
    print(f"\n--- Answer [{result['status']}, retries={result['retries']}] ---")
    print(result["answer"])


if __name__ == "__main__":
    question = input("Ask a question about the Chinook database: ").strip()
    print_result(ask(question))