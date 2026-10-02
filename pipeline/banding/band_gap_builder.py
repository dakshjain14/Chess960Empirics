"""Rating-band construction, plus gap-bin construction shared with the C1/C2
banding path.

Two deliberately separate rating-band conventions (see METHODOLOGY.md
"Cross-cutting notes") — don't merge them, each is specific to the
hypothesis it serves:
C1/C2 (two rows per game, band=own_elo, signed gap) live in
h1_stage2_aggregate_game_features.py / h1_stage3_band_gap.py, not here.
C4 uses build_bands_c4c5 below (one row per game, band=max elo since
averaging conflates skill with gap — a symmetric outcome is one
real-world fact, so a second per-player row would be pseudo-replication
that understates the CIs). build_bands_c4c5 has no gap dimension; its
consumers each derive their own gap bins directly.

Bin edges are always derived fresh from the passed dataframe's own
distribution (derive_bins), never hardcoded or reused across calls.
_assign_gap_bins_per_band derives gap-bin edges independently within
each rating band (an elite closed field and an open Swiss have very
different gap spreads) — used by h1_stage3_band_gap.py's C1/C2 path.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pandas as pd

from pipeline.config import BAND_STARTING_WIDTH, MIN_CELL_COUNT


class BandGapResult(NamedTuple):
    """Return type for build_bands_c4c5: banded data and the band edges used."""

    data: pd.DataFrame
    band_edges: list[float]


# --------------------------------------------------------------------------- #
# Automatic bin-boundary derivation                                            #
# --------------------------------------------------------------------------- #


def derive_bins(
    values: pd.Series | np.ndarray,
    min_cell_count: int = MIN_CELL_COUNT,
    starting_width: float = 100.0,
    merge_log: list[dict] | None = None,
) -> list[float]:
    """Lay starting_width-wide bins across the range, then repeatedly merge the sparsest
    bin into its smaller-count neighbour until every bin clears min_cell_count."""
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    if v.size == 0:
        raise ValueError("derive_bins: no non-NaN values")

    lo = float(np.floor(v.min() / starting_width) * starting_width)
    hi = float(np.ceil((v.max() + 1e-9) / starting_width) * starting_width)
    if hi <= lo:
        hi = lo + starting_width

    edges = list(np.arange(lo, hi + starting_width, starting_width))
    if len(edges) < 2:
        edges = [lo, lo + starting_width]

    def bin_counts(e: list[float]) -> np.ndarray:
        return np.histogram(v, bins=e)[0]

    while len(edges) > 2:
        counts = bin_counts(edges)
        if counts.min() >= min_cell_count:
            break
        i = int(np.argmin(counts))
        # merge into the smaller-count neighbour; ties merge toward the closer edge
        if i == 0:
            drop = 1
            direction = "right"
        elif i == len(counts) - 1:
            drop = len(edges) - 2
            direction = "left"
        else:
            left_c, right_c = counts[i - 1], counts[i + 1]
            if left_c <= right_c:
                drop, direction = i, "left"
            else:
                drop, direction = i + 1, "right"
        if merge_log is not None:
            merge_log.append(
                {
                    "merged_bin": [float(edges[i]), float(edges[i + 1])],
                    "merged_bin_count": int(counts[i]),
                    "direction": direction,
                    "reason": f"count {int(counts[i])} < min_cell_count {min_cell_count}",
                }
            )
        edges.pop(drop)

    return [float(e) for e in edges]


def _bin_labels(edges: list[float]) -> list[str]:
    """"lo to hi" labels, last bin "lo+"."""
    labels: list[str] = []
    for i in range(len(edges) - 1):
        lo = int(round(edges[i]))
        hi = int(round(edges[i + 1]))
        if i == len(edges) - 2:
            labels.append(f"{lo}+")
        else:
            labels.append(f"{lo} to {hi - 1}")
    return labels


def _assign_bins(values: pd.Series, edges: list[float]) -> pd.Categorical:
    """Ordered Categorical of bin labels for values under edges (half-open, last bin closed)."""
    labels = _bin_labels(edges)
    idx = np.digitize(values.to_numpy(dtype=float), bins=edges, right=False) - 1
    idx = np.clip(idx, 0, len(labels) - 1)
    return pd.Categorical.from_codes(idx, categories=labels, ordered=True)


def _sort_key(label: str) -> float:
    """Numeric lower bound of a bin label ("100 to 149", "-50 to -1", "400+")."""
    token = label.split(" to ")[0].rstrip("+")
    try:
        return float(token)
    except ValueError:
        return float("inf")


def _assign_gap_bins_per_band(
    df: pd.DataFrame,
    gap_vals: pd.Series,
    min_cell_count: int,
    starting_width: float,
    merge_logs: dict[str, list[dict]] | None = None,
) -> tuple[pd.Series, dict[str, list[float]]]:
    """Derive gap-bin edges independently within each band and return the labelled column."""
    gap_bin = pd.Series(index=df.index, dtype=object)
    edges_by_band: dict[str, list[float]] = {}
    for band_label in df["band"].cat.categories:
        mask = df["band"] == band_label
        if not mask.any():
            continue
        band_log = [] if merge_logs is not None else None
        edges = derive_bins(gap_vals[mask], min_cell_count, starting_width, merge_log=band_log)
        if merge_logs is not None:
            merge_logs[str(band_label)] = band_log
        edges_by_band[str(band_label)] = edges
        labels = _bin_labels(edges)
        idx = np.clip(np.digitize(gap_vals[mask].to_numpy(float), bins=edges, right=False) - 1,
                      0, len(labels) - 1)
        gap_bin.loc[mask] = [labels[i] for i in idx]

    all_labels = sorted({lab for labs in edges_by_band.values() for lab in _bin_labels(labs)},
                        key=_sort_key)
    cat = pd.Categorical(gap_bin, categories=all_labels, ordered=True)
    return pd.Series(cat, index=df.index), edges_by_band


def _clean_elo(df: pd.DataFrame, cols: tuple[str, ...]) -> pd.DataFrame:
    """Coerce cols to numeric and drop rows where any is unparseable."""
    out = df.copy()
    for c in cols:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    n0 = len(out)
    out = out.dropna(subset=list(cols)).reset_index(drop=True)
    if len(out) < n0:
        print(f"[band_gap_builder] dropped {n0 - len(out)} rows with unparseable Elo")
    return out


# --------------------------------------------------------------------------- #
# C4 — one row per game, max rating band                                      #
# --------------------------------------------------------------------------- #


def build_bands_c4c5(df: pd.DataFrame, min_cell_count: int = MIN_CELL_COUNT) -> BandGapResult:
    """C4 banding: Elo cleaning plus a band on a shared grid, one row per
    game, band=max(white_elo, black_elo). No gap-bin dimension — every
    build_bands_c4c5 consumer derives its own gap bins directly, keyed to
    the hypothesis it serves (see c5_bin_table.py, c4_gap_restricted_bands.py)."""
    work = _clean_elo(df, ("white_elo", "black_elo")).copy()
    band_vals = work[["white_elo", "black_elo"]].max(axis=1)

    band_edges = derive_bins(band_vals, min_cell_count, BAND_STARTING_WIDTH)
    work["band"] = _assign_bins(band_vals, band_edges)

    return BandGapResult(work, band_edges)
