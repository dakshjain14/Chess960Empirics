"""Stage 4 driver for H1a/H1b/C2 and the rating/accuracy-gradient test —
reads Stage 3's banded parquet (or game_features.parquet directly for
the gradient), never re-deriving bands or re-parsing PGN.

H1a, H1b, and C2 all read Stage 3's banded_h1_*.parquet (shared rating
bands, per-corpus gap bins) — C2 groups by (format, band) and ignores
gap_bin, since it's a band-level variance measure with no gap dimension.
A dedicated C2 band derivation isn't needed: C2's bands would be derived
from the same pooled own_rating distribution Stage 3 already uses, so a
second call produces numerically identical edges (verified — see
METHODOLOGY.md's "Shared-grid floor check"). The gradient test reads
game_features.parquet directly with no banding at all.

Each result row carries a status flag from its own n (the gradient test has
no per-cell floor, so it carries no status column); each output CSV's first
line notes which banded source it came from.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from pipeline.analysis.hypothesis_tests import cluster_bootstrap_ci
from pipeline.analysis.hypothesis_tests import test_rating_accuracy_gradient as _test_rating_accuracy_gradient
from pipeline.banding.band_gap_builder import _sort_key
from pipeline.config import (
    BOOTSTRAP_ITERATIONS,
    CORPORA,
    DEFAULT_SEED,
    FORMATS,
    MIN_CELL_COUNT,
    PROCESSED_DIR,
    RESULTS_DIR,
)

GAME_FEATURES_PATH = PROCESSED_DIR / "game_features.parquet"

_H1_SOURCE_NOTE = (
    "# band: Stage 3, shared grid per format (pooled Freestyle+Standard distribution); "
    "gap_bin: derived independently per corpus within each band "
    "(banded_h1_{corpus}_{format}.parquet)"
)
_C2_SOURCE_NOTE = (
    "# band: Stage 3's shared grid (banded_h1_{corpus}_{format}.parquet), same as H1a/H1b — "
    "grouped by (format, band), gap_bin ignored since C2 has no gap dimension"
)
_GRADIENT_SOURCE_NOTE = (
    "# game_features.parquet directly, own_rating vs opening_acpl — no band derivation "
    "of any kind is used here — see METHODOLOGY.md"
)


def _status(n: int, ci_lower: float | None = None, min_cell_count: int = MIN_CELL_COUNT) -> str:
    """"single_cluster" when n clears the floor but the clustered CI
    couldn't be computed (fewer than 2 distinct players on one side —
    cluster_bootstrap_ci/the per-band diff helpers return NaN bounds in
    that case, not a falsely-precise zero-width CI)."""
    if n < min_cell_count:
        return f"insufficient_n (<{min_cell_count})"
    if ci_lower is not None and ci_lower != ci_lower:  # NaN check, no numpy import needed here
        return "single_cluster"
    return "ok"


def _sort_by_band_gap(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    """Sort a result frame by group_cols, using derive_bins' own numeric bin
    ordering for 'band'/'gap_bin' (their dtype may be plain object/str after
    concatenating frames with differently-derived categories, so a default
    lexical sort would misorder e.g. '100 to 149' before '50 to 99')."""
    tmp = df.copy()
    sort_cols = []
    for c in group_cols:
        if c in ("band", "gap_bin"):
            key_col = f"_{c}_key"
            tmp[key_col] = tmp[c].astype(str).map(_sort_key)
            sort_cols.append(key_col)
        else:
            sort_cols.append(c)
    tmp = tmp.sort_values(sort_cols).drop(columns=[c for c in tmp.columns if c.startswith("_") and c.endswith("_key")])
    return tmp.reset_index(drop=True)


# loaders


def load_banded_h1(source_type: str | None = None) -> pd.DataFrame:
    tag = f"_{source_type}" if source_type else ""
    frames = [
        pd.read_parquet(PROCESSED_DIR / f"banded_h1_{corpus}_{fmt}{tag}.parquet")
        for corpus in CORPORA
        for fmt in FORMATS
    ]
    return pd.concat(frames, ignore_index=True)


def load_game_features(source_type: str | None = None) -> pd.DataFrame:
    """source_type="otb" filters to source_type != "playin_online" — only
    relevant to test_rating_accuracy_gradient, which reads
    game_features.parquet directly rather than Stage 3's already-filtered
    banded output (h1_stage3_band_gap.py)."""
    df = pd.read_parquet(GAME_FEATURES_PATH)
    if source_type:
        df = df[df["source_type"] != "playin_online"]
    return df


# tests


def test_h1a_opening_acpl(
    banded_h1: pd.DataFrame,
    n_iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int | None = DEFAULT_SEED,
) -> pd.DataFrame:
    """Mean opening_acpl by (corpus, format, band, gap_bin), player-block
    bootstrap CI (resamples whole players, not rows, so a player appearing
    in several games doesn't overstate precision)."""
    cols = ["corpus", "format", "band", "gap_bin", "mean_opening_acpl", "ci_lower", "ci_upper", "n", "status"]
    rows = []
    for (corpus, fmt, band, gap_bin), sub in banded_h1.groupby(
        ["corpus", "format", "band", "gap_bin"], observed=True
    ):
        vals = pd.to_numeric(sub["opening_acpl"], errors="coerce").to_numpy()
        players = sub["player_name"].to_numpy()
        n = int((~np.isnan(vals)).sum())
        point, lo, hi = cluster_bootstrap_ci(vals, players, "mean", n_iterations=n_iterations, seed=seed)
        rows.append(
            {
                "corpus": corpus, "format": fmt, "band": band, "gap_bin": gap_bin,
                "mean_opening_acpl": point, "ci_lower": lo, "ci_upper": hi,
                "n": n, "status": _status(n, lo),
            }
        )
    out = pd.DataFrame(rows, columns=cols)
    return _sort_by_band_gap(out, ["corpus", "format", "band", "gap_bin"])


def test_h1b_opening_time_ratio(
    banded_h1: pd.DataFrame,
    n_iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int | None = DEFAULT_SEED,
) -> pd.DataFrame:
    """Mean otr by (corpus, format, band, gap_bin), player-block bootstrap
    CI (resamples whole players, not rows). Reads otr straight off
    banded_h1 (Stage 2's column, null on zero full-game denominator or
    zero opening-window coverage; see METHODOLOGY.md's "Clock data
    coverage" section) — independent of extract_scalars.py's own OTR
    reliability gate."""
    cols = ["corpus", "format", "band", "gap_bin", "mean_otr", "ci_lower", "ci_upper", "n", "status"]
    rows = []
    for (corpus, fmt, band, gap_bin), sub in banded_h1.groupby(
        ["corpus", "format", "band", "gap_bin"], observed=True
    ):
        vals = pd.to_numeric(sub["otr"], errors="coerce").to_numpy()
        players = sub["player_name"].to_numpy()
        n = int((~np.isnan(vals)).sum())
        point, lo, hi = cluster_bootstrap_ci(vals, players, "mean", n_iterations=n_iterations, seed=seed)
        rows.append(
            {
                "corpus": corpus, "format": fmt, "band": band, "gap_bin": gap_bin,
                "mean_otr": point, "ci_lower": lo, "ci_upper": hi,
                "n": n, "status": _status(n, lo),
            }
        )
    out = pd.DataFrame(rows, columns=cols)
    return _sort_by_band_gap(out, ["corpus", "format", "band", "gap_bin"])


def test_c2_variance(
    banded_h1: pd.DataFrame,
    n_iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int | None = DEFAULT_SEED,
) -> pd.DataFrame:
    """SD(opening_acpl) per corpus and a Brown-Forsythe (median-centered
    Levene) test between them, by (format, band) — Stage 3's shared bands,
    gap_bin ignored (C2 is a band-level variance measure with no gap
    dimension). Brown-Forsythe is row-level (it has no natural clustered
    variant); as a player-clustered supplement, sd_diff (freestyle -
    standard) carries its own player-block bootstrap CI, each corpus's SD
    resampled by player independently."""
    cols = [
        "format", "band", "sd_freestyle", "sd_standard", "n_freestyle", "n_standard",
        "levene_statistic", "p_value",
        "sd_diff", "sd_diff_ci_lower", "sd_diff_ci_upper", "status",
    ]
    rows = []
    for (fmt, band), sub in banded_h1.groupby(["format", "band"], observed=True):
        fs_sub = sub[sub["corpus"] == "freestyle"]
        st_sub = sub[sub["corpus"] == "standard"]
        fs = pd.to_numeric(fs_sub["opening_acpl"], errors="coerce").dropna()
        st = pd.to_numeric(st_sub["opening_acpl"], errors="coerce").dropna()
        n_fs, n_st = int(len(fs)), int(len(st))
        sd_fs = float(fs.std(ddof=1)) if n_fs > 1 else float("nan")
        sd_st = float(st.std(ddof=1)) if n_st > 1 else float("nan")
        if n_fs > 1 and n_st > 1:
            stat, p = stats.levene(fs.to_numpy(), st.to_numpy(), center="median")
            stat, p = float(stat), float(p)
        else:
            stat, p = float("nan"), float("nan")

        sd_diff = sd_fs - sd_st if (n_fs > 1 and n_st > 1) else float("nan")
        if n_fs > 1 and n_st > 1:
            fs_vals = pd.to_numeric(fs_sub["opening_acpl"], errors="coerce").to_numpy()
            fs_players = fs_sub["player_name"].to_numpy()
            st_vals = pd.to_numeric(st_sub["opening_acpl"], errors="coerce").to_numpy()
            st_players = st_sub["player_name"].to_numpy()
            _, fs_lo, fs_hi = cluster_bootstrap_ci(fs_vals, fs_players, "sd", n_iterations=n_iterations, seed=seed)
            _, st_lo, st_hi = cluster_bootstrap_ci(st_vals, st_players, "sd", n_iterations=n_iterations, seed=seed)
            # independent per-corpus player-block bootstraps; percentile CI
            # on the elementwise difference of the two replicate series.
            rng_fs = np.random.default_rng(seed)
            rng_st = np.random.default_rng((seed or 0) + 1)
            boot_fs = _boot_sd_samples(fs_vals, fs_players, n_iterations, rng_fs)
            boot_st = _boot_sd_samples(st_vals, st_players, n_iterations, rng_st)
            diff_lo, diff_hi = np.nanpercentile(boot_fs - boot_st, [2.5, 97.5])
            diff_lo, diff_hi = float(diff_lo), float(diff_hi)
        else:
            diff_lo, diff_hi = float("nan"), float("nan")

        status = _status(min(n_fs, n_st), diff_lo)
        rows.append(
            {
                "format": fmt, "band": band, "sd_freestyle": sd_fs, "sd_standard": sd_st,
                "n_freestyle": n_fs, "n_standard": n_st,
                "levene_statistic": stat, "p_value": p,
                "sd_diff": sd_diff, "sd_diff_ci_lower": diff_lo, "sd_diff_ci_upper": diff_hi,
                "status": status,
            }
        )
    out = pd.DataFrame(rows, columns=cols)
    return _sort_by_band_gap(out, ["format", "band"])


def _boot_sd_samples(values: np.ndarray, clusters: np.ndarray, n_iterations: int, rng: np.random.Generator) -> np.ndarray:
    """Raw player-block-bootstrap SD replicates (not percentile-reduced),
    for pairing into a difference-of-SDs CI. Same sufficient-statistic
    vectorization as cluster_bootstrap_ci."""
    arr = np.asarray(values, dtype=float)
    grp = np.asarray(clusters)
    mask = ~np.isnan(arr)
    arr, grp = arr[mask], grp[mask]
    uniq, inv = np.unique(grp, return_inverse=True)
    k = uniq.size
    if k <= 1:
        return np.full(n_iterations, np.nan)
    sums = np.bincount(inv, weights=arr, minlength=k)
    sumsq = np.bincount(inv, weights=arr**2, minlength=k)
    counts = np.bincount(inv, minlength=k).astype(float)
    idx = rng.integers(0, k, size=(n_iterations, k))
    boot_sums = sums[idx].sum(axis=1)
    boot_sumsq = sumsq[idx].sum(axis=1)
    boot_counts = counts[idx].sum(axis=1)
    var = (boot_sumsq - boot_sums**2 / boot_counts) / (boot_counts - 1)
    return np.sqrt(np.clip(var, 0, None))


def test_rating_accuracy_gradient(game_features: pd.DataFrame) -> pd.DataFrame:
    """One row per format: rating/opening-ACPL correlation and slope per
    corpus, plus the pooled-OLS interaction term. Thin per-format loop over
    hypothesis_tests.test_rating_accuracy_gradient, reading
    game_features.parquet directly (no band derivation)."""
    fs = game_features[game_features["corpus"] == "freestyle"]
    std = game_features[game_features["corpus"] == "standard"]
    rows = [_test_rating_accuracy_gradient(fs, std, fmt) for fmt in FORMATS]
    return pd.concat(rows, ignore_index=True)


# driver


def _write_csv_with_note(df: pd.DataFrame, path, note: str) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(note + "\n")
        df.to_csv(f, index=False)


def main(source_type: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """source_type=None (default) reads/writes the standard unsuffixed
    paths; "otb" excludes playin_online, reading/writing the _otb-suffixed
    Stage 3 outputs so full-corpus results are never overwritten."""
    out_tag = f"_{source_type}" if source_type else ""
    banded_h1 = load_banded_h1(source_type)
    game_features = load_game_features(source_type)

    n_banded_h1, n_game_features = len(banded_h1), len(game_features)

    h1a = test_h1a_opening_acpl(banded_h1)
    h1b = test_h1b_opening_time_ratio(banded_h1)

    c2 = test_c2_variance(banded_h1)

    gradient = test_rating_accuracy_gradient(game_features)

    h1a_path = RESULTS_DIR / f"h1a_results{out_tag}.csv"
    h1b_path = RESULTS_DIR / f"h1b_results{out_tag}.csv"
    c2_path = RESULTS_DIR / f"c2_results{out_tag}.csv"
    gradient_path = RESULTS_DIR / f"rating_accuracy_gradient_results{out_tag}.csv"
    _write_csv_with_note(h1a, h1a_path, _H1_SOURCE_NOTE)
    _write_csv_with_note(h1b, h1b_path, _H1_SOURCE_NOTE)
    _write_csv_with_note(c2, c2_path, _C2_SOURCE_NOTE)
    _write_csv_with_note(gradient, gradient_path, _GRADIENT_SOURCE_NOTE)

    print(f"[stage4] banded_h1 rows in: {n_banded_h1} -> h1a_results rows: {len(h1a)} -> {h1a_path}")
    print(f"[stage4] banded_h1 rows in: {n_banded_h1} -> h1b_results rows: {len(h1b)} -> {h1b_path}")
    print(f"[stage4] banded_h1 rows in: {n_banded_h1} -> c2_results rows: {len(c2)} -> {c2_path}")
    print(f"[stage4] game_features rows in: {n_game_features} -> "
          f"rating_accuracy_gradient_results rows: {len(gradient)} -> {gradient_path}")

    for name, df in (("h1a", h1a), ("h1b", h1b), ("c2", c2)):
        n_insuff = int((df["status"] != "ok").sum())
        print(f"[stage4] {name}: {n_insuff}/{len(df)} rows flagged insufficient_n")

    return h1a, h1b, c2, gradient


if __name__ == "__main__":
    main()
