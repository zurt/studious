from __future__ import annotations

import pytest

from app.services.range_parser import parse_pages


def test_all_keyword():
    assert parse_pages("all", 5) == [1, 2, 3, 4, 5]


def test_all_implicit_when_empty():
    assert parse_pages("", 3) == [1, 2, 3]
    assert parse_pages(None, 3) == [1, 2, 3]


def test_simple_range():
    assert parse_pages("1-3", 5) == [1, 2, 3]


def test_mixed_spec_dedupes_and_sorts():
    assert parse_pages("3, 1-2, 5, 4", 5) == [1, 2, 3, 4, 5]
    assert parse_pages("1-3, 2-4", 5) == [1, 2, 3, 4]


def test_whitespace_tolerated():
    assert parse_pages("  1 - 3 ,  5  ", 5) == [1, 2, 3, 5]


def test_single_page():
    assert parse_pages("7", 10) == [7]


def test_out_of_range():
    with pytest.raises(ValueError):
        parse_pages("11", 10)
    with pytest.raises(ValueError):
        parse_pages("1-11", 10)


def test_invalid_tokens():
    with pytest.raises(ValueError):
        parse_pages("a-b", 5)
    with pytest.raises(ValueError):
        parse_pages("foo", 5)


def test_zero_disallowed():
    with pytest.raises(ValueError):
        parse_pages("0", 5)
    with pytest.raises(ValueError):
        parse_pages("0-2", 5)


def test_inverted_range():
    with pytest.raises(ValueError):
        parse_pages("5-2", 10)
