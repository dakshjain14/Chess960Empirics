"""Synthetic-data coverage for modules with none: c4_elo_scale's
fractional-score model, C4's pooled-interaction sign (hypothesis_tests),
C3's AME sign (c3_close_game_drawrate), Claim 4's descriptive outcomes
table (c5_bin_table), Claim 4's primary test (c5_upset_tests), the band x corpus interaction test
(h1_band_tests), the outcome-volatility formula (volatility), and Stage 4's
per-cell statistics (h1_stage4_hypothesis_tests). Each test checks
direction/sign against a known injected effect, not exact values — these are
not a substitute for reading the real-data result CSVs, just a guard against
the model sign flipping or the per-cell plumbing silently breaking."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline import config
from pipeline.analysis import h1_stage4_hypothesis_tests as h4
from pipeline.analysis import hypothesis_tests as ht
from pipeline.analysis.c4_elo_scale import _fit, _more_predictable_note, _pooled, _prep
from pipeline.analysis.c5_bin_table import BIN_LABELS, outcomes_table
from pipeline.analysis.c3_close_game_drawrate import fit_ame
from pipeline.analysis import c3_close_game_drawrate as c3
from pipeline.analysis.c5_upset_tests import GAP_MAX as C5_GAP_MAX
from pipeline.analysis.c5_upset_tests import fit_ame as c5_fit_ame
from pipeline.analysis.c5_upset_tests import load_close
from pipeline.analysis import c5_upset_tests as c5
from pipeline.analysis.h1_band_tests import _band_diff_table, _interaction_test
from pipeline.analysis.volatility import _var_from_w_d
from pipeline.config import MIN_CELL_COUNT
from pipeline.tests.conftest import synthetic_two_corpora

_WHITE, _BLACK, _DRAW = "1-0", "0-1", "1/2-1/2"


# --- C4: hypothesis_tests.test_c4_interaction ------------------------------


def test_c4_interaction_sign_on_injected_flatter_corpus():
    """synthetic_two_corpora's chess960 side has its Elo/outcome relationship
    deliberately flattened (chaos=True) relative to standard — the
    interaction coefficient (coded standard-minus-chess960) should come out
    positive and significant on a sample this size/effect."""
    c960, std = synthetic_two_corpora(5000, seed=11)
    out = ht.test_c4_interaction(c960, std)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["standard_gap_coef"] > row["chess960_gap_coef"]
    assert row["interaction_coefficient"] > 0
    assert row["interaction_p_value"] < 0.01


# --- C4: c4_elo_scale's primary fractional-logit expected-score model -----


def _synthetic_scalars(chaos: bool, n: int = 2000, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n_players = 60
    pool = np.clip(rng.normal(2450, 170, n_players), 2000, 2900).round().astype(int)
    rows = []
    for i in range(n):
        wi, bi = rng.integers(0, n_players, 2)
        while bi == wi:
            bi = rng.integers(0, n_players)
        we, be = int(pool[wi]), int(pool[bi])
        exp = 1 / (1 + 10 ** (-(we - be) / 400))
        if chaos:
            exp = 0.5 + (exp - 0.5) * 0.5
        r = rng.random()
        res = _DRAW if r < 0.1 else (_WHITE if rng.random() < exp else _BLACK)
        rows.append({
            "white_player": f"P{wi}", "black_player": f"P{bi}",
            "white_elo": we, "black_elo": be, "result": res,
        })
    return pd.DataFrame(rows)


def test_more_predictable_note_sign_mapping():
    """coef > 0 means standard's slope exceeds chess960's (coef =
    standard_slope - chess960_slope), i.e. chess960's outcome is predicted
    less strongly by rating gap -> chess960 is the LESS predictable one."""
    assert "Chess960" in _more_predictable_note(0.01, 0.01, "classical")
    assert "standard chess" in _more_predictable_note(-0.01, 0.01, "classical")
    assert "no significant difference" in _more_predictable_note(0.01, 0.5, "classical")


def test_c4_elo_scale_expected_score_flatter_for_chaos_corpus():
    """The stronger player's expected score at a fixed gap should be closer
    to 50% (less predictable) in the flattened ("chess960") corpus than in
    the unflattened ("standard") one — the sign c4_elo_scale.py's
    colour-neutral expected-score construction is built to detect."""
    chess960 = _prep(_synthetic_scalars(chaos=True, seed=1))
    standard = _prep(_synthetic_scalars(chaos=False, seed=2))
    pooled = _pooled(chess960, standard)
    fit = _fit(pooled, "score")

    def _white_pred(signed_gap: float, is_standard: float) -> float:
        return float(fit.predict(pd.DataFrame({
            "const": [1.0], "signed_gap": [signed_gap], "corpus_standard": [is_standard],
            "signed_gap_x_standard": [signed_gap * is_standard],
        }))[0])

    gap = 150.0
    p_chess960 = (_white_pred(gap, 0.0) + (1.0 - _white_pred(-gap, 0.0))) / 2.0
    p_standard = (_white_pred(gap, 1.0) + (1.0 - _white_pred(-gap, 1.0))) / 2.0
    assert 0.5 < p_chess960 < p_standard <= 1.0


# --- C3: c3_close_game_drawrate.fit_ame ------------------------------------


def test_c3_fit_ame_sign_on_injected_lower_draw_rate():
    """Chess960 rows are given a deliberately lower draw probability than
    standard's — the AME of corpus=freestyle should come out negative and
    its CI should exclude zero."""
    rng = np.random.default_rng(5)
    n_players = 40
    pool = np.clip(rng.normal(2400, 100, n_players), 2000, 2800).round().astype(int)
    rows = []
    for corpus, draw_p in (("freestyle", 0.15), ("standard", 0.45)):
        for i in range(600):
            wi, bi = rng.integers(0, n_players, 2)
            while bi == wi:
                bi = rng.integers(0, n_players)
            we, be = int(pool[wi]), int(pool[bi])
            draw = rng.random() < draw_p
            rows.append({
                "white_player": f"{corpus}_P{wi}", "black_player": f"{corpus}_P{bi}",
                "_avg_rating": (we + be) / 2.0, "_draw": float(draw), "_corpus": corpus,
                "source_event": f"{corpus}_E{i % 5}",
            })
    df = pd.DataFrame(rows)
    result = fit_ame(df, quadratic=False)
    assert result is not None
    ame, ci_lo, ci_hi, n = result
    assert ame < 0
    assert ci_hi < 0  # CI excludes zero, same direction as the point estimate


# --- Claim 4 descriptive: c5_bin_table.outcomes_table -----------------------


def _synthetic_cell_table() -> pd.DataFrame:
    rows = []
    rng = np.random.default_rng(7)
    for fmt in ["classical", "rapid"]:
        for corpus, upset_rate in (("chess960", 0.30), ("standard", 0.15)):
            for gb in BIN_LABELS:
                n = 200
                n_upsets = int(rng.binomial(n, upset_rate))
                n_draws = int(rng.binomial(n - n_upsets, 0.3))
                rows.append({"format": fmt, "corpus": corpus, "gap_bin": gb,
                             "n": n, "n_upsets": n_upsets, "n_draws": n_draws})
    return pd.DataFrame(rows)


def test_c5_outcomes_table_shape():
    cell_table = _synthetic_cell_table()
    out = outcomes_table(cell_table)
    assert len(out) == len(BIN_LABELS) * 2
    assert {"chess960_underdog_score_pct", "standard_underdog_score_pct", "diff_underdog_score_pct"}.issubset(out.columns)
    assert (out["diff_underdog_score_pct"] > 0).all()


# --- Stage 4: h1_stage4_hypothesis_tests per-cell statistics ---------------


def _synthetic_banded_h1(n_per_cell: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(9)
    rows = []
    for corpus, acpl_mean, otr_mean in (("freestyle", 25.0, 0.6), ("standard", 10.0, 0.4)):
        for i in range(n_per_cell):
            rows.append({
                "corpus": corpus, "format": "classical", "band": "2400 to 2499", "gap_bin": "0 to 99",
                "player_name": f"{corpus}_P{i}",
                "opening_acpl": max(0.0, rng.normal(acpl_mean, 5.0)),
                "otr": float(np.clip(rng.normal(otr_mean, 0.05), 0, 1)),
            })
    return pd.DataFrame(rows)


def test_h1a_opening_acpl_per_cell_mean_and_status():
    banded = _synthetic_banded_h1()
    out = h4.test_h1a_opening_acpl(banded)
    assert len(out) == 2
    fs_row = out[out["corpus"] == "freestyle"].iloc[0]
    std_row = out[out["corpus"] == "standard"].iloc[0]
    assert fs_row["status"] == "ok"
    assert std_row["status"] == "ok"
    assert fs_row["mean_opening_acpl"] > std_row["mean_opening_acpl"]
    assert fs_row["ci_lower"] < fs_row["mean_opening_acpl"] < fs_row["ci_upper"]


def test_h1b_opening_time_ratio_per_cell_mean():
    banded = _synthetic_banded_h1()
    out = h4.test_h1b_opening_time_ratio(banded)
    fs_row = out[out["corpus"] == "freestyle"].iloc[0]
    std_row = out[out["corpus"] == "standard"].iloc[0]
    assert fs_row["mean_otr"] > std_row["mean_otr"]


def test_c2_variance_per_cell():
    banded = _synthetic_banded_h1(n_per_cell=30)
    out = h4.test_c2_variance(banded)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["status"] == "ok"
    assert row["sd_freestyle"] > 0
    assert row["sd_standard"] > 0


# --- Claim 4: c5_upset_tests.load_close / fit_ame ---------------------------


def _synthetic_close_scalars(
    corpus: str, draw_p: float, underdog_p: float,
    n_close: int = 250, n_wide: int = 20, seed: int = 0,
) -> pd.DataFrame:
    """extract_scalars-shaped rows: n_close games with |gap| <= 100 (the
    close-game sample, underdog outcome controlled by draw_p/underdog_p)
    plus n_wide games with |gap| well above 100, to check that load_close
    drops the latter."""
    rng = np.random.default_rng(seed)
    n_players = 24
    players = [f"{corpus}_P{i}" for i in range(n_players)]

    def make_row(gid: int, we: float, be: float, result: str) -> dict:
        wi, bi = rng.choice(n_players, 2, replace=False)
        return {
            "game_id": f"{corpus}{gid:05d}", "source_event": f"{corpus}_E{gid % 5}",
            "source_type": "otb", "corpus": corpus, "format": "classical",
            "white_player": players[wi], "black_player": players[bi],
            "white_elo": we, "black_elo": be, "result": result,
        }

    rows = []
    for i in range(n_close):
        base = rng.uniform(2000, 2800)
        gap = rng.uniform(1.0, 100.0)  # never exactly 0 -> no equal-rated games here
        we, be = (base, base + gap) if rng.random() < 0.5 else (base + gap, base)
        lower_is_white = we < be
        if rng.random() < draw_p:
            result = _DRAW
        elif rng.random() < underdog_p:
            result = _WHITE if lower_is_white else _BLACK
        else:
            result = _BLACK if lower_is_white else _WHITE
        rows.append(make_row(i, we, be, result))

    for i in range(n_wide):
        base = rng.uniform(2000, 2700)
        gap = rng.uniform(150.0, 300.0)
        result = rng.choice([_WHITE, _BLACK, _DRAW])
        rows.append(make_row(n_close + i, base, base + gap, result))

    return pd.DataFrame(rows)


def test_c5_load_close_excludes_wide_gap_games(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROCESSED_DIR", tmp_path)
    n_close = 250
    fs = _synthetic_close_scalars("freestyle", draw_p=0.15, underdog_p=0.65,
                                   n_close=n_close, seed=1)
    fs.to_parquet(tmp_path / "freestyle_classical_scalars.parquet")

    df, n_before, n_equal = load_close("freestyle", "classical")
    assert n_before == n_close  # the n_wide=20 wide-gap games never reach this count
    assert n_equal == 0  # gap is always >= 1 in the close sample above
    assert len(df) == n_close
    assert (df["abs_gap"] <= C5_GAP_MAX).all()


def test_c5_fit_ame_signs_on_injected_fewer_draws_and_more_underdog_wins(tmp_path, monkeypatch):
    """Chess960 close games are given deliberately fewer draws and a higher
    underdog-win rate than standard's."""
    monkeypatch.setattr(config, "PROCESSED_DIR", tmp_path)
    fs_scalars = _synthetic_close_scalars("freestyle", draw_p=0.15, underdog_p=0.65, seed=1)
    std_scalars = _synthetic_close_scalars("standard", draw_p=0.45, underdog_p=0.20, seed=2)
    fs_scalars.to_parquet(tmp_path / "freestyle_classical_scalars.parquet")
    std_scalars.to_parquet(tmp_path / "standard_classical_scalars.parquet")

    fs, _, _ = load_close("freestyle", "classical")
    std, _, _ = load_close("standard", "classical")
    assert (fs["abs_gap"] <= C5_GAP_MAX).all()
    assert (std["abs_gap"] <= C5_GAP_MAX).all()

    pooled = pd.concat([fs, std], ignore_index=True)

    r_underdog = c5_fit_ame(pooled, "underdog_win")
    assert r_underdog is not None
    ame_u, lo_u, hi_u = r_underdog
    assert lo_u < ame_u < hi_u
    assert ame_u > 0

    r_draw = c5_fit_ame(pooled, "draw")
    assert r_draw is not None
    ame_d, lo_d, hi_d = r_draw
    assert lo_d < ame_d < hi_d
    assert ame_d < 0


