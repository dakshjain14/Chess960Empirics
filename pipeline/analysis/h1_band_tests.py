"""h1_band_tests.py — band-level Chess960-minus-standard CIs and a
band x corpus interaction test for H1a (opening ACPL) and H1b (OTR),
mirroring coverage_sensitivity.py's per-band diff-CI pattern. Diff CIs are
player-block bootstrapped (each corpus's players resampled independently,
same construction as C2's sd_diff supplement in h1_stage4_hypothesis_tests.py).

Interaction test: a Cochran's-Q heterogeneity test across bands, per format
— tests whether the Chess960-minus-standard difference varies by band (an
interaction), not just whether it is individually nonzero in each band.
Q = sum_i w_i*(diff_i - diff_bar)^2, w_i = 1/se_i^2 (se_i from the
player-block bootstrap CI), compared to chi2(df=n_bands-1) under the null
of a constant difference across bands.

Also writes h1b_pooled_summary.csv: per format, each corpus's full-corpus
(all bands pooled) mean OTR and the Chess960-minus-standard difference,
all player-block bootstrapped — the pooled numbers METHODOLOGY.md's H1b
section quotes in prose.

Run:  PYTHONPATH=. .venv-pipeline/bin/python -m pipeline.analysis.h1_band_tests
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from pipeline.analysis.h1_stage4_hypothesis_tests import load_banded_h1
from pipeline.analysis.hypothesis_tests import cluster_bootstrap_ci
from pipeline.config import BOOTSTRAP_ITERATIONS, DEFAULT_SEED, FORMATS, MIN_CELL_COUNT, RESULTS_DIR


def _boot_mean_samples(values: np.ndarray, clusters: np.ndarray, n_iterations: int, rng: np.random.Generator) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    grp = np.asarray(clusters)
    mask = ~np.isnan(arr)
    arr, grp = arr[mask], grp[mask]
    uniq, inv = np.unique(grp, return_inverse=True)
    k = uniq.size
    if k <= 1:
        return np.full(n_iterations, np.nan)
    sums = np.bincount(inv, weights=arr, minlength=k)
    counts = np.bincount(inv, minlength=k).astype(float)
    idx = rng.integers(0, k, size=(n_iterations, k))
    return sums[idx].sum(axis=1) / counts[idx].sum(axis=1)


def _diff_ci_clustered(
    fs_vals: np.ndarray, fs_players: np.ndarray, st_vals: np.ndarray, st_players: np.ndarray,
    n_iterations: int = BOOTSTRAP_ITERATIONS, seed: int | None = DEFAULT_SEED,
) -> tuple[float, float, float]:
    """Point diff + percentile CI on the elementwise difference of two
    independent player-block bootstrap mean replicate series."""
    fs_clean = fs_vals[~np.isnan(fs_vals)]
    st_clean = st_vals[~np.isnan(st_vals)]
    if fs_clean.size == 0 or st_clean.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    point = float(fs_clean.mean() - st_clean.mean())
    rng_fs = np.random.default_rng(seed)
    rng_st = np.random.default_rng((seed or 0) + 1)
    boot_fs = _boot_mean_samples(fs_vals, fs_players, n_iterations, rng_fs)
    boot_st = _boot_mean_samples(st_vals, st_players, n_iterations, rng_st)
    lo, hi = np.nanpercentile(boot_fs - boot_st, [2.5, 97.5])
    return (point, float(lo), float(hi))


def _band_diff_table(banded_h1: pd.DataFrame, value_col: str) -> pd.DataFrame:
    cols = [
        "format", "band",
        f"mean_{value_col}_freestyle", f"mean_{value_col}_standard",
        "n_freestyle", "n_standard", "diff", "diff_ci_lower", "diff_ci_upper", "status",
    ]
    rows = []
    for (fmt, band), sub in banded_h1.groupby(["format", "band"], observed=True):
        fs_sub = sub[sub["corpus"] == "freestyle"]
        st_sub = sub[sub["corpus"] == "standard"]
        fs_vals = pd.to_numeric(fs_sub[value_col], errors="coerce").to_numpy()
        st_vals = pd.to_numeric(st_sub[value_col], errors="coerce").to_numpy()
        fs_players = fs_sub["player_name"].to_numpy()
        st_players = st_sub["player_name"].to_numpy()
        n_fs, n_st = int((~np.isnan(fs_vals)).sum()), int((~np.isnan(st_vals)).sum())
        mean_fs = float(np.nanmean(fs_vals)) if n_fs else float("nan")
        mean_st = float(np.nanmean(st_vals)) if n_st else float("nan")
        if n_fs > 1 and n_st > 1:
            diff, lo, hi = _diff_ci_clustered(fs_vals, fs_players, st_vals, st_players)
        else:
            diff, lo, hi = float("nan"), float("nan"), float("nan")
        if n_fs < MIN_CELL_COUNT or n_st < MIN_CELL_COUNT:
            status = f"insufficient_n (<{MIN_CELL_COUNT})"
        elif lo != lo:  # NaN check — fewer than 2 distinct players on one side
            status = "single_cluster"
        else:
            status = "ok"
        rows.append({
            "format": fmt, "band": band,
            f"mean_{value_col}_freestyle": mean_fs, f"mean_{value_col}_standard": mean_st,
            "n_freestyle": n_fs, "n_standard": n_st,
            "diff": diff, "diff_ci_lower": lo, "diff_ci_upper": hi, "status": status,
        })
    return pd.DataFrame(rows, columns=cols)


def _interaction_test(band_diff: pd.DataFrame) -> pd.DataFrame:
    """Cochran's-Q heterogeneity test of the Chess960-minus-standard diff
    across bands, per format — the band x corpus interaction test."""
    rows = []
    for fmt, sub in band_diff.groupby("format"):
        ok = sub[sub["status"] == "ok"].copy()
        se = (ok["diff_ci_upper"] - ok["diff_ci_lower"]) / (2 * 1.959963984540054)
        # a band with se == 0 (degenerate CI — typically a single dominant
        # player in a thin tail band) carries infinite weight and would
        # swamp the test; excluded, not treated as a precise estimate.
        n_degenerate = int((se <= 0).sum())
        ok, se = ok[se > 0], se[se > 0]
        w = 1.0 / se**2
        df = max(len(ok) - 1, 0)
        if df > 0:
            diff_bar = float((w * ok["diff"]).sum() / w.sum())
            q = float((w * (ok["diff"] - diff_bar) ** 2).sum())
            p = float(1.0 - stats.chi2.cdf(q, df))
        else:
            diff_bar, q, p = float("nan"), float("nan"), float("nan")
        rows.append({
            "format": fmt, "n_bands": len(ok), "n_bands_degenerate_se_excluded": n_degenerate, "df": df,
            "weighted_mean_diff": diff_bar, "q_statistic": q, "p_value": p,
        })
    return pd.DataFrame(rows)


def pooled_h1b_summary(banded_h1: pd.DataFrame) -> pd.DataFrame:
    """Full-corpus (all bands pooled) OTR mean per format x corpus, and the
    Chess960-minus-standard difference — all player-block bootstrapped."""
    rows = []
    for fmt in FORMATS:
        sub = banded_h1[banded_h1["format"] == fmt]
        fs_sub = sub[sub["corpus"] == "freestyle"]
        st_sub = sub[sub["corpus"] == "standard"]
        fs_vals = pd.to_numeric(fs_sub["otr"], errors="coerce").to_numpy()
        st_vals = pd.to_numeric(st_sub["otr"], errors="coerce").to_numpy()
        fs_players, st_players = fs_sub["player_name"].to_numpy(), st_sub["player_name"].to_numpy()
        fs_pt, fs_lo, fs_hi = cluster_bootstrap_ci(fs_vals, fs_players, "mean")
        st_pt, st_lo, st_hi = cluster_bootstrap_ci(st_vals, st_players, "mean")
        diff, diff_lo, diff_hi = _diff_ci_clustered(fs_vals, fs_players, st_vals, st_players)
        rows.append({
            "format": fmt,
            "mean_otr_freestyle": fs_pt, "ci_lower_freestyle": fs_lo, "ci_upper_freestyle": fs_hi,
            "n_freestyle": int((~np.isnan(fs_vals)).sum()),
            "mean_otr_standard": st_pt, "ci_lower_standard": st_lo, "ci_upper_standard": st_hi,
            "n_standard": int((~np.isnan(st_vals)).sum()),
            "diff": diff, "diff_ci_lower": diff_lo, "diff_ci_upper": diff_hi,
        })
    return pd.DataFrame(rows)


def main() -> dict[str, pd.DataFrame]:
    banded_h1 = load_banded_h1()

    h1a_band_diff = _band_diff_table(banded_h1, "opening_acpl")
    h1a_interaction = _interaction_test(h1a_band_diff)
    h1b_band_diff = _band_diff_table(banded_h1, "otr")
    h1b_interaction = _interaction_test(h1b_band_diff)
    h1b_pooled = pooled_h1b_summary(banded_h1)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "h1a_band_diff": h1a_band_diff,
        "h1a_band_interaction": h1a_interaction,
        "h1b_band_diff": h1b_band_diff,
        "h1b_band_interaction": h1b_interaction,
        "h1b_pooled_summary": h1b_pooled,
    }
    for name, df in out.items():
        path = RESULTS_DIR / f"{name}.csv"
        df.to_csv(path, index=False)
        print(f"[h1_band_tests] wrote {path.name} ({len(df)} rows)")

    print()
    print(h1a_interaction.to_string(index=False))
    print(h1b_interaction.to_string(index=False))
    return out


if __name__ == "__main__":
    main()
