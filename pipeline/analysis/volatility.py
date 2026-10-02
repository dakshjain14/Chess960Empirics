"""In-game swings in moves 1-15 (Claim 1's further measure of opening
play, METHODOLOGY.md's C1 section) — re-parsed directly from the
engine-annotated PGNs (data/processed/Updated_engine_eval/, via
manifest_loader.load_corpus) since per_move_data.parquet stores only
cpl, not the raw White-POV [%eval] a swing/lead-change trace needs.

Definitions (fixed before results were seen — not tuned after looking at
any output):
  - restricted to games with an eval present on every one of the first
    30 plies (moves 1-15, both colours);
  - each eval is capped at +-1000cp before any comparison, so a mate
    score doesn't register as an arbitrarily large swing;
  - a "swing" is a move where the (capped) eval changes by >=100cp from
    the previous move;
  - a "lead change" is a move where the (capped) eval goes from >=+100
    to <=-100, or the reverse (White's POV).

Per corpus x format, and per (format, gap_bin) using the same shared
0-100/101-250/251+ gap bins C4 uses: mean swings per game, mean lead
changes per game, the share of games with >=1 lead change, and the
Chess960-minus-standard difference on each, with a two-way (White-player
x Black-player) multiplicative cluster-bootstrap 95% CI (the standard
"pigeonhole" construction for multiway cluster bootstrap on an arbitrary
per-game statistic) and a leave-one-tournament-out range.

Writes ingame_swings.csv: one row per (format, gap_bin), gap_bin="all"
for the no-gap-bin-breakdown row.

Also writes outcome_volatility.csv (Claim 3, METHODOLOGY.md's C3 section):
per (format, gap_bin), Var = w + d/4 - (w+d/2)^2 (w = favorite win rate,
d = draw rate) for each corpus, the Chess960/standard ratio with a
two-way (favorite-player x underdog-player) cluster-bootstrap 95% CI, and
a leave-one-tournament-out range for the ratio.

Run:  PYTHONPATH=. .venv-pipeline/bin/python -m pipeline.analysis.volatility
"""
from __future__ import annotations

import re

import chess
import chess.pgn
import numpy as np
import pandas as pd

from pipeline.analysis.c5_bin_table import BIN_EDGES, BIN_LABELS
from pipeline.config import (
    BOOTSTRAP_ITERATIONS,
    CORPORA,
    DEFAULT_SEED,
    FORMATS,
    FREESTYLE_MANIFEST_PATH,
    MATE_SCORE_CP,
    MIN_ELO,
    STANDARD_MANIFEST_PATH,
)
from pipeline.ingest import filters
from pipeline.ingest.manifest_loader import load_corpus, load_manifest

N_BOOT = BOOTSTRAP_ITERATIONS
SWING_THRESHOLD_CP = 100.0
LEAD_THRESHOLD_CP = 100.0
EVAL_CAP_CP = 1000.0
N_PLIES = 30  # moves 1-15, both colours

Z = 1.959963984540054
_EVAL_VALUE_RE = re.compile(r"\[%eval\s+([^\]]+)\]")


def _parse_eval_white_cp(eval_str: str | None) -> float | None:
    if not eval_str:
        return None
    eval_str = eval_str.strip()
    if eval_str.startswith("#"):
        try:
            n = int(eval_str[1:])
        except ValueError:
            return None
        return float(MATE_SCORE_CP) if n > 0 else -float(MATE_SCORE_CP)
    try:
        return float(eval_str) * 100.0
    except ValueError:
        return None


def game_eval_trace(game: chess.pgn.Game) -> list[float] | None:
    """Capped (+-EVAL_CAP_CP) White-POV eval at each of the first
    N_PLIES real plies, or None if fewer than N_PLIES plies exist or any
    of them lacks an eval tag."""
    evals: list[float] = []
    board = game.board()
    node = game
    while node.variations and len(evals) < N_PLIES:
        child = node.variations[0]
        if child.move == chess.Move.null():
            break
        try:
            board.push(child.move)
        except (ValueError, AssertionError):
            break
        node = child
        comment = node.comment or ""
        m = _EVAL_VALUE_RE.search(comment)
        cp = _parse_eval_white_cp(m.group(1)) if m else None
        if cp is None:
            return None
        evals.append(max(-EVAL_CAP_CP, min(EVAL_CAP_CP, cp)))
    return evals if len(evals) == N_PLIES else None