@pytest.mark.parametrize("module", [c3, c5])
def test_source_type_cli_rejects_playin_online(module):
    """--source-type is restricted to the otb sensitivity variant only —
    playin_online (the complement, not a meaningful restriction on its
    own) must be rejected with a clear argparse error, not silently
    accepted."""
    with pytest.raises(SystemExit):
        module._build_parser().parse_args(["--source-type", "playin_online"])


# --- h1_band_tests: band-diff status + Cochran's-Q interaction test --------


def _banded_h1_single_cluster_case() -> pd.DataFrame:
    """One (format, band): standard side is a single distinct player across
    enough rows to clear MIN_CELL_COUNT; freestyle side has several distinct
    players — exercises cluster_bootstrap_ci's single-cluster NaN path on
    the standard side without tripping the insufficient_n floor."""
    rng = np.random.default_rng(1)
    n_rows = MIN_CELL_COUNT + 5
    rows = []
    for _ in range(n_rows):
        rows.append({"format": "classical", "band": "2800+", "corpus": "standard",
                      "player_name": "SOLO_PLAYER", "opening_acpl": float(rng.normal(10, 2))})
    for i in range(n_rows):
        rows.append({"format": "classical", "band": "2800+", "corpus": "freestyle",
                      "player_name": f"P{i % 8}", "opening_acpl": float(rng.normal(25, 5))})
    return pd.DataFrame(rows)


