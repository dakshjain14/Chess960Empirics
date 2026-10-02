"""Writes a per-(format, gap_bin) outcomes table: underdog score (wins +
half draws), underdog decisive share (wins over decisive games only,
strips draws out), and the win/draw/favorite-win shares, for each corpus,
with the Chess960-minus-standard difference on each — underdog win rate
alone doesn't separate a higher win share from a lower draw rate, so both
are reported together. This is C4's figure data (`c5_outcomes.csv` ->
Figure 2).

Run:  PYTHONPATH=. .venv-pipeline/bin/python pipeline/analysis/c5_bin_table.py
"""
from __future__ import annotations

import pandas as pd

from pipeline import run_pipeline as rp
from pipeline.analysis import hypothesis_tests as ht
from pipeline.banding import band_gap_builder as bg
from pipeline.config import RESULTS_DIR

_WHITE, _BLACK, _DRAW = ht._WHITE, ht._BLACK, ht._DRAW
BIN_EDGES = [-0.01, 100, 250, float("inf")]
BIN_LABELS = ["0-100", "101-250", "251+"]


def get_c34(corpus, fmt):
    """build_bands_c4c5 is called only for its Elo cleaning (dropping rows
    with unparseable white_elo/black_elo) — its band column is not used
    here; gap_bin below is derived independently from raw unsigned gap."""
    df = pd.read_parquet(rp._paths(corpus, fmt, None)["scalars"])
    return bg.build_bands_c4c5(df).data


def prep(df):
    # equal-rated games excluded: "underdog" is undefined with no gap
    work = df[df["result"].isin([_WHITE, _BLACK, _DRAW])].copy()
    we = pd.to_numeric(work["white_elo"], errors="coerce")
    be = pd.to_numeric(work["black_elo"], errors="coerce")
    work = work[we.notna() & be.notna() & (we != be)].copy()
    we, be = we[work.index], be[work.index]
    work["_gap"] = (we - be).abs()
    lower_is_white = we < be
    white_won = work.result == _WHITE
    black_won = work.result == _BLACK
    work["_lower_won"] = (lower_is_white & white_won) | (~lower_is_white & black_won)
    work["_draw"] = work.result == _DRAW
    work["_gap_bin"] = pd.cut(work["_gap"], bins=BIN_EDGES, labels=BIN_LABELS)
    return work


def outcomes_table(cell_table: pd.DataFrame) -> pd.DataFrame:
    """Per-(format, gap_bin): underdog score (wins + half draws) and the
    win/draw/favorite-win shares for each corpus, plus the
    Chess960-minus-standard difference on each."""
    rows = []
    for fmt in ["classical", "rapid"]:
        for gb in BIN_LABELS:
            fs = cell_table[(cell_table.format == fmt) & (cell_table.corpus == "chess960") & (cell_table.gap_bin == gb)].iloc[0]
            std = cell_table[(cell_table.format == fmt) & (cell_table.corpus == "standard") & (cell_table.gap_bin == gb)].iloc[0]

            def metrics(row):
                n = row["n"]
                win_pct = row["n_upsets"] / n * 100 if n else float("nan")
                draw_pct = row["n_draws"] / n * 100 if n else float("nan")
                n_fav = n - row["n_upsets"] - row["n_draws"]
                fav_pct = n_fav / n * 100 if n else float("nan")
                score_pct = win_pct + 0.5 * draw_pct
                n_decisive = row["n_upsets"] + n_fav
                decisive_share_pct = row["n_upsets"] / n_decisive * 100 if n_decisive else float("nan")
                return win_pct, draw_pct, fav_pct, score_pct, decisive_share_pct

            fs_win, fs_draw, fs_fav, fs_score, fs_decisive = metrics(fs)
            std_win, std_draw, std_fav, std_score, std_decisive = metrics(std)
            rows.append({
                "format": fmt, "gap_bin": gb,
                "chess960_n": int(fs["n"]), "standard_n": int(std["n"]),
                "chess960_underdog_score_pct": fs_score, "standard_underdog_score_pct": std_score,
                "diff_underdog_score_pct": fs_score - std_score,
                "chess960_underdog_win_pct": fs_win, "standard_underdog_win_pct": std_win,
                "diff_underdog_win_pct": fs_win - std_win,
                "chess960_underdog_decisive_share_pct": fs_decisive, "standard_underdog_decisive_share_pct": std_decisive,
                "diff_underdog_decisive_share_pct": fs_decisive - std_decisive,
                "chess960_draw_pct": fs_draw, "standard_draw_pct": std_draw,
                "diff_draw_pct": fs_draw - std_draw,
                "chess960_favourite_win_pct": fs_fav, "standard_favourite_win_pct": std_fav,
                "diff_favourite_win_pct": fs_fav - std_fav,
            })
    return pd.DataFrame(rows)


def main():
    rows = []
    for fmt in ["classical", "rapid"]:
        fs = prep(get_c34("freestyle", fmt))
        std = prep(get_c34("standard", fmt))
        for corpus_name, df in [("chess960", fs), ("standard", std)]:
            for gb in BIN_LABELS:
                sub = df[df["_gap_bin"] == gb]
                n = len(sub)
                n_upsets = int(sub["_lower_won"].sum())
                n_draws = int(sub["_draw"].sum())
                n_decisive = n - n_draws
                underdog_rate = n_upsets / n if n else float("nan")
                draw_rate = n_draws / n if n else float("nan")
                underdog_ratio_decisive = n_upsets / n_decisive if n_decisive else float("nan")
                rows.append({
                    "format": fmt, "corpus": corpus_name, "gap_bin": gb, "n": n,
                    "underdog_win_rate_pct": underdog_rate * 100,
                    "draw_rate_pct": draw_rate * 100,
                    "underdog_wins_over_decisive_pct": underdog_ratio_decisive * 100,
                    "n_upsets": n_upsets, "n_draws": n_draws, "n_decisive": n_decisive,
                })
    out = pd.DataFrame(rows)

    outcomes = outcomes_table(out)
    print()
    print(outcomes.round(2).to_string(index=False))
    outcomes_path = RESULTS_DIR / "c5_outcomes.csv"
    outcomes.to_csv(outcomes_path, index=False)
    print(f"\n[c5_bin_table] wrote {outcomes_path.name} ({len(outcomes)} rows)")
    return out, outcomes


if __name__ == "__main__":
    main()
