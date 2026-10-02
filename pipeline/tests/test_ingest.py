"""End-to-end tests for the ingest layer."""

from __future__ import annotations

import io
from pathlib import Path

import chess.pgn
import pandas as pd
import pytest

from pipeline.config import (
    FREESTYLE_MANIFEST_PATH,
    MIN_ELO,
    STANDARD_MANIFEST_PATH,
    UPDATED_TIME_DIR,
)
from pipeline.ingest import audit_log, filters, manifest_loader

SAMPLE_DIR = Path(__file__).parent / "sample_pgns"


# audit_log


def test_audit_log_exclusion_roundtrip(tmp_path):
    lp = tmp_path / "x_exclusions.parquet"
    audit_log.log_exclusion(lp, "E", "e_00001", "freestyle", "rapid",
                            "anomaly_filter", "zero_ply", {"declared_plycount": "0"})
    audit_log.log_exclusion(lp, "E", "e_00002", "freestyle", "rapid",
                            "elo_filter", "elo_below_floor", {"white_elo": 1900})
    df = audit_log.read_exclusions(lp)
    assert list(df.columns) == list(audit_log.EXCLUSION_COLUMNS)
    assert len(df) == 2
    assert df["details"].str.contains("declared_plycount").any()


def test_audit_log_observation_is_separate_file(tmp_path):
    lp = tmp_path / "x_exclusions.parquet"
    audit_log.log_data_observation(lp, "manifest_row", "Ev", "something odd")
    assert audit_log.observations_path_for(lp).exists()
    assert not lp.exists()  # observations must not pollute the exclusion log


def test_build_event_summary_funnel(tmp_path):
    lp = tmp_path / "s_exclusions.parquet"
    audit_log.log_raw_game_count(lp, "EventA", "standard", "classical", 6)
    audit_log.log_exclusion(lp, "EventA", "a_1", "standard", "classical",
                            "anomaly_filter", "zero_ply")
    audit_log.log_exclusion(lp, "EventA", "a_2", "standard", "classical",
                            "elo_filter", "elo_below_floor", {"white_elo": 1850})
    man = pd.DataFrame([{"event": "EventA", "corpus": "standard", "format": "classical",
                         "source_type": "otb", "games": 6}])
    summ = audit_log.build_event_summary(lp, man, tmp_path / "none.parquet")
    row = summ[summ["event"] == "EventA"].iloc[0]
    assert row["total_games_in_file"] == 6
    assert row["excluded_zero_ply"] == 1
    assert row["excluded_elo_below_floor"] == 1
    assert row["final_games_analyzed"] == 0
    assert (summ["event"].str.startswith("__TOTAL__")).any()


# manifest_loader — real manifests


@pytest.fixture(scope="module")
def real_manifest(tmp_path_factory):
    obs = tmp_path_factory.mktemp("m") / "exclusions.parquet"
    return manifest_loader.load_manifest(
        FREESTYLE_MANIFEST_PATH, STANDARD_MANIFEST_PATH, observations_log=obs
    )


def test_manifest_concatenates_both_corpora(real_manifest):
    assert set(real_manifest["corpus"].unique()) == {"freestyle", "standard"}
    per_manifest = real_manifest.groupby("source_manifest").size()  # not hardcoded - manifests grow as events are split
    assert real_manifest.shape[0] == per_manifest.sum()
    assert (per_manifest > 0).all() and len(per_manifest) == 2


def test_manifest_normalises_vocab(real_manifest):
    assert set(real_manifest["format"].unique()) <= {"classical", "rapid"}
    assert set(real_manifest["source_type"].unique()) <= {"otb", "playin_online"}


def test_manifest_all_paths_resolve(real_manifest):
    assert real_manifest["filepath"].map(lambda p: Path(p).is_file()).all()


def test_manifest_game_id_prefixes_globally_unique(real_manifest):
    assert real_manifest["event_slug"].is_unique


def test_manifest_time_controls_prefers_pgn_column():
    """time_control_pgn is authoritative and PGN-format."""
    df = pd.DataFrame([
        {"event": "A", "time_control_pgn": "40/5400+30:1800+30", "timecontrol": "IGNORED"},
        {"event": "B", "time_control_pgn": "900+10"},
        {"event": "C", "time_control_pgn": "40/7200:0+10"},   # classical, no opening increment
        {"event": "D", "time_control_pgn": "?"},
    ])
    inc, base = manifest_loader.manifest_time_controls(df)
    assert inc == {"A": 30.0, "B": 10.0, "C": 0.0}
    assert base == {"A": 5400.0, "B": 900.0, "C": 7200.0}
    assert "D" not in inc and "D" not in base   # '?' contributes nothing


