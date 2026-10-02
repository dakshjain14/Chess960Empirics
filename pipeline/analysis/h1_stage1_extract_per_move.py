"""Stage 1 of the H1a/H1b/C2 pipeline: parses the engine+clock-annotated
corpus (``data/processed/Updated_engine_eval/``, see ENGINE.md) into one row
per player per ply for the whole game. ``cpl`` is populated only where a
``[%eval]`` tag exists (the opening window); ``time_spent`` wherever
``[%tspent]`` exists (the whole game) — lets Stage 2 compute OTR's
full-game denominator without a second PGN read.

**CPL reconstruction.** The engine-annotation run only wrote a POST-move
eval per ply, so CPL for ply *i* is ``eval_before_i - eval_after_i`` where
``eval_before_i`` is ply *i-1*'s own post-move eval — except for White's
move 1, whose "before" eval (the start position) was never computed, so
White's move-1 CPL is always null.

**Game-level exclusions** (mirrors ``run_pipeline._load_and_filter``, minus
clock-data presence — CPL needs no clocks, and OTR nulls gracefully rather
than needing the game dropped): broadcast anomalies, then
:func:`_exclude_unplayed_forfeits` (the ``Termination == "Unplayed"`` +
2-9-real-ply case filter 1 doesn't cover — genuine forfeits cluster at 1
ply, real games at 46+), then the Elo floor. ``Result == "*"`` games with
real movetext are **kept** — H1a/H1b/C2 never use ``Result``.

Output: ``data/processed/per_move_data.parquet``, one row per (game, ply).
"""

from __future__ import annotations

import re
from pathlib import Path

import chess
import chess.pgn
import pandas as pd

from pipeline.config import (
    CORPORA,
    CPL_CAP,
    FORMATS,
    FREESTYLE_MANIFEST_PATH,
    MATE_SCORE_CP,
    MIN_ELO,
    PROCESSED_DIR,
    RESULTS_DIR,
    STANDARD_MANIFEST_PATH,
)
from pipeline.ingest import audit_log, filters
from pipeline.ingest.manifest_loader import load_corpus, load_manifest

_EVAL_VALUE_RE = re.compile(r"\[%eval\s+([^\]]+)\]")
_TSPENT_VALUE_RE = re.compile(r"\[%tspent\s+([\d.]+)\]")

PER_MOVE_COLUMNS: tuple[str, ...] = (
    "game_id",
    "source_event",
    "corpus",
    "format",
    "source_type",
    "side",
    "player_name",
    "move_number",
    "cpl",
    "time_spent",
    "own_rating",
    "opponent_rating",
)

OUT_PATH = PROCESSED_DIR / "per_move_data.parquet"
EXCLUSIONS_LOG = RESULTS_DIR / "h1_pipeline_exclusions.parquet"

#: Below this many real plies, a Termination=="Unplayed" game is treated as
#: a genuine forfeit rather than a mislabeled real game — wide margin
#: between the two clusters (forfeits ~1 ply, real games 46+).
UNPLAYED_MIN_PLIES = 10


def _parse_eval_white_cp(eval_str: str | None) -> float | None:
    """White-POV centipawns from a raw ``[%eval]`` value string, or ``None`` if
    absent/unparseable. Mate strings map to ``+-MATE_SCORE_CP``."""
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


def _n_real_moves(game: chess.pgn.Game) -> int:
    """Count of real (non-null) moves in ``game``'s mainline."""
    n = 0
    for m in game.mainline_moves():
        if m == chess.Move.null():
            break
        n += 1
    return n


def _exclude_unplayed_forfeits(
    games: list[chess.pgn.Game], log_path: str | Path | None = None
) -> list[chess.pgn.Game]:
    """Drops ``Termination == "Unplayed"`` games with fewer than
    :data:`UNPLAYED_MIN_PLIES` real plies (2-9 plies specifically — the
    <2-ply case is already handled upstream by
    ``filters.filter_broadcast_anomalies``). Other low-ply games (2-9 real
    plies, any ``Termination`` value) are deliberately left alone: that
    population is dominated by plain ``Termination: None`` with no other
    forfeit signal, indistinguishable from a legitimately short, fully-played
    decisive game. Do not exclude on ``Termination`` alone — only this
    ply-count-plus-``Unplayed`` combination has positive forfeit evidence."""
    kept = []
    for game in games:
        n = _n_real_moves(game)
        is_forfeit = game.headers.get("Termination", "") == "Unplayed" and n < UNPLAYED_MIN_PLIES
        if is_forfeit:
            if log_path is not None:
                audit_log.log_exclusion(
                    log_path,
                    game.headers.get("SourceEvent", ""),
                    game.headers.get("GameId", ""),
                    game.headers.get("Corpus", ""),
                    game.headers.get("StratumFormat", ""),
                    "anomaly_filter",
                    "unplayed_forfeit",
                    {
                        "result": game.headers.get("Result"),
                        "termination": game.headers.get("Termination"),
                        "white": game.headers.get("White"),
                        "black": game.headers.get("Black"),
                        "n_real_moves": n,
                    },
                )
            continue
        kept.append(game)
    return kept


