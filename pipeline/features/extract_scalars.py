"""Per-game outcome-scalar extraction (Elo, result), using only what's
available before the engine evaluation stage has run.
"""

from __future__ import annotations

from pathlib import Path

import chess.pgn
import pandas as pd

OUTCOME_COLUMNS: tuple[str, ...] = (
    "game_id",
    "source_event",
    "source_type",
    "corpus",
    "format",
    "white_player",
    "black_player",
    "white_elo",
    "black_elo",
    "result",
)

SCALAR_COLUMNS: tuple[str, ...] = OUTCOME_COLUMNS


def _game_outcome(game: chess.pgn.Game) -> dict:
    """Elo, result, and provenance from game headers."""
    return {
        "game_id": game.headers.get("GameId", ""),
        "source_event": game.headers.get("SourceEvent", ""),
        "source_type": game.headers.get("SourceType", ""),
        "corpus": game.headers.get("Corpus", ""),
        "format": game.headers.get("StratumFormat", ""),
        "white_player": game.headers.get("White", ""),
        "black_player": game.headers.get("Black", ""),
        "white_elo": pd.to_numeric(game.headers.get("WhiteElo"), errors="coerce"),
        "black_elo": pd.to_numeric(game.headers.get("BlackElo"), errors="coerce"),
        "result": game.headers.get("Result", ""),
    }


def extract_outcome_scalars(games: list[chess.pgn.Game]) -> pd.DataFrame:
    """One row per game: Elo, result, provenance.

    Feeds C4 (and via scalars parquet, C3 script).
    """
    out = pd.DataFrame([_game_outcome(g) for g in games], columns=list(OUTCOME_COLUMNS))
    out["white_elo"] = pd.to_numeric(out["white_elo"], errors="coerce")
    out["black_elo"] = pd.to_numeric(out["black_elo"], errors="coerce")
    return out


def extract_scalars(
    games: list[chess.pgn.Game],
    output_path: str | Path | None = None,
) -> pd.DataFrame:
    """One row per game: Elo, result, and provenance."""
    out = extract_outcome_scalars(games)
    out = out[list(SCALAR_COLUMNS)]

    if output_path is not None:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        out.to_parquet(tmp, engine="pyarrow", index=False)
        tmp.replace(out_path)
        print(f"[extract_scalars] wrote {len(out)} rows -> {out_path}")

    return out
