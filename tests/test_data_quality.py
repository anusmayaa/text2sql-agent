"""Data-quality tests: the real data passes, and each check catches bad data."""
import duckdb
import pytest

from quality import (
    check_business_rules,
    check_foreign_keys,
    check_primary_keys,
    check_required_columns,
    check_row_counts,
)
from tools import con  # read-only connection to data/chinook.duckdb


def failures(results: list) -> list:
    return [r for r in results if not r[1]]


# --- The real Chinook data passes every check ---

def test_real_data_has_unique_primary_keys():
    assert failures(check_primary_keys(con)) == []


def test_real_data_has_no_missing_required_values():
    assert failures(check_required_columns(con)) == []


def test_real_data_has_no_orphaned_foreign_keys():
    assert failures(check_foreign_keys(con)) == []


def test_real_data_passes_business_rules():
    assert failures(check_business_rules(con)) == []


# --- Each check catches deliberately broken data ---

@pytest.fixture
def bad_db():
    """A tiny in-memory database with one problem of each kind."""
    db = duckdb.connect()  # in memory, nothing touches the real file
    db.execute("CREATE TABLE Artist (ArtistId INTEGER, Name VARCHAR)")
    db.execute("INSERT INTO Artist VALUES (1, 'A'), (1, 'A again'), (NULL, 'No id')")
    db.execute("CREATE TABLE Album (AlbumId INTEGER, Title VARCHAR, ArtistId INTEGER)")
    db.execute("INSERT INTO Album VALUES (10, NULL, 1), (11, 'Orphan', 99)")
    yield db
    db.close()


def test_duplicate_and_null_primary_keys_are_caught(bad_db):
    results = check_primary_keys(bad_db, {"Artist": ["ArtistId"]})
    assert failures(results)
    assert results[0][2] == "1 duplicates, 1 nulls"


def test_missing_required_value_is_caught(bad_db):
    results = check_required_columns(bad_db, {"Album": ["Title"]})
    assert results[0][2] == "1 nulls"


def test_orphaned_foreign_key_is_caught(bad_db):
    results = check_foreign_keys(bad_db, [("Album", "ArtistId", "Artist", "ArtistId")])
    assert results[0][2] == "1 orphan rows"


def test_row_count_mismatch_is_caught(bad_db):
    bad_db.execute("ATTACH ':memory:' AS src")
    bad_db.execute("CREATE TABLE src.Artist AS SELECT * FROM range(5)")
    results = check_row_counts(bad_db, ["Artist"])
    assert failures(results)
    assert results[0][2] == "source 5, target 3"