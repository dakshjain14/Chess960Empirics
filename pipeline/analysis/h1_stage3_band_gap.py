"""Stage 3 of the H1a/H1b/C2 pipeline.

Rating-band edges are a **shared grid per format** — derived once from the
pooled Freestyle+Standard ``own_rating`` distribution, then applied
identically to both corpora, so H1a/H1b compare within literally the same
band rather than each corpus's own bins. C2 reuses this same shared grid
directly (see h1_stage4_hypothesis_tests.py), with no separate band
derivation of its own. Gap-bin edges are derived independently per
(corpus, format, band) instead — no cross-corpus sharing needed there.

Per (corpus, format), writes ``data/processed/banded_h1_{corpus}_{format}.parquet``
(row-level band/gap_bin assignment) and
``data/results/bin_boundaries_{corpus}_{format}.json`` (final edges, merge
audit trail, two-way cell-count table).

Cell counts are checked two ways, not one: raw row count, plus non-null
``opening_acpl``/``otr`` counts — a cell can clear the row-count floor while
falling short on an actual test input (Stage 2's OTR nulling in
particular), so mismatches are flagged explicitly (``any_mismatch``) rather
than silently carried into Stage 4.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pipeline.banding.band_gap_builder import _assign_bins, _assign_gap_bins_per_band, derive_bins
from pipeline.config import (
    BAND_STARTING_WIDTH,
    CORPORA,
    FORMATS,
    GAP_STARTING_WIDTH,
    MIN_CELL_COUNT,
    PROCESSED_DIR,
    RESULTS_DIR,
)

GAME_FEATURES_PATH = PROCESSED_DIR / "game_features.parquet"


def _two_way_cell_counts(df: pd.DataFrame, min_cell_count: int) -> pd.DataFrame:
    """One row per observed ``(band, gap_bin)``: raw n, non-null counts for
    each Stage-4 test input, below-floor flags, and a combined mismatch flag."""
    rows = []
    for (band, gap_bin), sub in df.groupby(["band", "gap_bin"], observed=True):
        n_total = len(sub)
        n_acpl = int(sub["opening_acpl"].notna().sum())
        n_otr = int(sub["otr"].notna().sum())
        below = {
            "below_min_opening_acpl": n_acpl < min_cell_count,
            "below_min_otr": n_otr < min_cell_count,
        }
        rows.append(
            {
                "band": band,
                "gap_bin": gap_bin,
                "n_total": n_total,
                "n_opening_acpl": n_acpl,
                "n_otr": n_otr,
                **below,
                "any_mismatch": any(below.values()) and not all(below.values()),
            }
        )
    out = pd.DataFrame(rows)
    out["_bk"] = out["gap_bin"].astype(str)
    out = out.sort_values(["band", "_bk"]).drop(columns="_bk").reset_index(drop=True)
    return out


def derive_shared_band_edges(game_features: pd.DataFrame, fmt: str) -> tuple[list[float], list[dict]]:
    """Rating-band edges for ``fmt``, derived once from both corpora's pooled
    ``own_rating`` distribution so H1a/H1b compare within identical bands."""
    merge_log: list[dict] = []
    pooled = game_features.loc[game_features["format"] == fmt, "own_rating"].astype(float)
    edges = derive_bins(pooled, MIN_CELL_COUNT, BAND_STARTING_WIDTH, merge_log=merge_log)
    return edges, merge_log


def process_combo(game_features: pd.DataFrame, corpus: str, fmt: str, band_edges: list[float]):
    subset = game_features[
        (game_features["corpus"] == corpus) & (game_features["format"] == fmt)
    ].copy().reset_index(drop=True)

    band_vals = subset["own_rating"].astype(float)
    subset["band"] = _assign_bins(band_vals, band_edges)

    gap_merge_logs: dict[str, list[dict]] = {}
    gap_vals = subset["gap_signed"].astype(float)
    subset["gap_bin"], gap_edges = _assign_gap_bins_per_band(
        subset, gap_vals, MIN_CELL_COUNT, GAP_STARTING_WIDTH, merge_logs=gap_merge_logs
    )

    cell_counts = _two_way_cell_counts(subset, MIN_CELL_COUNT)

    return subset, gap_edges, gap_merge_logs, cell_counts


def main(source_type: str | None = None) -> dict[str, pd.DataFrame]:
    """``source_type="otb"`` filters to OTB games before banding, so band/
    gap-bin edges are derived fresh from that subset rather than reusing the
    full-corpus edges — same "never share bins across subsets" rule as
    elsewhere in this pipeline. Writes to ``_otb``-suffixed paths."""
    game_features = pd.read_parquet(GAME_FEATURES_PATH)
    if source_type:
        game_features = game_features[game_features["source_type"] != "playin_online"]

    out_tag = f"_{source_type}" if source_type else ""
    n_stage2_rows = len(game_features)
    n_stage3_rows = 0
    results: dict[str, pd.DataFrame] = {}
    any_mismatch_anywhere = False

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    for fmt in FORMATS:
        band_edges, band_merge_log = derive_shared_band_edges(game_features, fmt)
        print(f"\n=== format={fmt}: shared band edges (Freestyle+Standard pooled) = {band_edges} ===")
        if band_merge_log:
            print(f"    shared-grid merges: {band_merge_log}")

        for corpus in CORPORA:
            slug = f"{corpus}_{fmt}{out_tag}"
            subset, gap_edges, gap_merge_logs, cell_counts = process_combo(
                game_features, corpus, fmt, band_edges
            )
            n_stage3_rows += len(subset)

            out_path = PROCESSED_DIR / f"banded_h1_{slug}.parquet"
            tmp = out_path.with_suffix(out_path.suffix + ".tmp")
            subset.to_parquet(tmp, engine="pyarrow", index=False)
            tmp.replace(out_path)

            boundary_log = {
                "corpus": corpus,
                "format": fmt,
                "source_type": source_type,
                "min_cell_count": MIN_CELL_COUNT,
                "band_starting_width": BAND_STARTING_WIDTH,
                "gap_starting_width": GAP_STARTING_WIDTH,
                "n_rows": len(subset),
                "band_edges": band_edges,
                "band_edges_shared": True,
                "band_merges": band_merge_log,
                "gap_edges_by_band": gap_edges,
                "gap_merges_by_band": gap_merge_logs,
                "cell_counts": cell_counts.to_dict(orient="records"),
            }
            json_path = RESULTS_DIR / f"bin_boundaries_{slug}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(boundary_log, f, indent=2, default=str)

            n_mismatch = int(cell_counts["any_mismatch"].sum())
            n_below_any = int(
                (
                    cell_counts["below_min_opening_acpl"]
                    | cell_counts["below_min_otr"]
                ).sum()
            )
            any_mismatch_anywhere = any_mismatch_anywhere or n_mismatch > 0

            print(f"\n=== {slug}: {len(subset)} rows, {len(band_edges)-1} bands, "
                  f"{cell_counts.shape[0]} (band,gap_bin) cells ===")
            print(f"band edges: {band_edges}")
            print(cell_counts.to_string(index=False))
            print(f"-> wrote {out_path}")
            print(f"-> wrote {json_path}")
            if n_below_any:
                print(f"FLAG: {n_below_any}/{len(cell_counts)} cells have at least one "
                      f"metric below the {MIN_CELL_COUNT}-floor despite the raw row count clearing it")
            if n_mismatch:
                print(f"FLAG: {n_mismatch}/{len(cell_counts)} cells have a MISMATCH "
                      f"(some of the 2 metrics below floor, others not)")

            results[slug] = cell_counts

    print(f"\n[stage3] Stage 2 rows in: {n_stage2_rows} -> Stage 3 rows out: {n_stage3_rows}")
    if any_mismatch_anywhere:
        print("[stage3] at least one combo has a cell-level metric mismatch — see FLAG lines above "
              "before proceeding to Stage 4")
    else:
        print("[stage3] no below-floor metric mismatches found in any combo")
    return results


if __name__ == "__main__":
    main()
