"""Tests for annotate_time.py — time annotation stage of the annotated-PGN pipeline."""

from __future__ import annotations

import io

import chess.pgn
import pytest

from pipeline.features import annotate_time
from pipeline.ingest import audit_log

SAMPLE = """\
[Event "T"]
[Site "?"]
[White "A"]
[Black "B"]
[Result "1-0"]
[GameId "g1"]
[SourceEvent "E"]
[Corpus "freestyle"]
[StratumFormat "rapid"]

1. e4 { [%clk 0:09:55] } e5 { [%clk 0:09:52] } 2. Nf3 { [%clk 0:09:44] } Nc6 { [%clk 0:09:40] } 3. Bb5 { [%clk 0:09:30] } a6 { [%clk 0:09:20] } 1-0

[Event "T"]
[Site "?"]
[White "C"]
[Black "D"]
[Result "1-0"]
[GameId "g2"]
[SourceEvent "E"]
[Corpus "freestyle"]
[StratumFormat "rapid"]

1. d4 { [%clk 0:09:55] } d5 { [%clk 0:09:52] } 2. Nf3 { [%clk not-a-clock] } Nf6 { [%clk 0:09:40] } 3. c4 { [%clk 0:09:30] } e6 { [%clk 0:09:20] } 1-0

[Event "T"]
[Site "?"]
[White "E"]
[Black "F"]
[Result "1-0"]
[GameId "g3"]
[SourceEvent "E"]
[Corpus "freestyle"]
[StratumFormat "rapid"]

1. e4 e5 2. Nf3 Nc6 1-0
"""


def _load_sample() -> list[chess.pgn.Game]:
    games = []
    fh = io.StringIO(SAMPLE)
    while (g := chess.pgn.read_game(fh)) is not None:
        games.append(g)
    return games


def _plies_in_game(text: str, game_id: str) -> str:
    return text.split(f'[GameId "{game_id}"]')[1].split("[Event")[0]


# tag helpers


def test_with_tspent_places_tag_first_and_is_idempotent():
    c1 = annotate_time._with_tspent("[%clk 0:09:55]", 12.3)
    assert c1 == "[%tspent 12.30] [%clk 0:09:55]"
    c2 = annotate_time._with_tspent(c1, 9.87)  # re-annotate -> replaces, doesn't stack
    assert c2 == "[%tspent 9.87] [%clk 0:09:55]"
    assert c2.count("[%tspent") == 1


def test_with_tspent_no_prior_comment():
    assert annotate_time._with_tspent(None, 5.0) == "[%tspent 5.00]"
    assert annotate_time._with_tspent("", 5.0) == "[%tspent 5.00]"


# annotate_time_one_game


def test_annotate_one_game_full_coverage():
    g = _load_sample()[0]
    stats = annotate_time.annotate_time_one_game(g, increment=5.0, base_time=600.0)
    assert stats == {"played": 6, "tagged": 6}
    tags = [n.comment for n in g.mainline() if "%tspent" in (n.comment or "")]
    assert len(tags) == 6


def test_annotate_one_game_malformed_clock_breaks_chain():
    g = _load_sample()[1]
    stats = annotate_time.annotate_time_one_game(g, increment=5.0, base_time=600.0)
    # white's malformed clock breaks the chain for the next move too -> 1/3 tagged; black 3/3 -> 4 of 6 total
    assert stats["played"] == 6
    assert stats["tagged"] == 4


def test_annotate_one_game_clears_stale_tspent_on_uncomputable_ply():
    """An uncomputable ply must end up untagged even if it already carried a stale [%tspent] from a prior run."""
    g = _load_sample()[1]
    nodes = list(g.mainline())
    nodes[4].comment = "[%tspent 999.00] " + (nodes[4].comment or "")  # pre-seed a stale tag on an untaggable ply

    stats = annotate_time.annotate_time_one_game(g, increment=5.0, base_time=600.0)

    assert stats["tagged"] == 4  # unchanged - nothing new became computable
    assert "999.00" not in nodes[4].comment
    assert "%tspent" not in nodes[4].comment


