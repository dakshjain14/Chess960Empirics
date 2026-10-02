"""H1b coverage + partial-data robustness check (METHODOLOGY.md's "H1b
Coverage" and "Clock data coverage" sections). "Full-game coverage" =
fraction of (game_id, side) with non-null time_spent on every move, not just
the opening — the same condition ``h1_stage2_aggregate_game_features.py``
uses to null ``otr`` for complete-case. The alternative "partial-data"
method recomputes OTR including sides with an incomplete whole-game
denominator (opening_time / total_time over whatever moves are tagged,
regardless of coverage) as a robustness check on whether complete-case's
stricter rule changes H1b's direction or significance anywhere.

Run:  .venv-pipeline/bin/python -m pipeline.analysis.coverage_sensitivity
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.analysis.hypothesis_tests import bootstrap_ci
from pipeline.config import (
    BOOTSTRAP_ITERATIONS,
    CORPORA,
    DEFAULT_SEED,
    FORMATS,
    MIN_CELL_COUNT,
    PROCESSED_DIR,
    RESULTS_DIR,
)


def coverage_by_corpus_format() -> pd.DataFrame:
    pm = pd.read_parquet(PROCESSED_DIR / "per_move_data.parquet")
    g = (
        pm.groupby(["corpus", "format", "side", "game_id"])["time_spent"]
        .apply(lambda s: s.notna().all())
        .reset_index(name="full_coverage")
    )
    out = g.groupby(["corpus", "format"])["full_coverage"].mean().reset_index()
    out["full_coverage_pct"] = out["full_coverage"] * 100
    return out.drop(columns="full_coverage")


def _partial_data_otr(pm: pd.DataFrame, opening_moves: int = 15) -> pd.DataFrame:
    """Partial-coverage OTR: opening_time / total_time over whatever moves
    are tagged, null only on zero coverage outright — the method this
    module checks complete-case against."""
    opening = pm[pm["move_number"] <= opening_moves]
    total_time = pm.groupby(["corpus", "format", "game_id", "side"])["time_spent"].sum().rename("total_time")
    opening_time = opening.groupby(["corpus", "format", "game_id", "side"])["time_spent"].sum().rename("opening_time")
    opening_n = opening.groupby(["corpus", "format", "game_id", "side"])["time_spent"].apply(lambda s: s.notna().sum()).rename("opening_n")
    out = pd.concat([total_time, opening_time, opening_n], axis=1).reset_index()
    out["partial_otr"] = np.where(
        (out["total_time"] > 0) & (out["opening_n"] > 0),
        out["opening_time"] / out["total_time"],
        np.nan,
    )
    return out


def _diff_ci(a: np.ndarray, b: np.ndarray, n_iterations: int = BOOTSTRAP_ITERATIONS, seed: int | None = DEFAULT_SEED):
    """Independent two-sample bootstrap CI for mean(a) - mean(b)."""
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if a.size == 0 or b.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    point = float(a.mean() - b.mean())
    rng = np.random.default_rng(seed)
    boot_a = a[rng.integers(0, a.size, size=(n_iterations, a.size))].mean(axis=1)
    boot_b = b[rng.integers(0, b.size, size=(n_iterations, b.size))].mean(axis=1)
    diff = boot_a - boot_b
    lo, hi = np.percentile(diff, [2.5, 97.5])
    return (point, float(lo), float(hi))


def complete_case_vs_partial() -> pd.DataFrame:
    """Per (format, band): complete-case and partial-data mean OTR for each
    corpus (n + 95% CI), and the Chess960-minus-standard difference (n + 95%
    CI) under both methods."""
    pm = pd.read_parquet(PROCESSED_DIR / "per_move_data.parquet")
    partial = _partial_data_otr(pm)

    rows = []
    for fmt in FORMATS:
        h1 = {c: pd.read_parquet(PROCESSED_DIR / f"banded_h1_{c}_{fmt}.parquet") for c in CORPORA}
        bands = sorted(pd.concat(h1.values())["band"].dropna().unique().tolist())
        for band in bands:
            cc_vals: dict[str, np.ndarray] = {}
            cc_n: dict[str, int] = {}
            pd_vals: dict[str, np.ndarray] = {}
            pd_n: dict[str, int] = {}
            for corpus in CORPORA:
                sub = h1[corpus][h1[corpus]["band"] == band]
                cc = pd.to_numeric(sub["otr"], errors="coerce").dropna().to_numpy()
                cc_vals[corpus], cc_n[corpus] = cc, cc.size

                merged = sub[["game_id", "side"]].merge(
                    partial[(partial.corpus == corpus) & (partial.format == fmt)][["game_id", "side", "partial_otr"]],
                    on=["game_id", "side"], how="left",
                )
                pv = pd.to_numeric(merged["partial_otr"], errors="coerce").dropna().to_numpy()
                pd_vals[corpus], pd_n[corpus] = pv, pv.size

            cc_fs_pt, cc_fs_lo, cc_fs_hi = bootstrap_ci(cc_vals["freestyle"], np.mean)
            cc_std_pt, cc_std_lo, cc_std_hi = bootstrap_ci(cc_vals["standard"], np.mean)
            cc_d_pt, cc_d_lo, cc_d_hi = _diff_ci(cc_vals["freestyle"], cc_vals["standard"])

            pd_fs_pt, pd_fs_lo, pd_fs_hi = bootstrap_ci(pd_vals["freestyle"], np.mean)
            pd_std_pt, pd_std_lo, pd_std_hi = bootstrap_ci(pd_vals["standard"], np.mean)
            pd_d_pt, pd_d_lo, pd_d_hi = _diff_ci(pd_vals["freestyle"], pd_vals["standard"])

            min_n = min(cc_n["freestyle"], cc_n["standard"])
            rows.append({
                "format": fmt, "band": band,
                "cc_mean_otr_freestyle": cc_fs_pt, "cc_ci_lower_freestyle": cc_fs_lo, "cc_ci_upper_freestyle": cc_fs_hi, "cc_n_freestyle": cc_n["freestyle"],
                "cc_mean_otr_standard": cc_std_pt, "cc_ci_lower_standard": cc_std_lo, "cc_ci_upper_standard": cc_std_hi, "cc_n_standard": cc_n["standard"],
                "cc_diff": cc_d_pt, "cc_diff_ci_lower": cc_d_lo, "cc_diff_ci_upper": cc_d_hi,
                "partial_mean_otr_freestyle": pd_fs_pt, "partial_ci_lower_freestyle": pd_fs_lo, "partial_ci_upper_freestyle": pd_fs_hi, "partial_n_freestyle": pd_n["freestyle"],
                "partial_mean_otr_standard": pd_std_pt, "partial_ci_lower_standard": pd_std_lo, "partial_ci_upper_standard": pd_std_hi, "partial_n_standard": pd_n["standard"],
                "partial_diff": pd_d_pt, "partial_diff_ci_lower": pd_d_lo, "partial_diff_ci_upper": pd_d_hi,
                "status": "ok" if min_n >= MIN_CELL_COUNT else f"insufficient_n (<{MIN_CELL_COUNT})",
            })
    return pd.DataFrame(rows)


def main() -> dict[str, pd.DataFrame]:
    coverage = coverage_by_corpus_format()
    sensitivity = complete_case_vs_partial()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(RESULTS_DIR / "h1b_coverage_by_corpus_format.csv", index=False)
    sensitivity.to_csv(RESULTS_DIR / "h1b_complete_case_sensitivity.csv", index=False)

    print(coverage.to_string(index=False))
    print()
    with pd.option_context("display.max_columns", None, "display.width", 240):
        print(sensitivity.to_string(index=False))
    print()
    ok = sensitivity[sensitivity["status"] == "ok"]
    n_sign_flip = int((np.sign(ok["cc_diff"]) != np.sign(ok["partial_diff"])).sum())
    n_cc_sig_pos = int(((ok["cc_diff_ci_lower"] > 0)).sum())
    n_partial_sig_pos = int(((ok["partial_diff_ci_lower"] > 0)).sum())
    print(f"Bands with status=ok: {len(ok)}; sign flips between methods: {n_sign_flip}")
    print(f"Chess960 > standard, significant (CI excludes zero): complete-case {n_cc_sig_pos}/{len(ok)}, "
          f"partial-data {n_partial_sig_pos}/{len(ok)}")
    return {"coverage": coverage, "sensitivity": sensitivity}


if __name__ == "__main__":
    main()
