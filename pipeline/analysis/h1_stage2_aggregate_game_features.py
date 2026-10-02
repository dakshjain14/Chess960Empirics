"""Stage 2 of the H1a/H1b/C2 pipeline: aggregates Stage 1's per-move table
into one row per (game, side) — ``opening_acpl`` (mean CPL over
``move_number <= OPENING_WINDOW_MOVES``; White's always-null move-1 CPL is
skipped by ``pandas.Series.mean``, not counted as zero), ``otr`` (opening
time / full-game time, both summed from Stage 1 rows), ``full_clock_coverage``
(whether every move of the game has a non-null ``time_spent``), and
``gap_signed`` (``own_rating - opponent_rating``).

``otr`` is complete-case: null unless ``full_clock_coverage`` is True. OTR is
the ratio of opening time to total game time, so a side with any move missing
its clock reading has an unreliable total-game denominator and is excluded
rather than averaged in on a partial one — the same rule for H1b and for the
within-player OTR comparison in ``player_overlap.py``, since both read this
column directly. See METHODOLOGY.md's "Clock data coverage" and "H1b"
sections; ``coverage_sensitivity.py`` reports the partial-data (all
non-null-opening-window sides, regardless of whole-game coverage) method as
a robustness check against this one.

Kept as its own stage so a specific game's aggregates can be spot-checked
against its Stage 1 rows without re-parsing PGN.

Output: ``data/processed/game_features.parquet``, one row per (game, side).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.config import OPENING_WINDOW_MOVES, PROCESSED_DIR

IN_PATH = PROCESSED_DIR / "per_move_data.parquet"
OUT_PATH = PROCESSED_DIR / "game_features.parquet"

GAME_FEATURE_COLUMNS: tuple[str, ...] = (
    "game_id",
    "source_event",
    "corpus",
    "format",
    "source_type",
    "side",
    "player_name",
    "own_rating",
    "opponent_rating",
    "gap_signed",
    "opening_acpl",
    "otr",
    "full_clock_coverage",
)


def aggregate_game_features(per_move: pd.DataFrame, opening_moves: int = OPENING_WINDOW_MOVES) -> pd.DataFrame:
    """Builds the one-row-per-(game, side) feature table from Stage 1's rows.
    ``source_type`` carries through unchanged so a caller can filter this
    table directly by it."""
    df = per_move.copy()
    opening = df[df["move_number"] <= opening_moves]

    meta = (
        df.groupby(["game_id", "side"], as_index=False)
        .agg(
            source_event=("source_event", "first"),
            corpus=("corpus", "first"),
            format=("format", "first"),
            source_type=("source_type", "first"),
            player_name=("player_name", "first"),
            own_rating=("own_rating", "first"),
            opponent_rating=("opponent_rating", "first"),
            total_time=("time_spent", "sum"),
            full_clock_coverage=("time_spent", lambda s: bool(s.notna().all())),
        )
    )
    opening_agg = opening.groupby(["game_id", "side"], as_index=False).agg(
        opening_acpl=("cpl", "mean"),
        opening_time=("time_spent", "sum"),
    )

    out = meta.merge(opening_agg, on=["game_id", "side"], how="left")
    out["gap_signed"] = out["own_rating"] - out["opponent_rating"]
    # complete-case: otr is null unless every move of the game has a
    # recorded time_spent, not just the opening window
    out["otr"] = np.where(
        out["full_clock_coverage"] & (out["total_time"] > 0),
        out["opening_time"] / out["total_time"],
        np.nan,
    )
    out = out[list(GAME_FEATURE_COLUMNS)]
    return out.sort_values(["game_id", "side"]).reset_index(drop=True)


def main() -> pd.DataFrame:
    per_move = pd.read_parquet(IN_PATH)
    n_in = len(per_move)
    n_games_in = per_move["game_id"].nunique()

    out = aggregate_game_features(per_move)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix(OUT_PATH.suffix + ".tmp")
    out.to_parquet(tmp, engine="pyarrow", index=False)
    tmp.replace(OUT_PATH)

    print(
        f"[stage2] Stage 1 rows in: {n_in} ({n_games_in} games, "
        f"{n_games_in * 2} expected game-sides) -> Stage 2 rows out: {len(out)}"
    )
    print(f"[stage2] wrote -> {OUT_PATH}")

    otr_null = int(out["otr"].isna().sum())
    n_full_coverage = int(out["full_clock_coverage"].sum())
    print(
        f"[stage2] OTR (complete-case): {n_full_coverage}/{len(out)} sides have full clock "
        f"coverage, {otr_null} sides null (partial or zero clock coverage)"
    )
    n_white_acpl_notna = int((out.loc[out.side == "white", "opening_acpl"].notna()).sum())
    print(
        f"[stage2] opening_acpl coverage: white {n_white_acpl_notna}/{(out.side=='white').sum()} sides, "
        f"black {(out.loc[out.side=='black','opening_acpl'].notna()).sum()}/{(out.side=='black').sum()} sides"
    )
    return out


if __name__ == "__main__":
    main()
