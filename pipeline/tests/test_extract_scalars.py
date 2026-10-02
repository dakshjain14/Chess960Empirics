"""Tests for extract_scalars.py, which has no CLI entry point of its own — it's called by pipeline.run_pipeline."""

from __future__ import annotations

import io

import chess.pgn
import pytest

from pipeline.features.extract_scalars import extract_scalars

SAMPLE = """\
[Event "T"]
[Site "?"]
[White "A"]
[Black "B"]
[Result "1-0"]
[WhiteElo "2200"]
[BlackElo "2350"]
[GameId "g1"]
[SourceEvent "E"]
[SourceType "otb"]
[Corpus "standard"]
[StratumFormat "classical"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0

[Event "T"]
[Site "?"]
[White "C"]
[Black "D"]
[Result "1/2-1/2"]
[WhiteElo "2700"]
[BlackElo "2650"]
[GameId "g2"]
[SourceEvent "E"]
[SourceType "otb"]
[Corpus "standard"]
[StratumFormat "classical"]

1. d4 d5 2. Nf3 Nf6 1/2-1/2

[Event "T"]
[Site "?"]
[White "E"]
[Black "F"]
[Result "1-0"]
[WhiteElo "2400"]
[BlackElo "2450"]
[GameId "g3"]
[SourceEvent "E"]
[SourceType "otb"]
[Corpus "standard"]
[StratumFormat "classical"]

1. e4 e5 1-0
"""


@pytest.fixture()
def games():
    fh = io.StringIO(SAMPLE)
    parsed = []
    while (g := chess.pgn.read_game(fh)) is not None:
        parsed.append(g)
    return parsed


@pytest.fixture()
def df(games):
    return extract_scalars(games)


def test_one_row_per_game(df):
    assert len(df) == 3


def test_elo_and_result_carried_through(df):
    g1 = df.loc[df["game_id"] == "g1"].iloc[0]
    assert g1["white_elo"] == 2200 and g1["black_elo"] == 2350
    assert set(df["result"]) == {"1-0", "1/2-1/2"}


def test_provenance_columns_present(df):
    assert {"source_event", "source_type", "corpus", "format"}.issubset(df.columns)