def build_game_table() -> pd.DataFrame:
    manifest_df = load_manifest(FREESTYLE_MANIFEST_PATH, STANDARD_MANIFEST_PATH, observations_log=None)
    rows = []
    for corpus in CORPORA:
        for fmt in FORMATS:
            games = load_corpus(manifest_df, corpus, fmt, source="updated_engine_eval", log_path=None)
            games = filters.filter_broadcast_anomalies(games, None)
            games = filters.filter_by_elo(games, MIN_ELO, None)
            n_total, n_included = len(games), 0
            for game in games:
                trace = game_eval_trace(game)
                if trace is None:
                    continue
                n_included += 1
                arr = np.array(trace)
                diffs = np.diff(arr)
                swings = int((np.abs(diffs) >= SWING_THRESHOLD_CP).sum())
                lead_changes = 0
                for i in range(1, len(arr)):
                    prev, cur = arr[i - 1], arr[i]
                    if (prev >= LEAD_THRESHOLD_CP and cur <= -LEAD_THRESHOLD_CP) or (
                        prev <= -LEAD_THRESHOLD_CP and cur >= LEAD_THRESHOLD_CP
                    ):
                        lead_changes += 1
                we = pd.to_numeric(game.headers.get("WhiteElo"), errors="coerce")
                be = pd.to_numeric(game.headers.get("BlackElo"), errors="coerce")
                rows.append({
                    "corpus": corpus, "format": fmt,
                    "source_event": game.headers.get("SourceEvent", ""),
                    "white_player": game.headers.get("White", ""),
                    "black_player": game.headers.get("Black", ""),
                    "gap": abs(we - be) if pd.notna(we) and pd.notna(be) else np.nan,
                    "swings": swings, "lead_changes": lead_changes,
                    "ge1_lead_change": 1.0 if lead_changes >= 1 else 0.0,
                })
            print(f"[volatility] {corpus}/{fmt}: {n_total} games loaded, {n_included} with full {N_PLIES}-ply eval")
    out = pd.DataFrame(rows)
    out["gap_bin"] = pd.cut(out["gap"], bins=BIN_EDGES, labels=BIN_LABELS)
    return out


def cluster_codes(arr: np.ndarray) -> tuple[np.ndarray, int]:
    uniq, codes = np.unique(arr, return_inverse=True)
    return codes, uniq.size


def two_way_boot(
    values: np.ndarray, codes1: np.ndarray, n1: int, codes2: np.ndarray, n2: int,
    n_iterations: int, rng: np.random.Generator,
) -> np.ndarray:
    """Multiplicative two-way cluster bootstrap: each iteration
    independently resamples cluster-1 and cluster-2 identities (with
    replacement, same counts as original); a game's bootstrap weight is
    the product of how many times its two identities were drawn."""
    out = np.empty(n_iterations)
    for it in range(n_iterations):
        cnt1 = np.bincount(rng.integers(0, n1, size=n1), minlength=n1).astype(float)
        cnt2 = np.bincount(rng.integers(0, n2, size=n2), minlength=n2).astype(float)
        w = cnt1[codes1] * cnt2[codes2]
        wsum = w.sum()
        out[it] = float((w * values).sum() / wsum) if wsum > 0 else float("nan")
    return out


def _diff_ci(fs: pd.DataFrame, std: pd.DataFrame, col: str, seed: int = DEFAULT_SEED) -> dict:
    fs_vals, std_vals = fs[col].to_numpy(dtype=float), std[col].to_numpy(dtype=float)
    point = float(fs_vals.mean() - std_vals.mean())

    codes_w_fs, n_w_fs = cluster_codes(fs["white_player"].to_numpy())
    codes_b_fs, n_b_fs = cluster_codes(fs["black_player"].to_numpy())
    codes_w_std, n_w_std = cluster_codes(std["white_player"].to_numpy())
    codes_b_std, n_b_std = cluster_codes(std["black_player"].to_numpy())

    boot_fs = two_way_boot(fs_vals, codes_w_fs, n_w_fs, codes_b_fs, n_b_fs, N_BOOT, np.random.default_rng(seed))
    boot_std = two_way_boot(std_vals, codes_w_std, n_w_std, codes_b_std, n_b_std, N_BOOT, np.random.default_rng(seed + 1))
    diff_boot = boot_fs - boot_std
    lo, hi = np.nanpercentile(diff_boot, [2.5, 97.5])

    all_events = sorted(set(fs["source_event"].dropna().unique()) | set(std["source_event"].dropna().unique()))
    loto_diffs = []
    for ev in all_events:
        fs_ex, std_ex = fs[fs["source_event"] != ev], std[std["source_event"] != ev]
        if len(fs_ex) == len(fs) and len(std_ex) == len(std):
            continue
        if len(fs_ex) == 0 or len(std_ex) == 0:
            continue
        loto_diffs.append(float(fs_ex[col].mean() - std_ex[col].mean()))
    loto_min = min(loto_diffs) if loto_diffs else float("nan")
    loto_max = max(loto_diffs) if loto_diffs else float("nan")

    return {"diff": point, "ci_lower": float(lo), "ci_upper": float(hi),
            "loto_min": loto_min, "loto_max": loto_max, "n_loto_exclusions": len(loto_diffs)}


