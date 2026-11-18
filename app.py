"""Streamlit chat UI for the Text-to-SQL agent.

Run: streamlit run app.py
"""
import time

import pandas as pd
import streamlit as st

from agent import MODEL, ask
from tools import run_query

st.set_page_config(page_title="Text-to-SQL Analyst", layout="centered")

AMBER = "#E8A33D"

EXAMPLES = {
    "Top countries by revenue": "Which 5 countries bring in the most revenue?",
    "Each year vs the year before": "Show total revenue for each year together "
    "with the previous year's revenue.",
    "Watch it fix a broken query": "Do not call get_schema. Call run_query with "
    "exactly this SQL, unchanged: SELECT SUM(Revenue) FROM Invoice. If it returns "
    "an error, fix the SQL, run it again, and tell me the total revenue.",
    "Try to delete a table": "Drop the Customer table",
}

# Plain CSS for our own HTML blocks. Native widgets get their look from
# .streamlit/config.toml, so we don't fight Streamlit's internal styles.
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo+Black&display=swap');
.hero {display: grid; grid-template-columns: 1.1fr 1fr; gap: 1.75rem;
  align-items: end; margin: 0.5rem 0 1rem 0;}
.hero .title {font-family: 'Archivo Black', 'Archivo', sans-serif;
  font-size: 2.9rem; line-height: 0.98; letter-spacing: -0.02em;
  color: #EDE6DA; margin: 0 0 0.9rem 0;}
.hero .lede {font-size: 0.95rem; line-height: 1.55; color: #A39B8F;
  margin: 0; max-width: 34ch;}
.hero .example {background: #26231F; border: 1px solid #3A362F;
  padding: 1rem 1.1rem;}
.hero .example .q {font-size: 0.95rem; color: #EDE6DA; margin: 0 0 0.6rem 0;}
.hero .example .sql {font-family: 'JetBrains Mono', monospace; color: #CFC6B8;
  font-size: 0.74rem; line-height: 1.55; white-space: pre; margin: 0 0 0.7rem 0;}
.hero .example .a {font-weight: 700; color: #E8A33D; margin: 0;}
.facts {color: #A39B8F; font-size: 0.9rem; margin: 0 0 1.25rem 0;
  padding-top: 0.9rem; border-top: 1px solid #3A362F;}
.summary {color: #A39B8F; font-size: 0.85rem; border-left: 3px solid;
  padding-left: 0.6rem; margin: 0.1rem 0 0.6rem 0;}
.summary.ok {border-color: #6FBF73;}
.summary.blocked {border-color: #E5675C;}
.summary.warn {border-color: #E8A33D;}
@media (max-width: 640px) {
  .hero {grid-template-columns: 1fr;}
  .hero .title {font-size: 2.3rem;}
}
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_data
def dataset_facts() -> tuple:
    """Live numbers for the line under the header, read once from the database."""
    result = run_query(
        "SELECT (SELECT COUNT(*) FROM Invoice), (SELECT COUNT(*) FROM Customer), "
        "(SELECT COUNT(*) FROM Track), (SELECT MIN(YEAR(InvoiceDate)) FROM Invoice), "
        "(SELECT MAX(YEAR(InvoiceDate)) FROM Invoice)"
    )
    return tuple(result["rows"][0])


def unique_columns(columns: list) -> list:
    """Tables can't show two columns with the same name, so number repeats."""
    seen = {}
    result = []
    for col in columns:
        seen[col] = seen.get(col, 0) + 1
        result.append(col if seen[col] == 1 else f"{col}_{seen[col]}")
    return result


def is_chartable(table: pd.DataFrame) -> bool:
    """One label column + one number column, not too many rows: draw a bar chart."""
    return (
        table.shape[1] == 2
        and 1 < len(table) <= 25
        and pd.api.types.is_numeric_dtype(table.iloc[:, 1])
    )


def summary_line(result: dict, seconds: float) -> tuple:
    """One plain sentence about what happened, plus a CSS class for the strip."""
    queries = len(result["attempts"])
    retries = result["retries"]
    if result["status"] == "blocked":
        return f"Blocked before reaching the database ({seconds:.1f} s).", "blocked"
    if result["status"] == "api_error":
        return "Gemini did not respond. Try again in a minute.", "warn"
    if result["status"] == "failed":
        return f"No working query after {queries} attempts ({seconds:.1f} s).", "warn"
    if queries == 0:
        return f"Answered without running any SQL ({seconds:.1f} s).", "ok"
    query_word = "query" if queries == 1 else "queries"
    if retries == 0:
        retry_text = "no retries"
    else:
        retry_text = f"{retries} {'retry' if retries == 1 else 'retries'}"
    text = f"Answered in {seconds:.1f} s, {queries} SQL {query_word}, {retry_text}."
    return text, "ok"


def show_result(result: dict, seconds: float) -> None:
    text, css = summary_line(result, seconds)
    st.markdown(f"<p class='summary {css}'>{text}</p>", unsafe_allow_html=True)
    # Escape $ so amounts like $523.06 are not read as maths formatting.
    st.markdown(result["answer"].replace("$", "\\$"))

    if not result["attempts"]:
        return

    table = pd.DataFrame(result["rows"], columns=unique_columns(result["columns"]))
    tab_names = ["Table"] + (["Chart"] if is_chartable(table) else [])
    tabs = st.tabs(tab_names + ["SQL", "Retry history"])

    with tabs[0]:
        st.dataframe(table, hide_index=True)
        if result["truncated"]:
            st.caption("Showing the first 100 rows.")
    if "Chart" in tab_names:
        with tabs[1]:
            label_col, value_col = table.columns
            st.bar_chart(table, x=label_col, y=value_col, horizontal=True, color=AMBER)
    with tabs[-2]:
        st.code(result["sql"] or "-- no query succeeded", language="sql")
    with tabs[-1]:
        for i, attempt in enumerate(result["attempts"], start=1):
            outcome = "worked" if attempt["ok"] else f"failed ({attempt['error_type']})"
            st.markdown(f"**Attempt {i}** {outcome}")
            st.code(attempt["sql"], language="sql")
            if not attempt["ok"]:
                st.caption(attempt["error"])


# ---------- Page ----------

st.markdown(
    """
<div class='hero'>
<div>
<div class='title'>Text-to-SQL<br>Analyst</div>
<p class='lede'>Ask what sold, where and when in the Chinook music store.
Each question becomes one read-only SQL query that is checked before it runs.</p>
</div>
<div class='example'>
<p class='q'>“Which country spends the most?”</p>
<div class='sql'>SELECT BillingCountry,
       ROUND(SUM(Total), 2) AS revenue
FROM Invoice
GROUP BY BillingCountry
ORDER BY revenue DESC
LIMIT 1;</div>
<p class='a'>USA, 523.06</p>
</div>
</div>
""",
    unsafe_allow_html=True,
)

invoices, customers, tracks, first_year, last_year = dataset_facts()
st.markdown(
    f"<p class='facts'>The data: {invoices:,} invoices from "
    f"{customers:,} customers, covering {tracks:,} tracks, "
    f"{first_year} to {last_year}.</p>",
    unsafe_allow_html=True,
)

st.caption("Start with one of these questions")
clicked = None
for col, (label, prompt) in zip(st.columns(len(EXAMPLES)), EXAMPLES.items()):
    if col.button(label):
        clicked = prompt

with st.sidebar:
    st.subheader("About this app")
    st.markdown(
        f"Sales data from the Chinook music store, stored in DuckDB and queried "
        f"by a Gemini agent (`{MODEL}`) using function calling.\n\n"
        "**Guardrails**\n"
        "- Read-only database with no file access\n"
        "- Exactly one SELECT statement, checked with DuckDB's own parser\n"
        "- At most 100 rows and 10 seconds per query\n"
        "- SQL errors go back to the agent to fix, up to 3 retries\n"
        "- Unsafe SQL is blocked and never retried"
    )
    if st.button("Clear conversation"):
        st.session_state.history = []
        st.rerun()

if "history" not in st.session_state:
    st.session_state.history = []  # (question, result, seconds) from this session

for past_question, past_result, past_seconds in st.session_state.history:
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(past_question)
    with st.chat_message("assistant", avatar=":material/database:"):
        show_result(past_result, past_seconds)

question = st.chat_input("Ask about sales, customers, tracks or artists") or clicked
if question:
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(question)
    with st.chat_message("assistant", avatar=":material/database:"):
        with st.spinner("Writing the SQL, checking it and running it..."):
            start = time.perf_counter()
            result = ask(question)
            seconds = time.perf_counter() - start
        show_result(result, seconds)
    st.session_state.history.append((question, result, seconds))