def test_band_diff_table_single_cluster_status_and_nan_ci():
    out = _band_diff_table(_banded_h1_single_cluster_case(), "opening_acpl")
    assert len(out) == 1
    row = out.iloc[0]
    assert row["status"] == "single_cluster"
    assert np.isnan(row["diff_ci_lower"])
    assert np.isnan(row["diff_ci_upper"])


def _band_diff_rows(diffs: list[float], se: float = 0.01, fmt: str = "classical") -> pd.DataFrame:
    half = se * 1.959963984540054
    rows = [
        {"format": fmt, "band": f"band{i}", "diff": d,
         "diff_ci_lower": d - half, "diff_ci_upper": d + half, "status": "ok"}
        for i, d in enumerate(diffs)
    ]
    return pd.DataFrame(rows)


def test_interaction_test_identical_diffs_gives_q_near_zero():
    out = _interaction_test(_band_diff_rows([0.05] * 6))
    row = out.iloc[0]
    assert row["q_statistic"] == pytest.approx(0.0, abs=1e-6)
    assert row["p_value"] == pytest.approx(1.0, abs=1e-6)


def test_interaction_test_divergent_diffs_gives_significant_q():
    out = _interaction_test(_band_diff_rows([-0.3, 0.4, -0.2, 0.5, -0.4, 0.3], se=0.01))
    row = out.iloc[0]
    assert row["p_value"] < 0.001


# --- volatility._var_from_w_d -----------------------------------------------


def test_var_from_w_d_matches_m_one_minus_m_formula():
    """Var = w + d/4 - (w+d/2)^2, with m = w + d/2 (the expected score)
    held fixed, is algebraically equivalent to m(1-m) - d/4."""
    for m, d in [(0.6, 0.4), (0.6, 0.1), (0.5, 0.3), (0.5, 0.05), (0.3, 0.2)]:
        w = m - d / 2.0
        assert _var_from_w_d(w, d) == pytest.approx(m * (1 - m) - d / 4.0)


def test_var_from_w_d_fewer_draws_higher_variance_at_fixed_expected_score():
    m = 0.6
    d_high, d_low = 0.4, 0.1
    w_high, w_low = m - d_high / 2.0, m - d_low / 2.0
    var_high_draws = _var_from_w_d(w_high, d_high)
    var_low_draws = _var_from_w_d(w_low, d_low)
    assert var_low_draws > var_high_draws
