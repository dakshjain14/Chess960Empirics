"""hypothesis_tests.py — C1-adjacent and C4 test functions. C1/H1a/H1b and
C2's actual (reported) tests live in h1_stage4_hypothesis_tests.py; C3 (draw
rate) lives in c3_close_game_drawrate.py (see METHODOLOGY.md's C3 section).

Each test takes both corpora's prepared frames and returns a tidy results
dataframe; nothing is hardcoded to which corpus is "chess960" vs "standard".

    test_rating_accuracy_gradient      C1-adjacent: rating vs opening-ACPL slope, Chess960 vs standard
    test_c4_interaction                C4: pooled logistic interaction, signed gap vs. corpus

Shared: bootstrap_ci, cluster_bootstrap_ci (player-block bootstrap), wilson_ci.
"""

from __future__ import annotations

import warnings
from typing import Callable

import numpy as np
import pandas as pd
from scipy import stats

from pipeline.config import (
    BOOTSTRAP_ITERATIONS,
    DEFAULT_SEED,
    MIN_CELL_COUNT,
    WILSON_Z,
)

_DRAW = "1/2-1/2"
_WHITE = "1-0"
_BLACK = "0-1"


# shared utilities


def bootstrap_ci(
    data: np.ndarray,
    statistic_fn: Callable[..., float],
    n_iterations: int = BOOTSTRAP_ITERATIONS,
    ci: float = 0.95,
    seed: int | None = DEFAULT_SEED,
) -> tuple[float, float, float]:
    """Percentile bootstrap CI for an arbitrary statistic; (point, ci_lower,
    ci_upper), all NaN if data is empty after dropping NaNs."""
    arr = np.asarray(data, dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    point = float(statistic_fn(arr))
    if arr.size == 1:
        return (point, point, point)

    rng = np.random.default_rng(seed)
    resamples = arr[rng.integers(0, arr.size, size=(n_iterations, arr.size))]
    try:
        boot = np.asarray(statistic_fn(resamples, axis=1), dtype=float)
    except TypeError:
        boot = np.array([float(statistic_fn(row)) for row in resamples])
    alpha = (1.0 - ci) / 2.0
    lo, hi = np.nanpercentile(boot, [100 * alpha, 100 * (1 - alpha)])
    return (point, float(lo), float(hi))


def cluster_bootstrap_ci(
    values: np.ndarray,
    clusters: np.ndarray,
    statistic: str = "mean",
    n_iterations: int = BOOTSTRAP_ITERATIONS,
    ci: float = 0.95,
    seed: int | None = DEFAULT_SEED,
) -> tuple[float, float, float]:
    """Percentile block-bootstrap CI resampling whole clusters (e.g.
    players) with replacement, so correlation from the same player
    appearing in multiple rows is reflected in the CI width — unlike
    bootstrap_ci's row-level resampling. statistic in {"mean", "sd"}.
    Vectorized via per-cluster sufficient statistics (sum/sumsq/n), since
    both mean and sample SD are computable from cluster-level totals.
    (point, ci_lower, ci_upper), all NaN if data is empty after dropping NaNs."""
    arr = np.asarray(values, dtype=float)
    grp = np.asarray(clusters)
    mask = ~np.isnan(arr)
    arr, grp = arr[mask], grp[mask]
    if arr.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    if statistic == "mean":
        point = float(arr.mean())
    elif statistic == "sd":
        point = float(arr.std(ddof=1)) if arr.size > 1 else float("nan")
    else:
        raise ValueError(f"unsupported statistic: {statistic!r}")

    uniq, inv = np.unique(grp, return_inverse=True)
    k = uniq.size
    if k <= 1:
        # a single distinct cluster can't support a block bootstrap — every
        # resample is the same cluster, which would otherwise return a
        # falsely-precise zero-width CI. NaN flags it as unreliable
        # (callers report this as status "single_cluster", not "ok").
        return (point, float("nan"), float("nan"))

    sums = np.bincount(inv, weights=arr, minlength=k)
    counts = np.bincount(inv, minlength=k).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, k, size=(n_iterations, k))
    boot_sums = sums[idx].sum(axis=1)
    boot_counts = counts[idx].sum(axis=1)

    if statistic == "mean":
        boot = boot_sums / boot_counts
    else:
        sumsq = np.bincount(inv, weights=arr**2, minlength=k)
        boot_sumsq = sumsq[idx].sum(axis=1)
        var = (boot_sumsq - boot_sums**2 / boot_counts) / (boot_counts - 1)
        boot = np.sqrt(np.clip(var, 0, None))

    alpha = (1.0 - ci) / 2.0
    lo, hi = np.nanpercentile(boot, [100 * alpha, 100 * (1 - alpha)])
    return (point, float(lo), float(hi))


