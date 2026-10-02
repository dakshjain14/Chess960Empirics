"""Tests for figures.figures — rendering-only checks: each function must produce a non-empty 300-DPI PNG and return a Figure."""

from __future__ import annotations

import matplotlib
import numpy as np
import pandas as pd
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from pipeline.figures import figures as fg  # noqa: E402


def _assert_png(path, fig):
    assert isinstance(fig, plt.Figure)
    assert path.exists() and path.stat().st_size > 5000
    plt.close(fig)


@pytest.fixture(scope="module")
def gradient_data():
    rng = np.random.default_rng(5)
    rows = []
    for corpus, slope in (("freestyle", -0.03), ("standard", -0.01)):
        for fmt in ("classical", "rapid"):
            n = 500
            ratings = rng.uniform(2000, 2800, n)
            acpl = 40 + slope * (ratings - 2000) + rng.normal(0, 5, n)
            rows.append(pd.DataFrame({
                "own_rating": ratings, "opening_acpl": np.clip(acpl, 0, None),
                "corpus": corpus, "format": fmt,
            }))
    game_features = pd.concat(rows, ignore_index=True)
    gradient_results = pd.DataFrame({
        "format": ["classical", "rapid"],
        "interaction_p_value": [1.1e-10, 2.2e-20],
    })
    return game_features, gradient_results


def test_rating_accuracy_gradient_plot(tmp_path, gradient_data):
    game_features, gradient_results = gradient_data
    p = tmp_path / "fig1.png"
    f = fg.rating_accuracy_gradient_plot(game_features, gradient_results, p)
    _assert_png(p, f)


def test_rating_accuracy_gradient_plot_is_300_dpi(tmp_path, gradient_data):
    from PIL import Image

    game_features, gradient_results = gradient_data
    p = tmp_path / "fig1_dpi.png"
    fg.rating_accuracy_gradient_plot(game_features, gradient_results, p)
    with Image.open(p) as im:
        dpi = im.info.get("dpi", (0, 0))
    assert round(dpi[0]) == 300


@pytest.fixture(scope="module")
def c5_outcomes():
    bins = ["0-100", "101-250", "251+"]
    # (chess960 win/draw/fav, standard win/draw/fav), each triple sums to 100
    shares = {
        "classical": [((15, 49, 36), (15, 59, 26)), ((14, 31, 55), (13, 43, 44)), ((7, 15, 78), (2, 24, 74))],
        "rapid": [((32, 24, 44), (27, 39, 34)), ((27, 19, 54), (19, 29, 52)), ((17, 9, 74), (11, 17, 72))],
    }
    rows = []
    for fmt, per_bin in shares.items():
        for b, (c960, std) in zip(bins, per_bin):
            rows.append({
                "format": fmt, "gap_bin": b, "chess960_n": 100, "standard_n": 100,
                "chess960_underdog_win_pct": c960[0], "chess960_draw_pct": c960[1], "chess960_favourite_win_pct": c960[2],
                "standard_underdog_win_pct": std[0], "standard_draw_pct": std[1], "standard_favourite_win_pct": std[2],
            })
    return pd.DataFrame(rows)


def test_outcome_stacked_bars(tmp_path, c5_outcomes):
    p = tmp_path / "fig2.png"
    f = fg.outcome_stacked_bars(c5_outcomes, p)
    _assert_png(p, f)