def test_annotate_one_game_no_clocks_nothing_tagged():
    g = _load_sample()[2]
    stats = annotate_time.annotate_time_one_game(g, increment=5.0, base_time=600.0)
    assert stats["tagged"] == 0
    assert stats["played"] == 4


# annotate_time_games (full stratum pass)


def test_annotate_time_games_writes_pgn_and_preserves_clk(tmp_path):
    games = _load_sample()
    out = tmp_path / "time.pgn"
    summary = annotate_time.annotate_time_games(
        games, out, increment_seconds=5.0, base_seconds=600.0
    )
    text = out.read_text()

    assert text.count("[Event") == 3
    assert "[%tspent" in text and "[%clk" in text
    assert text.index("[%tspent") < text.index("[%clk")
    assert summary["n_games"] == 3
    assert summary["total_plies"] == 16
    assert 0 < summary["tagged_plies"] < 16


def test_annotate_time_games_per_game_ply_counts(tmp_path):
    games = _load_sample()
    out = tmp_path / "time.pgn"
    annotate_time.annotate_time_games(games, out, increment_seconds=5.0, base_seconds=600.0)
    text = out.read_text()
    assert _plies_in_game(text, "g1").count("[%tspent") == 6
    assert _plies_in_game(text, "g2").count("[%tspent") == 4
    assert _plies_in_game(text, "g3").count("[%tspent") == 0


def test_annotate_time_games_logs_no_increment_observation(tmp_path):
    games = _load_sample()
    out = tmp_path / "time.pgn"
    lp = tmp_path / "exclusions.parquet"
    annotate_time.annotate_time_games(games, out, log_path=lp)  # no increment source given -> every event unresolved
    obs = audit_log.read_observations(lp)
    assert (obs["note"].str.contains("no increment available", na=False)).any()
    assert out.exists()  # falls back to 0.0, never crashes


def test_annotate_time_games_increment_by_event_used(tmp_path):
    games = _load_sample()
    out = tmp_path / "time.pgn"
    lp = tmp_path / "exclusions.parquet"
    annotate_time.annotate_time_games(
        games, out, increment_by_event={"E": 5.0}, base_by_event={"E": 600.0}, log_path=lp
    )
    obs = audit_log.read_observations(lp)
    assert not (obs["note"].str.contains("no increment available", na=False)).any()  # resolved via the map
    text = out.read_text()
    assert _plies_in_game(text, "g1").count("[%tspent") == 6


def test_annotate_time_games_header_fallback_off_by_default(tmp_path):
    """A TimeControl header is ignored unless header_fallback=True (manifest is authoritative)."""
    pgn = (
        '[Event "T"]\n[White "A"]\n[Black "B"]\n[Result "1-0"]\n[GameId "gh"]\n'
        '[SourceEvent "H"]\n[TimeControl "600+5"]\n\n'
        "1. e4 { [%clk 0:09:55] } e5 { [%clk 0:09:52] } 1-0\n"
    )
    g = chess.pgn.read_game(io.StringIO(pgn))
    out = tmp_path / "time.pgn"
    lp = tmp_path / "exclusions.parquet"
    annotate_time.annotate_time_games([g], out, log_path=lp)
    obs = audit_log.read_observations(lp)
    assert (obs["note"].str.contains("no increment available", na=False)).any()

    out2 = tmp_path / "time2.pgn"
    annotate_time.annotate_time_games([g], out2, header_fallback=True)
    assert "[%tspent" in out2.read_text()


def test_annotate_time_games_idempotent_rerun(tmp_path):
    games = _load_sample()
    out = tmp_path / "time.pgn"
    annotate_time.annotate_time_games(games, out, increment_seconds=5.0, base_seconds=600.0)
    text1 = out.read_text()
    annotate_time.annotate_time_games(games, out, increment_seconds=5.0, base_seconds=600.0)  # re-run on the same annotated objects
    text2 = out.read_text()
    assert text1 == text2
    assert _plies_in_game(text2, "g1").count("[%tspent") == 6  # replaced, not duplicated


def test_annotate_time_games_empty_list(tmp_path):
    out = tmp_path / "time.pgn"
    summary = annotate_time.annotate_time_games([], out)
    assert summary["n_games"] == 0
    assert out.exists()