def wilson_ci(successes: int, n: int, z: float = WILSON_Z) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion; (nan, nan) if n == 0.
    Used by C3's raw draw-rate CI (c3_close_game_drawrate.py)."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (float(centre - half), float(centre + half))


def _empty(columns: list[str]) -> pd.DataFrame:
    """Empty, correctly-typed frame — returned when there's nothing to
    compute on, so callers never branch on shape."""
    return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})


# C1-adjacent — rating/accuracy gradient


def test_rating_accuracy_gradient(
    df_chess960: pd.DataFrame,
    df_standard: pd.DataFrame,
    format: str,  # noqa: A002 - shadows builtin
) -> pd.DataFrame:
    """Does rating predict opening ACPL more weakly in standard chess than
    Chess960 — i.e. is standard's opening accuracy available more uniformly
    across skill levels (consistent with shared memorized theory)?

    Expects raw game_features.parquet rows per corpus (own_rating,
    opening_acpl, format), not banded frames; format selects one row per call.

    Reports per-corpus Pearson/Spearman correlation, each corpus's simple-OLS
    slope (ACPL per 100 rating points) with a player-clustered CI, and a
    pooled OLS interaction model (opening_acpl ~ own_rating + corpus_standard
    + own_rating:corpus_standard) whose interaction coefficient/p-value is
    the primary test of whether the two slopes differ — also player-clustered
    (one-way, by player_name; a player contributes rows across bands/gap-bins
    but not across both corpora, so one-way is sufficient here unlike C4's
    White/Black two-way setup).
    """
    try:
        import statsmodels.api as sm
    except ImportError as exc:  # pragma: no cover
        raise ImportError("test_rating_accuracy_gradient requires statsmodels") from exc

    cols = [
        "format",
        "corpus_chess960_r", "corpus_chess960_rho", "corpus_chess960_p", "corpus_chess960_spearman_p",
        "corpus_chess960_n",
        "corpus_standard_r", "corpus_standard_rho", "corpus_standard_p", "corpus_standard_spearman_p",
        "corpus_standard_n",
        "chess960_slope", "chess960_slope_ci_low", "chess960_slope_ci_high",
        "standard_slope", "standard_slope_ci_low", "standard_slope_ci_high",
        "interaction_coefficient", "interaction_p_value",
    ]

    def _prep(df: pd.DataFrame) -> pd.DataFrame:
        sub = df.loc[df["format"] == format, ["own_rating", "opening_acpl", "player_name"]].copy()
        sub["own_rating"] = pd.to_numeric(sub["own_rating"], errors="coerce")
        sub["opening_acpl"] = pd.to_numeric(sub["opening_acpl"], errors="coerce")
        return sub.dropna(subset=["own_rating", "opening_acpl"])

    c960 = _prep(df_chess960)
    std = _prep(df_standard)

    if len(c960) < 3 or len(std) < 3:
        return _empty(cols)

    def _corrs(sub: pd.DataFrame) -> tuple[float, float, float, float, int]:
        r, p = stats.pearsonr(sub["own_rating"], sub["opening_acpl"])
        rho, sp = stats.spearmanr(sub["own_rating"], sub["opening_acpl"])
        return float(r), float(p), float(rho), float(sp), int(len(sub))

    c_r, c_p, c_rho, c_sp, c_n = _corrs(c960)
    s_r, s_p, s_rho, s_sp, s_n = _corrs(std)

    def _slope_ci(sub: pd.DataFrame) -> tuple[float, float, float]:
        """Simple-OLS slope + player-clustered 95% CI, rescaled to
        per-100-rating-points."""
        x = sm.add_constant(sub[["own_rating"]].astype(float))
        fit = sm.OLS(sub["opening_acpl"].astype(float).to_numpy(), x).fit(
            cov_type="cluster", cov_kwds={"groups": sub["player_name"].to_numpy()}
        )
        slope = fit.params["own_rating"]
        ci_lo, ci_hi = fit.conf_int(alpha=0.05).loc["own_rating"]
        return slope * 100.0, ci_lo * 100.0, ci_hi * 100.0

    c_slope, c_lo, c_hi = _slope_ci(c960)
    s_slope, s_lo, s_hi = _slope_ci(std)

    pooled = pd.concat(
        [c960.assign(corpus_standard=0.0), std.assign(corpus_standard=1.0)], ignore_index=True
    )
    pooled["own_rating_x_standard"] = pooled["own_rating"] * pooled["corpus_standard"]
    pooled["cluster_player"] = pooled["player_name"]
    X = sm.add_constant(pooled[["own_rating", "corpus_standard", "own_rating_x_standard"]].astype(float))
    fit = sm.OLS(pooled["opening_acpl"].astype(float).to_numpy(), X).fit(
        cov_type="cluster", cov_kwds={"groups": pooled["cluster_player"].to_numpy()}
    )
    interaction_coef = float(fit.params["own_rating_x_standard"])
    interaction_p = float(fit.pvalues["own_rating_x_standard"])

    row = {
        "format": format,
        "corpus_chess960_r": c_r, "corpus_chess960_rho": c_rho,
        "corpus_chess960_p": c_p, "corpus_chess960_spearman_p": c_sp, "corpus_chess960_n": c_n,
        "corpus_standard_r": s_r, "corpus_standard_rho": s_rho,
        "corpus_standard_p": s_p, "corpus_standard_spearman_p": s_sp, "corpus_standard_n": s_n,
        "chess960_slope": c_slope, "chess960_slope_ci_low": c_lo, "chess960_slope_ci_high": c_hi,
        "standard_slope": s_slope, "standard_slope_ci_low": s_lo, "standard_slope_ci_high": s_hi,
        "interaction_coefficient": interaction_coef, "interaction_p_value": interaction_p,
    }
    return pd.DataFrame([row], columns=cols)


