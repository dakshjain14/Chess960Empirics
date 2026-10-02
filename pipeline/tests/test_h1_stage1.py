"""Tests for h1_stage1_extract_per_move.py."""

from __future__ import annotations

import io

import chess.pgn
import pandas as pd

from pipeline.analysis.h1_stage1_extract_per_move import CPL_CAP, PER_MOVE_COLUMNS, extract_game_rows

# g1: 3 full moves both sides, clean eval+tspent chain throughout.
# g2: mate score on move 2, tests mate-CPL mapping.
# g3: no [%eval] at all (past opening window / no-analysis game) -> cpl
#     always null, time_spent still populated.
SAMPLE = """\
[Event "T"]
[Site "?"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]
[WhiteElo "2400"]
[BlackElo "2350"]
[GameId "g1"]
[SourceEvent "E"]
[Corpus "standard"]
[StratumFormat "classical"]
[SourceType "otb"]

1. e4 { [%eval 0.20] [%tspent 5.00] } e5 { [%eval 0.15] [%tspent 4.00] } 2. Nf3 { [%eval 0.30] [%tspent 6.00] } Nc6 { [%eval 0.25] [%tspent 3.00] } 3. Bb5 { [%eval 0.40] [%tspent 8.00] } a6 { [%eval 0.35] [%tspent 7.00] } 1-0

[Event "T"]
[Site "?"]
[White "Carol"]
[Black "Dave"]
[Result "1-0"]
[WhiteElo "2500"]
[BlackElo "2450"]
[GameId "g2"]
[SourceEvent "E"]
[Corpus "standard"]
[StratumFormat "classical"]
[SourceType "playin_online"]

1. e4 { [%eval 0.20] [%tspent 5.00] } e5 { [%eval 0.15] [%tspent 4.00] } 2. Qh5 { [%eval #-5] [%tspent 6.00] } 1-0

[Event "T"]
[Site "?"]
[White "Eve"]
[Black "Frank"]
[Result "1-0"]
[WhiteElo "2200"]
[BlackElo "2250"]
[GameId "g3"]
[SourceEvent "E"]
[Corpus "standard"]
[StratumFormat "classical"]

1. d4 { [%tspent 3.00] } d5 { [%tspent 2.00] } 1-0
"""


def _sample_df() -> pd.DataFrame:
    games = []
    fh = io.StringIO(SAMPLE)
    while (g := chess.pgn.read_game(fh)) is not None:
        games.append(g)
    rows = []
    for g in games:
        rows.extend(extract_game_rows(g))
    return pd.DataFrame(rows, columns=list(PER_MOVE_COLUMNS))


def test_g1_six_rows_three_full_moves_both_sides():
    df = _sample_df()
    assert len(df[df.game_id == "g1"]) == 6


def test_white_move1_cpl_null_no_starting_position_eval():
    df = _sample_df()
    g1_white = df[(df.game_id == "g1") & (df.side == "white")].reset_index(drop=True)
    assert pd.isna(g1_white.loc[0, "cpl"])


def test_white_move2_cpl_computed():
    df = _sample_df()
    g1_white = df[(df.game_id == "g1") & (df.side == "white")].reset_index(drop=True)
    assert pd.notna(g1_white.loc[1, "cpl"])


def test_black_move1_cpl_computed_from_whites_move1_eval():
    df = _sample_df()
    g1_black = df[(df.game_id == "g1") & (df.side == "black")].reset_index(drop=True)
    assert pd.notna(g1_black.loc[0, "cpl"])


def test_time_spent_always_populated_when_tspent_present():
    df = _sample_df()
    g1 = df[df.game_id == "g1"]
    assert g1["time_spent"].notna().all()


def test_own_and_opponent_rating_correct_both_sides():
    df = _sample_df()
    g1_white = df[(df.game_id == "g1") & (df.side == "white")].reset_index(drop=True)
    g1_black = df[(df.game_id == "g1") & (df.side == "black")].reset_index(drop=True)
    assert g1_white.loc[0, "own_rating"] == 2400 and g1_white.loc[0, "opponent_rating"] == 2350
    assert g1_black.loc[0, "own_rating"] == 2350 and g1_black.loc[0, "opponent_rating"] == 2400


def test_mate_score_maps_to_cap_and_clamps_cpl():
    df = _sample_df()
    g2 = df[df.game_id == "g2"].reset_index(drop=True)
    assert g2[(g2.side == "white") & (g2.move_number == 2)]["cpl"].iloc[0] == float(CPL_CAP)


def test_g3_no_eval_anywhere_cpl_always_null_but_time_spent_populated():
    df = _sample_df()
    g3 = df[df.game_id == "g3"].reset_index(drop=True)
    assert g3["cpl"].isna().all()
    assert g3["time_spent"].notna().all()


def test_move_number_is_per_side_own_move_count():
    df = _sample_df()
    g1_white = df[(df.game_id == "g1") & (df.side == "white")].reset_index(drop=True)
    assert list(g1_white["move_number"]) == [1, 2, 3]


def test_source_type_carried_through():
    df = _sample_df()
    g1 = df[df.game_id == "g1"]
    g2 = df[df.game_id == "g2"]
    assert (g1["source_type"] == "otb").all()
    assert (g2["source_type"] == "playin_online").all()
