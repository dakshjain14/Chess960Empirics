"""Tests for band_gap_builder."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline.banding import band_gap_builder as bg
from pipeline.tests.conftest import synthetic_games


@pytest.fixture(scope="module")
def games() -> pd.DataFrame:
    return synthetic_games(4000, seed=7)


# derive_bins


def test_derive_bins_clears_floor():
    rng = np.random.default_rng(0)
    vals = rng.normal(2400, 120, 600)
    edges = bg.derive_bins(vals, min_cell_count=20, starting_width=100)
    counts = np.histogram(vals, bins=edges)[0]
    assert counts.min() >= 20


def test_derive_bins_collapses_when_data_too_thin():
    edges = bg.derive_bins(np.array([2401.0, 2402.0, 2403.0]), min_cell_count=20, starting_width=100)
    assert len(edges) == 2  # single all-covering bin


def test_derive_bins_is_stateless():
    a = bg.derive_bins(np.arange(2000, 3000), 20, 100)
    b = bg.derive_bins(np.arange(2500, 3500), 20, 100)
    assert a[0] == 2000 and b[0] == 2500


# build_bands_c4c5 (C4)


def test_c4c5_one_row_per_game(games):
    res = bg.build_bands_c4c5(games)
    assert len(res.data) == len(games)


def test_c4c5_band_is_max_not_mean(games):
    """Picks a game whose mean and max Elo fall in different bands under
    the fixture's actual band_edges, and checks the assigned band matches
    the max-based bin, not the mean-based one — a band's lower bound alone
    can't distinguish the two (it's below both), so this needs a case where
    they actively disagree."""
    res = bg.build_bands_c4c5(games)
    edges = res.band_edges

    def band_index(v: float) -> int:
        idx = int(np.digitize([v], bins=edges, right=False)[0]) - 1
        return min(max(idx, 0), len(edges) - 2)

    max_elo = games[["white_elo", "black_elo"]].max(axis=1)
    mean_elo = games[["white_elo", "black_elo"]].mean(axis=1)
    max_idx = max_elo.map(band_index)
    mean_idx = mean_elo.map(band_index)
    disagreeing = games[max_idx != mean_idx]
    assert len(disagreeing) > 0, "fixture has no game whose mean/max Elo fall in different bands"

    g = disagreeing.iloc[0]
    expected_idx = band_index(max(g["white_elo"], g["black_elo"]))
    wrong_idx = band_index((g["white_elo"] + g["black_elo"]) / 2.0)
    assert expected_idx != wrong_idx

    row = res.data[res.data["game_id"] == g["game_id"]].iloc[0]
    actual_band = str(row["band"])
    expected_band = bg._bin_labels(edges)[expected_idx]
    wrong_band = bg._bin_labels(edges)[wrong_idx]
    assert actual_band == expected_band
    assert actual_band != wrong_band


# shared guarantees


def test_ordered_categoricals(games):
    res = bg.build_bands_c4c5(games)
    assert isinstance(res.data["band"].dtype, pd.CategoricalDtype)
    assert res.data["band"].cat.ordered


def test_boundaries_not_reused_across_datasets(games):
    shifted = games.copy()
    shifted["white_elo"] += 400
    shifted["black_elo"] += 400
    a = bg.build_bands_c4c5(games)
    b = bg.build_bands_c4c5(shifted)
    assert b.band_edges[0] > a.band_edges[0]


def test_drops_unparseable_elo(games):
    dirty = games.copy()
    dirty["white_elo"] = dirty["white_elo"].astype(object)
    dirty.loc[dirty.index[:15], "white_elo"] = "?"
    res = bg.build_bands_c4c5(dirty)
    assert len(res.data) == len(games) - 15
