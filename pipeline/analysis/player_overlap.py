"""player_overlap.py — within-player paired comparison across corpora.

Chess960 and standard chess share a real population of players, identified
by FIDE ID. Instead of comparing the two corpora's populations (which could
differ in composition), this compares each overlapping player to
themselves, removing skill-composition as a possible confound for H1a's
opening-ACPL/OTR finding.

FIDE IDs are read from Updated_engine_eval/ — the same tree Stage 1 reads to
build game_features.parquet — so the join on (corpus, format, game_id, side)
holds by construction, not just by both trees happening to stay in lock-step.
When that tree isn't on disk (e.g. a fresh clone with no Stockfish run),
main() falls back to build_fide_id_map_from_raw_pgns(), which reads the same
FideId tags from the tracked raw PGNs in data/games/ instead — safe because
rating/time/engine annotation never reorders or drops games, so the same
per-event positional game_id lines up with game_features.parquet's either
way (see that function's docstring for the one caveat).

For every FIDE ID with >= min_games rows in both corpora, runs a Wilcoxon
signed-rank test on that player's paired per-player mean opening_acpl/otr
(rank-based — the overlap sample is small and non-normal).
"""

from __future__ import annotations

from pathlib import Path

import chess.pgn
import numpy as np
import pandas as pd
from scipy import stats

from pipeline.config import (
    CORPORA,
    FORMATS,
    FREESTYLE_MANIFEST_PATH,
    PROCESSED_DIR,
    RESULTS_DIR,
    STANDARD_MANIFEST_PATH,
    UPDATED_ENGINE_EVAL_DIR,
)
from pipeline.ingest import manifest_loader

GAME_FEATURES_PATH = PROCESSED_DIR / "game_features.parquet"


def build_fide_id_map() -> pd.DataFrame:
    """One row per (corpus, format, game_id, side, fide_id) — every game-side
    with a non-empty ``WhiteFideId``/``BlackFideId`` header, across all 4
    (corpus, format) combinations.

    Reads from ``Updated_engine_eval/`` (``source="updated_engine_eval"``) —
    the same tree ``h1_stage1_extract_per_move.py`` reads to build
    ``game_features.parquet`` — so the positionally-assigned ``game_id``
    this module joins on is guaranteed to line up with ``game_features``'s,
    rather than only holding as long as two independently-regenerated trees
    stay in lock-step.
    """
    manifest = manifest_loader.load_manifest(FREESTYLE_MANIFEST_PATH, STANDARD_MANIFEST_PATH)
    rows = []
    for corpus in CORPORA:
        for fmt in FORMATS:
            games = manifest_loader.load_corpus(manifest, corpus, fmt, source_type=None,
                                                 source="updated_engine_eval")
            for g in games:
                gid = g.headers.get("GameId", "")
                for side, prefix in (("white", "White"), ("black", "Black")):
                    fid = g.headers.get(f"{prefix}FideId", "").strip()
                    if fid and fid != "0":
                        rows.append(
                            {"corpus": corpus, "format": fmt, "game_id": gid, "side": side, "fide_id": fid}
                        )
    return pd.DataFrame(rows, columns=["corpus", "format", "game_id", "side", "fide_id"])


def build_fide_id_map_from_raw_pgns() -> pd.DataFrame:
    """Same output as build_fide_id_map(), but reads FideId tags directly
    from the tracked raw PGNs in data/games/ instead of Updated_engine_eval/
    (excluded from this repo, needs a Stockfish run to build).

    Game IDs still line up with game_features.parquet's: load_corpus
    assigns game_id positionally (f"{slug}_{idx:05d}") from iterating each
    event's file in order, and rating/time/engine annotation only patches
    header tags in place -- it never reorders, adds, or drops games -- so a
    raw file and its corrected copy share the same game order and count.

    Caveat: standard_rating_backfill.py's manual-candidates step (see
    Data_Selection.md) patches a handful of Standard games' FideId tags
    that the raw PGN doesn't carry. A player identifiable only through that
    patch won't appear in this fallback's map.
    """
    manifest = manifest_loader.load_manifest(FREESTYLE_MANIFEST_PATH, STANDARD_MANIFEST_PATH)
    rows = []
    for corpus in CORPORA:
        for fmt in FORMATS:
            mask = (manifest["corpus"] == corpus) & (manifest["format"] == fmt)
            for _, row in manifest.loc[mask].iterrows():
                path = row["filepath"]
                if not path or not Path(path).is_file():
                    continue
                slug = str(row["event_slug"])
                with open(path, encoding="utf-8", errors="replace") as fh:
                    idx = 0
                    while True:
                        game = chess.pgn.read_game(fh)
                        if game is None:
                            break
                        gid = f"{slug}_{idx:05d}"
                        for side, prefix in (("white", "White"), ("black", "Black")):
                            fid = game.headers.get(f"{prefix}FideId", "").strip()
                            if fid and fid != "0":
                                rows.append(
                                    {"corpus": corpus, "format": fmt, "game_id": gid, "side": side, "fide_id": fid}
                                )
                        idx += 1
    return pd.DataFrame(rows, columns=["corpus", "format", "game_id", "side", "fide_id"])


