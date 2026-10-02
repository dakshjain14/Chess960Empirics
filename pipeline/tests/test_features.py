"""Tests for clock_parser.py."""

from __future__ import annotations

import pytest

from pipeline.features import clock_parser


def test_extract_clock_seconds():
    assert clock_parser.extract_clock_seconds("[%clk 0:10:03]") == 603.0
    assert clock_parser.extract_clock_seconds("[%clk 1:00:00]") == 3600.0
    assert clock_parser.extract_clock_seconds("[%clk 12:45]") == 765.0
    assert clock_parser.extract_clock_seconds("[%clk 0:00:04.5]") == 4.5
    assert clock_parser.extract_clock_seconds("[%clk not-a-clock]") is None
    assert clock_parser.extract_clock_seconds("[%clk 0:09:99]") is None  # out of range
    assert clock_parser.extract_clock_seconds("") is None
    assert clock_parser.extract_clock_seconds(None) is None


@pytest.mark.parametrize("tc,expected", [
    ("600+5", (600.0, 5.0)),
    ("5400", (5400.0, 0.0)),
    ("180+2", (180.0, 2.0)),
    ("?", (None, None)),
    ("-", (None, None)),
    ("40/7200", (7200.0, 0.0)),
    ("40/7200:0+10", (7200.0, 0.0)),            # no increment in the first 40 moves
    ("40/5400+30:1800+30", (5400.0, 30.0)),     # first period of a composite
    ("40/1200:0+2", (1200.0, 0.0)),
    ("*1200", (1200.0, 0.0)),                   # hourglass
    ("garbage", (None, None)),
])
def test_parse_pgn_time_control(tc, expected):
    assert clock_parser.parse_pgn_time_control(tc) == expected