def test_manifest_time_controls_no_shorthand_fallback():
    """time_control_pgn is the only source - a shorthand column contributes nothing."""
    df = pd.DataFrame([
        {"event": "A", "time_control_pgn": "900+10", "timecontrol": "IGNORED", "base_minutes": 999},
        {"event": "B", "timecontrol": "90+30"},  # no time_control_pgn at all
    ])
    inc, base = manifest_loader.manifest_time_controls(df)
    assert inc == {"A": 10.0}
    assert base == {"A": 900.0}
    assert "B" not in inc and "B" not in base


def test_manifest_time_controls_on_real_manifests(real_manifest):
    for corpus in ("freestyle", "standard"):
        sub = real_manifest[real_manifest["corpus"] == corpus]
        inc, base = manifest_loader.manifest_time_controls(sub)
        assert len(inc) == len(sub) and len(base) == len(sub), corpus  # every event covered


def test_manifest_time_control_periods_matches_first_period():
    """The first period must agree with manifest_time_controls for the same event."""
    df = pd.DataFrame([{"event": "A", "time_control_pgn": "40/5400+30:1800+30"}])
    inc, base = manifest_loader.manifest_time_controls(df)
    periods = manifest_loader.manifest_time_control_periods(df)
    assert periods["A"] == [(40, 5400.0, 30.0), (None, 1800.0, 30.0)]
    assert periods["A"][0][1:] == (base["A"], inc["A"])


def test_manifest_time_control_periods_on_real_manifests(real_manifest):
    for corpus in ("freestyle", "standard"):
        sub = real_manifest[real_manifest["corpus"] == corpus]
        periods = manifest_loader.manifest_time_control_periods(sub)
        assert len(periods) == len(sub), corpus  # every event covered


def test_manifest_playin_source_type(real_manifest):
    playin = real_manifest[
        (real_manifest["corpus"] == "freestyle")
        & (real_manifest["source_type"] == "playin_online")
    ]
    assert len(playin) == 10


@pytest.mark.skipif(not UPDATED_TIME_DIR.exists(), reason="Updated_Time/ is gitignored, not present on a fresh clone")
def test_load_corpus_tags_and_ids(real_manifest, tmp_path):
    fr = real_manifest[
        (real_manifest["corpus"] == "freestyle") & (real_manifest["format"] == "rapid")
    ]
    one = real_manifest[real_manifest["event"] == fr.loc[fr["games"].idxmin(), "event"]]
    lp = tmp_path / "lc_exclusions.parquet"
    games = manifest_loader.load_corpus(one, "freestyle", "rapid", log_path=lp)
    assert len(games) > 0
    assert all(g.headers.get("SourceEvent") for g in games)
    assert all(g.headers.get("SourceType") == "otb" for g in games)
    assert len({g.headers["GameId"] for g in games}) == len(games)
    obs = audit_log.read_observations(lp)
    assert (obs["note"] == "raw_game_count").any()


@pytest.mark.skipif(not UPDATED_TIME_DIR.exists(), reason="Updated_Time/ is gitignored, not present on a fresh clone")
def test_load_corpus_source_type_filter(real_manifest, tmp_path):
    full = manifest_loader.load_corpus(real_manifest, "freestyle", "rapid",
                                       log_path=tmp_path / "a.parquet")
    otb_only = manifest_loader.load_corpus(real_manifest, "freestyle", "rapid",
                                          source_type="otb", log_path=tmp_path / "b.parquet")
    assert len(otb_only) < len(full)
    assert all(g.headers["SourceType"] == "otb" for g in otb_only)


# filters — hand-built samples


def _load_sample(name: str) -> list[chess.pgn.Game]:
    games = []
    with open(SAMPLE_DIR / name, encoding="utf-8") as fh:
        while (g := chess.pgn.read_game(fh)) is not None:
            # stamp the headers that manifest_loader would add
            g.headers.setdefault("SourceEvent", g.headers.get("Event", "?"))
            g.headers.setdefault("GameId", f"sample_{len(games):05d}")
            g.headers.setdefault("Corpus", "freestyle" if "Chess960" in str(g.headers) else "standard")
            g.headers.setdefault("StratumFormat", "rapid")
            games.append(g)
    return games