def overlap_counts(fide_df: pd.DataFrame, min_games: int = 5) -> pd.DataFrame:
    """One row per (format, threshold): distinct FIDE IDs clearing
    ``min_games`` in each corpus, and the overlap between them."""
    rows = []
    for fmt in FORMATS:
        sub = fide_df[fide_df["format"] == fmt]
        counts = sub.groupby(["corpus", "fide_id"]).size().rename("n").reset_index()
        for thresh in (1, 3, 5, 10, min_games):
            fs_ok = set(counts.loc[(counts.corpus == "freestyle") & (counts.n >= thresh), "fide_id"])
            std_ok = set(counts.loc[(counts.corpus == "standard") & (counts.n >= thresh), "fide_id"])
            rows.append(
                {
                    "format": fmt, "threshold": thresh,
                    "n_freestyle_qualifying": len(fs_ok), "n_standard_qualifying": len(std_ok),
                    "n_overlap": len(fs_ok & std_ok),
                }
            )
    return pd.DataFrame(rows).drop_duplicates(subset=["format", "threshold"]).reset_index(drop=True)


def paired_comparison(fmt: str, fide_df: pd.DataFrame, game_features: pd.DataFrame, min_games: int = 5) -> pd.DataFrame:
    """One row per FIDE ID with >= ``min_games`` rows in BOTH corpora for
    ``fmt``: each corpus's own mean ``opening_acpl``/``otr`` for that player."""
    merged = game_features.merge(
        fide_df, on=["corpus", "format", "game_id", "side"], how="inner"
    )
    sub = merged[merged["format"] == fmt]
    per_player = (
        sub.groupby(["fide_id", "corpus"])
        .agg(n_games=("game_id", "count"), mean_opening_acpl=("opening_acpl", "mean"), mean_otr=("otr", "mean"))
        .reset_index()
    )
    fs = per_player[(per_player.corpus == "freestyle") & (per_player.n_games >= min_games)]
    std = per_player[(per_player.corpus == "standard") & (per_player.n_games >= min_games)]
    return fs.merge(std, on="fide_id", suffixes=("_c960", "_std"))


def wilcoxon_on_paired(paired: pd.DataFrame, metric: str) -> dict:
    """Wilcoxon signed-rank test on ``paired``'s ``{metric}_c960`` vs.
    ``{metric}_std`` columns, dropping any pair with a NaN in either side.
    ``direction`` and ``n_positive``/``n_negative`` describe the sign of
    ``c960 - std`` per pair (positive = that player's Chess960 value is
    higher) — not just the aggregate mean/median diff, so a reader can see
    whether the effect is unanimous or just directionally dominant."""
    a, b = paired[f"{metric}_c960"], paired[f"{metric}_std"]
    ok = a.notna() & b.notna()
    a, b = a[ok].to_numpy(), b[ok].to_numpy()
    if len(a) < 5:
        return {"metric": metric, "n_pairs": int(len(a)), "median_diff": float("nan"),
                "mean_diff": float("nan"), "wilcoxon_statistic": float("nan"), "p_value": float("nan"),
                "n_positive": 0, "n_negative": 0, "direction": "insufficient_n"}
    diff = a - b
    try:
        w_stat, w_p = stats.wilcoxon(diff)
    except ValueError:
        w_stat, w_p = float("nan"), float("nan")
    n_pos, n_neg = int((diff > 0).sum()), int((diff < 0).sum())
    mean_diff = float(np.mean(diff))
    direction = "chess960 > standard" if mean_diff > 0 else ("chess960 < standard" if mean_diff < 0 else "tied")
    return {
        "metric": metric, "n_pairs": int(len(a)), "median_diff": float(np.median(diff)),
        "mean_diff": mean_diff, "wilcoxon_statistic": float(w_stat), "p_value": float(w_p),
        "n_positive": n_pos, "n_negative": n_neg, "direction": direction,
    }


def main(min_games: int = 5) -> dict[str, pd.DataFrame]:
    if UPDATED_ENGINE_EVAL_DIR.exists() and any(UPDATED_ENGINE_EVAL_DIR.rglob("*.pgn")):
        fide_df = build_fide_id_map()
    else:
        print("[player_overlap] Updated_engine_eval/ not found -- falling back to FideId "
              "tags read from the tracked raw PGNs in data/games/")
        fide_df = build_fide_id_map_from_raw_pgns()
    game_features = pd.read_parquet(GAME_FEATURES_PATH)

    counts = overlap_counts(fide_df, min_games)
    print(counts.to_string(index=False))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    counts.to_csv(RESULTS_DIR / "player_overlap_counts.csv", index=False)

    out: dict[str, pd.DataFrame] = {}
    stat_rows = []
    for fmt in FORMATS:
        paired = paired_comparison(fmt, fide_df, game_features, min_games)
        print(f"\n{fmt}: {len(paired)} players with >={min_games} games in both corpora")
        for metric in ("mean_opening_acpl", "mean_otr"):
            result = wilcoxon_on_paired(paired, metric)
            print(f"  {result}")
            stat_rows.append({"format": fmt, **result})
        path = RESULTS_DIR / f"player_paired_comparison_{fmt}.csv"
        paired.to_csv(path, index=False)
        print(f"  -> wrote {path}")
        out[fmt] = paired

    stats_path = RESULTS_DIR / "player_paired_comparison_stats.csv"
    pd.DataFrame(stat_rows).to_csv(stats_path, index=False)
    print(f"\n-> wrote {stats_path}")
    return out


if __name__ == "__main__":
    main()
