"""ply_by_ply.py — reliability-weighted ply-by-ply accuracy-gap curve,
reproducing METHODOLOGY.md's "Ply-by-Ply Accuracy Gap" subsection.

Bins: moves 1-3, 4-6, 7-9, 10-12, 13-15. Reliability-weighting method: all
9 shared rating bands, requiring MIN_CELL_COUNT at every individual move
position, for both corpora, before a band may contribute to a bin.

Run:  .venv-pipeline/bin/python -m pipeline.analysis.ply_by_ply
"""

from __future__ import annotations

import pandas as pd

from pipeline.config import CORPORA, FORMATS, MIN_CELL_COUNT, PROCESSED_DIR, RESULTS_DIR

BINS = [(1, 3), (4, 6), (7, 9), (10, 12), (13, 15)]
BIN_LABELS = [f"{lo}-{hi}" for lo, hi in BINS]


def _load_with_band(fmt: str, corpus: str) -> pd.DataFrame:
    pm = pd.read_parquet(PROCESSED_DIR / "per_move_data.parquet")
    pm = pm[(pm["format"] == fmt) & (pm["corpus"] == corpus)]
    h1 = pd.read_parquet(PROCESSED_DIR / f"banded_h1_{corpus}_{fmt}.parquet")
    band_map = h1[["game_id", "side", "band"]].drop_duplicates()
    return pm.merge(band_map, on=["game_id", "side"], how="inner")


def reliability_weighted_curve(fmt: str, side: str) -> pd.DataFrame:
    """One row per bin: reliability-weighted mean CPL per corpus, and the
    Chess960-minus-standard gap, aggregating only bands that individually
    clear MIN_CELL_COUNT at every move position in that bin, for both
    corpora."""
    frames = {corpus: _load_with_band(fmt, corpus) for corpus in CORPORA}
    for corpus in CORPORA:
        frames[corpus] = frames[corpus][frames[corpus]["side"] == side]

    bands = sorted(set(frames["freestyle"]["band"].astype(str)) | set(frames["standard"]["band"].astype(str)))

    rows = []
    for (lo, hi), label in zip(BINS, BIN_LABELS):
        moves = list(range(lo, hi + 1))
        qualifying_bands = []
        for band in bands:
            ok = True
            for corpus in CORPORA:
                sub = frames[corpus]
                sub = sub[(sub["band"].astype(str) == band) & (sub["move_number"].isin(moves))]
                for m in moves:
                    n = int((sub["move_number"] == m).sum())
                    if n < MIN_CELL_COUNT:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                qualifying_bands.append(band)

        means, weights = {}, {}
        for corpus in CORPORA:
            band_means, band_ns = [], []
            for band in qualifying_bands:
                sub = frames[corpus]
                sub = sub[(sub["band"].astype(str) == band) & (sub["move_number"].isin(moves))]
                vals = pd.to_numeric(sub["cpl"], errors="coerce").dropna()
                if len(vals):
                    band_means.append(vals.mean())
                    band_ns.append(len(vals))
            if band_ns:
                total_n = sum(band_ns)
                means[corpus] = sum(m * n for m, n in zip(band_means, band_ns)) / total_n
                weights[corpus] = total_n
            else:
                means[corpus] = float("nan")
                weights[corpus] = 0

        rows.append({
            "format": fmt, "side": side, "bin": label,
            "n_qualifying_bands": len(qualifying_bands),
            "chess960_mean_cpl": means["freestyle"], "standard_mean_cpl": means["standard"],
            "gap": means["freestyle"] - means["standard"],
        })
    return pd.DataFrame(rows)


def summarize_reversal(curve: pd.DataFrame) -> dict:
    """Given one (format, side)'s 5-bin curve, report: monotonic through
    bin3 (moves 1-9)?, and bin3-vs-bin5 growth-share percentage."""
    gaps = curve["gap"].to_list()
    steps_1_to_3 = [gaps[i + 1] - gaps[i] for i in range(2)]  # bin1->2, bin2->3
    monotonic_1_9 = all(s > 0 for s in steps_1_to_3)
    growth_1_9 = gaps[2] - gaps[0]
    growth_1_15 = gaps[4] - gaps[0]
    pct_by_move9 = growth_1_9 / growth_1_15 * 100 if growth_1_15 else float("nan")
    return {
        "monotonic_through_move9": monotonic_1_9,
        "growth_bin1_to_bin3": growth_1_9,
        "growth_bin1_to_bin5": growth_1_15,
        "pct_of_total_growth_by_move9": pct_by_move9,
    }


def main() -> pd.DataFrame:
    rows = []
    summaries = []
    for fmt in FORMATS:
        for side in ("white", "black"):
            curve = reliability_weighted_curve(fmt, side)
            rows.append(curve)
            summ = summarize_reversal(curve)
            summ["format"], summ["side"] = fmt, side
            summaries.append(summ)

    full = pd.concat(rows, ignore_index=True)
    summary = pd.DataFrame(summaries)[
        ["format", "side", "monotonic_through_move9", "growth_bin1_to_bin3",
         "growth_bin1_to_bin5", "pct_of_total_growth_by_move9"]
    ]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    full.to_csv(RESULTS_DIR / "ply_by_ply_curve.csv", index=False)
    summary.to_csv(RESULTS_DIR / "ply_by_ply_summary.csv", index=False)
    print(full.to_string(index=False))
    print()
    print(summary.to_string(index=False))
    return full


if __name__ == "__main__":
    main()
