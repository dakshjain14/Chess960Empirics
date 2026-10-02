"""Tests for standard_rating_backfill.py's manual-candidate step (applied
before the automated FideId-based lookup)."""

from __future__ import annotations

import pandas as pd

from pipeline.ingest.standard_rating_backfill import (
    apply_manual_candidates,
    load_manual_candidates,
    manual_overrides_for_file,
    parse_tags,
    process_file,
)

SYNTHETIC_PGN = '''[Event "Test Open 2025"]
[Site "Testville"]
[Date "2025.06.01"]
[Round "1"]
[White "Misspeled, Playr"]
[Black "Known, Player"]
[Result "1-0"]
[BlackFideId "11111111"]
[BlackElo "2100"]

1. e4 e5 1-0
'''


def _write_candidates_xlsx(path, rows):
    pd.DataFrame(rows).to_excel(path, index=False)


def test_manual_candidate_corrects_name_id_and_rating(tmp_path):
    pgn_path = tmp_path / "test-open-2025.pgn"
    pgn_path.write_text(SYNTHETIC_PGN, encoding="utf-8")

    xlsx_path = tmp_path / "candidates.xlsx"
    _write_candidates_xlsx(xlsx_path, [{
        "PGN Name": "Misspeled, Playr",
        "Tournament (file)": "test-open-2025",
        "Month": "Jun25",
        "Rating Type Needed": "Rapid",
        "PGN Title": None,
        "Candidate FIDE Name": "Misspelled, Player",
        "FIDE Id": 22222222,
        "FIDE Federation": "USA",
        "FIDE Title": None,
        "FIDE Rating (that month)": 1800,
        "Notes / Confidence": "test row",
        "Verified? (Y/N)": None,
    }])

    candidates = load_manual_candidates(path=str(xlsx_path))
    assert len(candidates) == 1
    overrides = manual_overrides_for_file(pgn_path.name, candidates)
    assert len(overrides) == 1

    result = process_file(str(pgn_path), "Rapid", (2025, 6), overrides)
    assert result is not None
    assert result["n_manual"] == 1

    out_block = result["blocks"][0]
    tags = parse_tags(out_block)
    assert tags["White"] == "Misspelled, Player"
    assert tags["WhiteFideId"] == "22222222"
    assert tags["WhiteElo"] == "1800"
    # Black was already complete and must be untouched
    assert tags["Black"] == "Known, Player"
    assert tags["BlackFideId"] == "11111111"
    assert tags["BlackElo"] == "2100"

    assert candidates[0]["matched"] is True


def test_manual_candidate_with_unknown_rating_only_sets_id_not_elo(tmp_path):
    """A row with a FideId but no rating value (blank, not 0) should patch
    the name/id and leave Elo for the automated lookup, not write a
    fabricated '0'."""
    pgn_path = tmp_path / "test-open-2025.pgn"
    pgn_path.write_text(SYNTHETIC_PGN, encoding="utf-8")

    xlsx_path = tmp_path / "candidates.xlsx"
    _write_candidates_xlsx(xlsx_path, [{
        "PGN Name": "Misspeled, Playr",
        "Tournament (file)": "test-open-2025",
        "Month": "Jun25",
        "Rating Type Needed": "Rapid",
        "PGN Title": None,
        "Candidate FIDE Name": "Misspelled, Player",
        "FIDE Id": 22222222,
        "FIDE Federation": "USA",
        "FIDE Title": None,
        "FIDE Rating (that month)": None,
        "Notes / Confidence": "rating unknown",
        "Verified? (Y/N)": None,
    }])

    candidates = load_manual_candidates(path=str(xlsx_path))
    overrides = manual_overrides_for_file(pgn_path.name, candidates)

    block = SYNTHETIC_PGN.split("\n\n")[0]
    new_block, n_applied = apply_manual_candidates(block, overrides)
    tags = parse_tags(new_block)
    assert n_applied == 1
    assert tags["WhiteFideId"] == "22222222"
    assert "WhiteElo" not in tags  # left for the automated lookup


def test_unmatched_candidate_row_is_not_marked_matched(tmp_path):
    xlsx_path = tmp_path / "candidates.xlsx"
    _write_candidates_xlsx(xlsx_path, [{
        "PGN Name": "Nobody, Here",
        "Tournament (file)": "some-other-tournament-2025",
        "Month": "Jun25",
        "Rating Type Needed": "Rapid",
        "PGN Title": None,
        "Candidate FIDE Name": "Nobody, Here",
        "FIDE Id": 33333333,
        "FIDE Federation": "USA",
        "FIDE Title": None,
        "FIDE Rating (that month)": 1500,
        "Notes / Confidence": "should not match",
        "Verified? (Y/N)": None,
    }])

    candidates = load_manual_candidates(path=str(xlsx_path))
    overrides = manual_overrides_for_file("test-open-2025.pgn", candidates)
    assert overrides == []
    assert candidates[0]["matched"] is False