def extract_game_rows(game: chess.pgn.Game) -> list[dict]:
    """Every ply of ``game`` as one row: ``cpl`` where a ``[%eval]`` tag
    exists, ``time_spent`` wherever ``[%tspent]`` exists. Stops at a PGN null
    move (defensive; such games are already excluded upstream). Carries
    ``source_type`` straight through, unused, so this expensive stage always
    covers the full corpus and downstream stages can filter on it themselves."""
    white_elo = pd.to_numeric(game.headers.get("WhiteElo"), errors="coerce")
    black_elo = pd.to_numeric(game.headers.get("BlackElo"), errors="coerce")
    white_name = game.headers.get("White", "")
    black_name = game.headers.get("Black", "")
    game_id = game.headers.get("GameId", "")
    source_event = game.headers.get("SourceEvent", "")
    corpus = game.headers.get("Corpus", "")
    fmt = game.headers.get("StratumFormat", "")
    source_type = game.headers.get("SourceType", "")

    rows: list[dict] = []
    own_no = {chess.WHITE: 0, chess.BLACK: 0}
    prev_white_cp: float | None = None
    board = game.board()
    node = game
    while node.variations:
        child = node.variations[0]
        if child.move == chess.Move.null():
            break
        mover = board.turn
        try:
            board.push(child.move)
        except (ValueError, AssertionError):
            break
        node = child
        own_no[mover] += 1

        comment = node.comment or ""
        eval_m = _EVAL_VALUE_RE.search(comment)
        after_white_cp = _parse_eval_white_cp(eval_m.group(1)) if eval_m else None

        cpl = None
        if after_white_cp is not None and prev_white_cp is not None:
            before_mover = prev_white_cp if mover == chess.WHITE else -prev_white_cp
            after_mover = after_white_cp if mover == chess.WHITE else -after_white_cp
            cpl = min(max(before_mover - after_mover, 0.0), float(CPL_CAP))
        prev_white_cp = after_white_cp

        tspent_m = _TSPENT_VALUE_RE.search(comment)
        time_spent = float(tspent_m.group(1)) if tspent_m else None

        side = "white" if mover == chess.WHITE else "black"
        rows.append(
            {
                "game_id": game_id,
                "source_event": source_event,
                "corpus": corpus,
                "format": fmt,
                "source_type": source_type,
                "side": side,
                "player_name": white_name if mover == chess.WHITE else black_name,
                "move_number": own_no[mover],
                "cpl": cpl,
                "time_spent": time_spent,
                "own_rating": white_elo if mover == chess.WHITE else black_elo,
                "opponent_rating": black_elo if mover == chess.WHITE else white_elo,
            }
        )
    return rows


def main() -> pd.DataFrame:
    """Always the full corpus (every source_type) — downstream stages filter
    on the carried-through ``source_type`` column themselves."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    for f in (EXCLUSIONS_LOG, audit_log.observations_path_for(EXCLUSIONS_LOG)):
        Path(f).unlink(missing_ok=True)

    manifest_df = load_manifest(
        FREESTYLE_MANIFEST_PATH, STANDARD_MANIFEST_PATH, observations_log=EXCLUSIONS_LOG
    )

    all_rows: list[dict] = []
    n_loaded = 0
    n_kept = 0

    for corpus in CORPORA:
        for fmt in FORMATS:
            games = load_corpus(
                manifest_df, corpus, fmt,
                source="updated_engine_eval", log_path=EXCLUSIONS_LOG,
            )
            n_raw = len(games)
            games = filters.filter_broadcast_anomalies(games, EXCLUSIONS_LOG)
            games = _exclude_unplayed_forfeits(games, EXCLUSIONS_LOG)
            games = filters.filter_by_elo(games, MIN_ELO, EXCLUSIONS_LOG)
            n_loaded += n_raw
            n_kept += len(games)
            print(f"[stage1] {corpus}/{fmt}: raw {n_raw} -> kept {len(games)}")

            for game in games:
                all_rows.extend(extract_game_rows(game))

    df = pd.DataFrame(all_rows, columns=list(PER_MOVE_COLUMNS))
    df["move_number"] = df["move_number"].astype("Int64")
    df["cpl"] = pd.to_numeric(df["cpl"], errors="coerce")
    df["time_spent"] = pd.to_numeric(df["time_spent"], errors="coerce")
    df["own_rating"] = pd.to_numeric(df["own_rating"], errors="coerce").astype("Int64")
    df["opponent_rating"] = pd.to_numeric(df["opponent_rating"], errors="coerce").astype("Int64")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix(OUT_PATH.suffix + ".tmp")
    df.to_parquet(tmp, engine="pyarrow", index=False)
    tmp.replace(OUT_PATH)

    print(
        f"\n[stage1] games loaded: {n_loaded}, games kept: {n_kept}, "
        f"distinct games with >=1 row: {df['game_id'].nunique()}, "
        f"rows written: {len(df)} -> {OUT_PATH}"
    )
    return df


if __name__ == "__main__":
    main()