def test_filters_standard_sample_funnel(tmp_path):
    lp = tmp_path / "std_exclusions.parquet"
    games = _load_sample("standard_classical_sample.pgn")
    for g in games:
        g.headers["Corpus"] = "standard"
        g.headers["StratumFormat"] = "classical"
    assert len(games) == 6

    a = filters.filter_broadcast_anomalies(games, lp)
    b = filters.filter_by_elo(a, MIN_ELO, lp)

    excl = audit_log.read_exclusions(lp)
    by_reason = excl["reason"].value_counts().to_dict()

    assert by_reason.get("zero_ply") == 1          # sc005
    assert by_reason.get("elo_below_floor") == 1   # sc004 (1850)
    assert by_reason.get("elo_unparseable", 0) == 0
    # sc001, sc002, sc003, sc006 survive (no clock-presence filter)
    assert len(b) == 4
    assert {g.headers["GameId"] for g in b} == {
        g.headers["GameId"] for g in games[:3] + games[5:6]
    }
    assert (excl["stage"].isin(list(audit_log.STAGES))).all()


def test_filters_freestyle_missing_fen(tmp_path):
    lp = tmp_path / "fs_exclusions.parquet"
    games = _load_sample("freestyle_rapid_sample.pgn")
    for g in games:
        g.headers["Corpus"] = "freestyle"
        g.headers["StratumFormat"] = "rapid"
    # the sample game with no FEN and Corpus=freestyle -> missing_fen
    filters.filter_broadcast_anomalies(games, lp)
    excl = audit_log.read_exclusions(lp)
    assert (excl["reason"] == "missing_fen").sum() == 1


def test_filter_duplicate_game_id(tmp_path):
    lp = tmp_path / "dup_exclusions.parquet"
    games = _load_sample("standard_classical_sample.pgn")[:2]
    for g in games:
        g.headers["Corpus"] = "standard"
        g.headers["StratumFormat"] = "classical"
        g.headers["GameId"] = "collide_00000"  # force a collision
        g.headers["SourceEvent"] = "DupEvent"
    kept = filters.filter_broadcast_anomalies(games, lp)
    assert len(kept) == 1
    excl = audit_log.read_exclusions(lp)
    assert (excl["reason"] == "duplicate_game_id").sum() == 1


def test_filter_unplayed_forfeit_single_ply_with_timeout(tmp_path):
    """A single-ply game with Termination='timeout' is still an unplayed forfeit; a legit short game must NOT be flagged."""
    lp = tmp_path / "forfeit_exclusions.parquet"
    pgn = """\
[Event "T"]
[White "N"]
[Black "O"]
[Result "1-0"]
[Termination "timeout"]
[WhiteElo "2600"]
[BlackElo "2550"]
[Corpus "standard"]
[StratumFormat "classical"]
[SourceEvent "T"]
[GameId "forfeit_00000"]

1. e4 { [%clk 0:59:50] } 1-0

[Event "T"]
[White "P"]
[Black "Q"]
[Result "1-0"]
[WhiteElo "2600"]
[BlackElo "2550"]
[Corpus "standard"]
[StratumFormat "classical"]
[SourceEvent "T"]
[GameId "legit_00000"]

1. e4 { [%clk 0:59:50] } e5 { [%clk 0:59:48] } 2. Nf3 { [%clk 0:59:40] } 1-0
"""
    games = []
    fh = io.StringIO(pgn)
    while (g := chess.pgn.read_game(fh)) is not None:
        games.append(g)

    kept = filters.filter_broadcast_anomalies(games, lp)
    assert {g.headers["GameId"] for g in kept} == {"legit_00000"}
    excl = audit_log.read_exclusions(lp)
    assert (excl["reason"] == "unplayed_forfeit").sum() == 1


def test_filter_elo_unparseable(tmp_path):
    lp = tmp_path / "elo_exclusions.parquet"
    pgn = """\
[Event "T"]
[White "J"]
[Black "K"]
[Result "1-0"]
[WhiteElo "?"]
[BlackElo "2550"]
[Corpus "standard"]
[StratumFormat "classical"]
[SourceEvent "T"]
[GameId "t_00003"]

1. e4 { [%clk 0:59:50] } e5 { [%clk 0:59:48] } 1-0
"""
    g = chess.pgn.read_game(io.StringIO(pgn))
    kept = filters.filter_by_elo([g], MIN_ELO, lp)
    assert kept == []
    excl = audit_log.read_exclusions(lp)
    assert (excl["reason"] == "elo_unparseable").sum() == 1


def test_filters_never_raise_on_empty():
    assert filters.filter_broadcast_anomalies([]) == []
    assert filters.filter_by_elo([]) == []