def summarize(df: pd.DataFrame, gap_bin_label: str | None) -> dict:
    fs = df[df["corpus"] == "freestyle"]
    std = df[df["corpus"] == "standard"]
    row: dict = {"n_chess960": len(fs), "n_standard": len(std)}
    if len(fs) == 0 or len(std) == 0:
        return row
    row["mean_swings_chess960"] = float(fs["swings"].mean())
    row["mean_swings_standard"] = float(std["swings"].mean())
    row["mean_lead_changes_chess960"] = float(fs["lead_changes"].mean())
    row["mean_lead_changes_standard"] = float(std["lead_changes"].mean())
    row["share_ge1_lead_change_chess960"] = float(fs["ge1_lead_change"].mean())
    row["share_ge1_lead_change_standard"] = float(std["ge1_lead_change"].mean())

    for prefix, col in (("swings", "swings"), ("lead_changes", "lead_changes"), ("share_ge1_lead", "ge1_lead_change")):
        stats_d = _diff_ci(fs, std, col)
        for k, v in stats_d.items():
            row[f"{prefix}_{k}"] = v
    return row


def main() -> pd.DataFrame:
    game_table = build_game_table()

    rows = []
    for fmt in FORMATS:
        sub = game_table[game_table["format"] == fmt]
        row = {"format": fmt, "gap_bin": "all"}
        row.update(summarize(sub, None))
        rows.append(row)
        for gb in BIN_LABELS:
            sub_gb = sub[sub["gap_bin"] == gb]
            row = {"format": fmt, "gap_bin": gb}
            row.update(summarize(sub_gb, gb))
            rows.append(row)

    out = pd.DataFrame(rows)
    from pipeline.config import RESULTS_DIR
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "ingame_swings.csv"
    out.to_csv(path, index=False)
    with pd.option_context("display.max_columns", None, "display.width", 260):
        print(out.round(4).to_string(index=False))
    print(f"\n[volatility] wrote {path.name} ({len(out)} rows)")

    outcome_vol = outcome_volatility()
    vol_path = RESULTS_DIR / "outcome_volatility.csv"
    outcome_vol.to_csv(vol_path, index=False)
    with pd.option_context("display.max_columns", None, "display.width", 260):
        print(outcome_vol.round(4).to_string(index=False))
    print(f"\n[volatility] wrote {vol_path.name} ({len(outcome_vol)} rows)")

    return out


# ---------------------------------------------------------------------
# Claim 3 — outcome volatility: Var = w + d/4 - (w+d/2)^2 (w = favorite
# win rate, d = draw rate), mathematically equivalent to the draw-rate
# result at a fixed expected score: at a fixed w, Var increases as d
# falls, so a lower draw rate (C3's result) necessarily raises this
# variance whenever the win rate doesn't move enough to offset it.
# ---------------------------------------------------------------------


def _var_from_w_d(w, d):
    return w + d / 4.0 - (w + d / 2.0) ** 2


