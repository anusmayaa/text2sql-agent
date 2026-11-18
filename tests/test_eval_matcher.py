"""Tests for the eval scoring, so the accuracy number can be trusted."""
from decimal import Decimal

from run_eval import results_match


def test_tied_rows_in_a_different_order_still_match():
    gold = [("USA", 13), ("Brazil", 5), ("France", 5)]
    agent = [("USA", 13), ("France", 5), ("Brazil", 5)]
    assert results_match(gold, agent)


def test_extra_columns_and_float_noise_are_ignored():
    gold = [("USA", Decimal("523.06"))]
    agent = [(1, "USA", 523.0600000000003)]
    assert results_match(gold, agent)


def test_first_and_last_name_match_a_full_name_column():
    gold = [("Helena", "Holý", 49.62)]
    agent = [("Helena Holý", 49.62)]
    assert results_match(gold, agent)


def test_wrong_value_fails():
    assert not results_match([("USA", 13)], [("USA", 12)])


def test_missing_row_fails():
    assert not results_match([("USA", 13), ("Canada", 8)], [("USA", 13)])