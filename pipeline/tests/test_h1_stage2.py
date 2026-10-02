"""Tests for h1_stage2_aggregate_game_features.py."""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.analysis.h1_stage2_aggregate_game_features import GAME_FEATURE_COLUMNS, aggregate_game_features


def _sample_df() -> pd.DataFrame:
    sample = pd.DataFrame(
        [
            # white: move 1 cpl null (Stage 1 convention), moves 2-3 real; all 3 fall in this test's opening_moves=3 window
            {"game_id": "g1", "source_event": "E", "corpus": "standard", "format": "classical",
             "side": "white", "player_name": "Alice", "move_number": 1, "cpl": np.nan, "time_spent": 5.0,
             "own_rating": 2400, "opponent_rating": 2350},
            {"game_id": "g1", "source_event": "E", "corpus": "standard", "format": "classical",
             "side": "white", "player_name": "Alice", "move_number": 2, "cpl": 10.0, "time_spent": 6.0,
             "own_rating": 2400, "opponent_rating": 2350},
            {"game_id": "g1", "source_event": "E", "corpus": "standard", "format": "classical",
             "side": "white", "player_name": "Alice", "move_number": 3, "cpl": 20.0, "time_spent": 8.0,
             "own_rating": 2400, "opponent_rating": 2350},
            # white move 4: past the opening window, must NOT count toward opening_acpl
            {"game_id": "g1", "source_event": "E", "corpus": "standard", "format": "classical",
             "side": "white", "player_name": "Alice", "move_number": 4, "cpl": 999.0, "time_spent": 3.0,
             "own_rating": 2400, "opponent_rating": 2350},
            {"game_id": "g1", "source_event": "E", "corpus": "standard", "format": "classical",
             "side": "black", "player_name": "Bob", "move_number": 1, "cpl": 4.0, "time_spent": 4.0,
             "own_rating": 2350, "opponent_rating": 2400},
            {"game_id": "g1", "source_event": "E", "corpus": "standard", "format": "classical",
             "side": "black", "player_name": "Bob", "move_number": 2, "cpl": 6.0, "time_spent": 3.0,
             "own_rating": 2350, "opponent_rating": 2400},
            {"game_id": "g1", "source_event": "E", "corpus": "standard", "format": "classical",
             "side": "black", "player_name": "Bob", "move_number": 3, "cpl": 8.0, "time_spent": 7.0,
             "own_rating": 2350, "opponent_rating": 2400},
            # g2: zero total time -> otr must be null, not inf/zero
            {"game_id": "g2", "source_event": "E", "corpus": "standard", "format": "classical",
             "side": "white", "player_name": "Carol", "move_number": 1, "cpl": np.nan, "time_spent": np.nan,
             "own_rating": 2500, "opponent_rating": 2450},
            # g3: zero coverage anywhere in the game -> otr must be null, not a spurious 0/total
            {"game_id": "g3", "source_event": "E", "corpus": "standard", "format": "classical",
             "side": "white", "player_name": "Dave", "move_number": 1, "cpl": np.nan, "time_spent": np.nan,
             "own_rating": 2200, "opponent_rating": 2150},
            {"game_id": "g3", "source_event": "E", "corpus": "standard", "format": "classical",
             "side": "white", "player_name": "Dave", "move_number": 4, "cpl": 5.0, "time_spent": 40.0,
             "own_rating": 2200, "opponent_rating": 2150},
            # g4: opening window (moves 1-3) fully covered, but move 4 (outside the window) is
            # missing -> complete-case otr must still be null, since the whole-game denominator
            # is incomplete even though every input to opening_acpl/opening_time is present
            {"game_id": "g4", "source_event": "E", "corpus": "standard", "format": "classical",
             "side": "white", "player_name": "Erin", "move_number": 1, "cpl": 2.0, "time_spent": 2.0,
             "own_rating": 2300, "opponent_rating": 2250},
            {"game_id": "g4", "source_event": "E", "corpus": "standard", "format": "classical",
             "side": "white", "player_name": "Erin", "move_number": 2, "cpl": 3.0, "time_spent": 3.0,
             "own_rating": 2300, "opponent_rating": 2250},
            {"game_id": "g4", "source_event": "E", "corpus": "standard", "format": "classical",
             "side": "white", "player_name": "Erin", "move_number": 3, "cpl": 4.0, "time_spent": 4.0,
             "own_rating": 2300, "opponent_rating": 2250},
            {"game_id": "g4", "source_event": "E", "corpus": "standard", "format": "classical",
             "side": "white", "player_name": "Erin", "move_number": 4, "cpl": 5.0, "time_spent": np.nan,
             "own_rating": 2300, "opponent_rating": 2250},
        ]
    )
    sample["source_type"] = sample["game_id"].map(
        {"g1": "otb", "g2": "playin_online", "g3": "otb", "g4": "otb"}
    )  # varied per game to verify it's carried through
    return sample


def _out():
    return aggregate_game_features(_sample_df(), opening_moves=3)


def test_white_opening_acpl_excludes_null_move1():
    out = _out()
    g1w = out[(out.game_id == "g1") & (out.side == "white")].iloc[0]
    assert abs(g1w["opening_acpl"] - 15.0) < 1e-9


def test_black_opening_acpl_uses_all_three_moves():
    out = _out()
    g1b = out[(out.game_id == "g1") & (out.side == "black")].iloc[0]
    assert abs(g1b["opening_acpl"] - 6.0) < 1e-9


def test_white_otr_opening_over_total_time():
    out = _out()
    g1w = out[(out.game_id == "g1") & (out.side == "white")].iloc[0]
    assert abs(g1w["otr"] - 19 / 22) < 1e-9


def test_gap_signed_correct_sign_both_sides():
    out = _out()
    g1w = out[(out.game_id == "g1") & (out.side == "white")].iloc[0]
    g1b = out[(out.game_id == "g1") & (out.side == "black")].iloc[0]
    assert g1w["gap_signed"] == 50
    assert g1b["gap_signed"] == -50


def test_zero_total_time_otr_is_nan():
    out = _out()
    g2w = out[(out.game_id == "g2") & (out.side == "white")].iloc[0]
    assert pd.isna(g2w["otr"])


def test_zero_opening_window_coverage_otr_is_nan_not_spurious_zero():
    out = _out()
    g3w = out[(out.game_id == "g3") & (out.side == "white")].iloc[0]
    assert pd.isna(g3w["otr"])
    assert g3w["full_clock_coverage"] == False  # noqa: E712


def test_complete_case_otr_null_despite_full_opening_window_coverage():
    """g4 white has every opening-window move tagged but is missing one
    move later in the game — otr must still be null under the complete-case
    rule, since a partial whole-game denominator is unreliable regardless of
    where in the game the gap falls."""
    out = _out()
    g4w = out[(out.game_id == "g4") & (out.side == "white")].iloc[0]
    assert g4w["full_clock_coverage"] == False  # noqa: E712
    assert pd.isna(g4w["otr"])
    assert not pd.isna(g4w["opening_acpl"])  # opening_acpl is unaffected by whole-game coverage


def test_output_columns_match_spec():
    out = _out()
    assert list(out.columns) == list(GAME_FEATURE_COLUMNS)


def test_one_row_per_game_side():
    out = _out()
    assert len(out) == 5


def test_source_type_carried_through_per_game():
    out = _out()
    g1w = out[(out.game_id == "g1") & (out.side == "white")].iloc[0]
    g2w = out[(out.game_id == "g2") & (out.side == "white")].iloc[0]
    assert g1w["source_type"] == "otb"
    assert g2w["source_type"] == "playin_online"