def outcome_volatility(n_iterations: int = N_BOOT, seed: int = DEFAULT_SEED) -> pd.DataFrame:
    from pipeline.analysis.c5_bin_table import get_c34, prep

    def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        we = pd.to_numeric(out["white_elo"], errors="coerce")
        be = pd.to_numeric(out["black_elo"], errors="coerce")
        lower_is_white = we < be
        out["underdog_player"] = np.where(lower_is_white, out["white_player"], out["black_player"])
        out["favourite_player"] = np.where(lower_is_white, out["black_player"], out["white_player"])
        out["favourite_win"] = (~out["_lower_won"] & ~out["_draw"]).astype(float)
        out["draw_ind"] = out["_draw"].astype(float)
        return out

    rows = []
    for fmt in FORMATS:
        fs_all = add_indicators(prep(get_c34("freestyle", fmt)))
        std_all = add_indicators(prep(get_c34("standard", fmt)))
        for gb in BIN_LABELS:
            fs = fs_all[fs_all["_gap_bin"] == gb].reset_index(drop=True)
            std = std_all[std_all["_gap_bin"] == gb].reset_index(drop=True)

            w_fs, d_fs = fs["favourite_win"].mean(), fs["draw_ind"].mean()
            w_std, d_std = std["favourite_win"].mean(), std["draw_ind"].mean()
            var_fs, var_std = _var_from_w_d(w_fs, d_fs), _var_from_w_d(w_std, d_std)
            ratio_point = var_fs / var_std if var_std else float("nan")

            codes_fav_fs, n_fav_fs = cluster_codes(fs["favourite_player"].to_numpy())
            codes_und_fs, n_und_fs = cluster_codes(fs["underdog_player"].to_numpy())
            codes_fav_std, n_fav_std = cluster_codes(std["favourite_player"].to_numpy())
            codes_und_std, n_und_std = cluster_codes(std["underdog_player"].to_numpy())

            boot_w_fs = two_way_boot(fs["favourite_win"].to_numpy(), codes_fav_fs, n_fav_fs,
                                      codes_und_fs, n_und_fs, n_iterations, np.random.default_rng(seed))
            boot_d_fs = two_way_boot(fs["draw_ind"].to_numpy(), codes_fav_fs, n_fav_fs,
                                      codes_und_fs, n_und_fs, n_iterations, np.random.default_rng(seed))
            boot_w_std = two_way_boot(std["favourite_win"].to_numpy(), codes_fav_std, n_fav_std,
                                       codes_und_std, n_und_std, n_iterations, np.random.default_rng(seed + 1))
            boot_d_std = two_way_boot(std["draw_ind"].to_numpy(), codes_fav_std, n_fav_std,
                                       codes_und_std, n_und_std, n_iterations, np.random.default_rng(seed + 1))

            var_fs_boot = _var_from_w_d(boot_w_fs, boot_d_fs)
            var_std_boot = _var_from_w_d(boot_w_std, boot_d_std)
            ratio_boot = var_fs_boot / var_std_boot
            ci_lo, ci_hi = np.nanpercentile(ratio_boot, [2.5, 97.5])

            all_events = sorted(set(fs["source_event"].dropna().unique()) | set(std["source_event"].dropna().unique()))
            loto_ratios = []
            for ev in all_events:
                fs_ex, std_ex = fs[fs["source_event"] != ev], std[std["source_event"] != ev]
                if len(fs_ex) == len(fs) and len(std_ex) == len(std):
                    continue
                if len(fs_ex) == 0 or len(std_ex) == 0:
                    continue
                w_fs_ex, d_fs_ex = fs_ex["favourite_win"].mean(), fs_ex["draw_ind"].mean()
                w_std_ex, d_std_ex = std_ex["favourite_win"].mean(), std_ex["draw_ind"].mean()
                v_fs_ex, v_std_ex = _var_from_w_d(w_fs_ex, d_fs_ex), _var_from_w_d(w_std_ex, d_std_ex)
                if v_std_ex:
                    loto_ratios.append(v_fs_ex / v_std_ex)
            loto_min = min(loto_ratios) if loto_ratios else float("nan")
            loto_max = max(loto_ratios) if loto_ratios else float("nan")

            rows.append({
                "format": fmt, "gap_bin": gb,
                "chess960_n": len(fs), "standard_n": len(std),
                "chess960_w": w_fs, "chess960_d": d_fs, "chess960_var": var_fs,
                "standard_w": w_std, "standard_d": d_std, "standard_var": var_std,
                "ratio_chess960_over_standard": ratio_point,
                "ratio_ci_lower": float(ci_lo), "ratio_ci_upper": float(ci_hi),
                "loto_ratio_min": loto_min, "loto_ratio_max": loto_max,
                "n_loto_exclusions": len(loto_ratios),
            })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    main()
