"""Tests for hypothesis_tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline.analysis import hypothesis_tests as ht

# --- shared utilities -----------------------------------------------------


def test_bootstrap_ci_brackets_and_close():
    data = np.random.default_rng(1).normal(5, 1, 400)
    pt, lo, hi = ht.bootstrap_ci(data, np.mean, n_iterations=2000)
    assert lo < pt < hi and abs(pt - 5) < 0.3


def test_bootstrap_ci_empty_is_nan():
    pt, lo, hi = ht.bootstrap_ci(np.array([]), np.mean)
    assert all(np.isnan(x) for x in (pt, lo, hi))


@pytest.mark.parametrize("k,n", [(0, 10), (10, 10), (5, 100), (1, 3)])
def test_wilson_ci_valid_bounds(k, n):
    lo, hi = ht.wilson_ci(k, n)
    assert -1e-9 <= lo <= hi <= 1 + 1e-9


# --- rating-accuracy gradient ------------------------------------------


def test_rating_accuracy_gradient_shape_and_effect():
    rng = np.random.default_rng(7)
    n = 800
    ratings = rng.uniform(2000, 2800, n)
    players = [f"P{i}" for i in range(n)]
    c960 = pd.DataFrame({"own_rating": ratings, "format": "classical", "player_name": players,
                          "opening_acpl": 60 - 0.03 * (ratings - 2000) + rng.normal(0, 5, n)})
    std = pd.DataFrame({"own_rating": ratings, "format": "classical", "player_name": players,
                         "opening_acpl": 30 - 0.005 * (ratings - 2000) + rng.normal(0, 3, n)})
    out = ht.test_rating_accuracy_gradient(c960, std, "classical")
    assert len(out) == 1
    assert out.loc[0, "corpus_chess960_n"] == n and out.loc[0, "corpus_standard_n"] == n
    # chess960 given the steeper (more negative) injected slope
    assert out.loc[0, "chess960_slope"] < out.loc[0, "standard_slope"]
    assert out.loc[0, "corpus_chess960_r"] < 0 and out.loc[0, "corpus_standard_r"] < 0


def test_rating_accuracy_gradient_empty_input_safe():
    empty = pd.DataFrame({"own_rating": [], "format": [], "opening_acpl": [], "player_name": []})
    assert len(ht.test_rating_accuracy_gradient(empty, empty, "classical")) == 0