# C4 supplementary — predictive power of the rating gap (not Claim 4's
# close-game test; that's c5_upset_tests.py)


def test_c4_interaction(
    df_chess960: pd.DataFrame,
    df_standard: pd.DataFrame,
    outcome_col: str = "result",
    white_elo_col: str = "white_elo",
    black_elo_col: str = "black_elo",
) -> pd.DataFrame:
    """C4 — pooled logistic interaction model: does the rating-gap/outcome
    relationship differ by corpus? One primary statistic per format (call
    once per format on that format's build_bands_c4c5 frames; pooled over
    the whole format, bands aren't used here).

    Binary win-vs-not-win outcome (draws count as 0, unlike
    c4_elo_scale.py's decisive_only coding, which drops them) — a
    deliberate simplification stated explicitly rather than silently
    reframing draws as losses.

    Model: white_win ~ signed_gap + corpus_standard +
    signed_gap:corpus_standard (logistic; corpus_standard = 1 for standard,
    0 for chess960, so gap_coef is chess960's slope and gap_coef +
    interaction_coefficient is standard's). interaction_coefficient/
    interaction_p_value is the direct test of whether the two slopes differ
    — mirrors test_rating_accuracy_gradient's pooled-OLS convention, via
    logistic regression instead of OLS.
    """
    cols = [
        "n_chess960", "n_standard", "chess960_gap_coef", "standard_gap_coef",
        "interaction_coefficient", "interaction_p_value",
    ]

    def _prep(df: pd.DataFrame) -> pd.DataFrame:
        sub = df[df[outcome_col].isin([_WHITE, _BLACK, _DRAW])].copy()
        we = pd.to_numeric(sub[white_elo_col], errors="coerce")
        be = pd.to_numeric(sub[black_elo_col], errors="coerce")
        sub = sub[we.notna() & be.notna()].copy()
        sub["signed_gap"] = we - be
        sub["white_win"] = (sub[outcome_col] == _WHITE).astype(float)
        return sub[["signed_gap", "white_win"]]

    c960 = _prep(df_chess960)
    std = _prep(df_standard)
    if len(c960) < 3 or len(std) < 3:
        return _empty(cols)

    try:
        import statsmodels.api as sm
    except ImportError as exc:  # pragma: no cover
        raise ImportError("test_c4_interaction requires statsmodels") from exc

    pooled = pd.concat(
        [c960.assign(corpus_standard=0.0), std.assign(corpus_standard=1.0)], ignore_index=True
    )
    pooled["signed_gap_x_standard"] = pooled["signed_gap"] * pooled["corpus_standard"]
    X = sm.add_constant(pooled[["signed_gap", "corpus_standard", "signed_gap_x_standard"]].astype(float))
    y = pooled["white_win"].to_numpy(float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = sm.Logit(y, X).fit(disp=0, maxiter=100)

    chess960_gap_coef = float(fit.params["signed_gap"])
    interaction_coef = float(fit.params["signed_gap_x_standard"])
    row = {
        "n_chess960": int(len(c960)), "n_standard": int(len(std)),
        "chess960_gap_coef": chess960_gap_coef,
        "standard_gap_coef": chess960_gap_coef + interaction_coef,
        "interaction_coefficient": interaction_coef,
        "interaction_p_value": float(fit.pvalues["signed_gap_x_standard"]),
    }
    return pd.DataFrame([row], columns=cols)


