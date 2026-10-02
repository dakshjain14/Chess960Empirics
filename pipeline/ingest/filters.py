"""filters.py — the two ingest filters (broadcast anomalies, then Elo floor).

Every excluded game is logged via audit_log.log_exclusion(); nothing is
dropped silently. Context fields (corpus/format/event/game_id) are read off
the headers manifest_loader.load_corpus() stamps on each game.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import chess
import chess.pgn

from pipeline.config import MIN_ELO
from pipeline.ingest import audit_log


def _ctx(game: chess.pgn.Game) -> dict[str, str]:
    """Audit-log context fields off a game's headers."""
    return {
        "event": game.headers.get("SourceEvent", game.headers.get("Event", "<unknown>")),
        "game_id": game.headers.get("GameId", "<unassigned>"),
        "corpus": game.headers.get("Corpus", ""),
        "format": game.headers.get("StratumFormat", ""),
    }


def _log(log_path: str | Path | None, game: chess.pgn.Game, stage: str, reason: str,
         details: dict | None = None) -> None:
    """Log one exclusion, or no-op if log_path is None."""
    if log_path is None:
        return
    c = _ctx(game)
    audit_log.log_exclusion(
        log_path, c["event"], c["game_id"], c["corpus"], c["format"], stage, reason, details
    )


def _n_plies(game: chess.pgn.Game) -> int:
    """Number of plies in mainline (including null-move placeholders)."""
    n = 0
    for _ in game.mainline_moves():
        n += 1
    return n


def _n_real_moves(game: chess.pgn.Game) -> int:
    """Count non-null moves, stopping at first null move (-- placeholder)."""
    n = 0
    for m in game.mainline_moves():
        if m == chess.Move.null():
            break
        n += 1
    return n


# Filter 1 — broadcast anomalies. To add a signature: write one more
# _check_* function (return (reason, details) or None) and append it below.


def _check_zero_ply(game: chess.pgn.Game) -> tuple[str, dict] | None:
    """Forfeits / no-shows: a game with no moves is not real chess."""
    if _n_plies(game) == 0:
        declared = game.headers.get("PlyCount")
        return "zero_ply", {"declared_plycount": declared}
    return None


def _check_single_ply_forfeit(game: chess.pgn.Game) -> tuple[str, dict] | None:
    """<2 real plies can't legally reach any conclusion in standard chess or
    any Chess960 setup (the rank-2/7 pawn wall blocks every back-rank piece
    either way), so it's a forfeit regardless of the Termination label.
    Catches padded forfeits (one real move + null-move filler) that
    _check_zero_ply misses. Deliberately not extended to 2-9 real moves —
    that range is dominated by genuinely short, fully-played games."""
    n = _n_real_moves(game)
    if n < 2:
        return "unplayed_forfeit", {"n_real_moves": n, "termination": game.headers.get("Termination")}
    return None


def _check_missing_fen(game: chess.pgn.Game) -> tuple[str, dict] | None:
    """Freestyle games must carry a parseable Chess960 starting FEN."""
    if game.headers.get("Corpus", "").lower() != "freestyle":
        return None
    fen = game.headers.get("FEN", "").strip()
    if not fen:
        return "missing_fen", {"fen": None}
    try:
        chess.Board(fen, chess960=True)
    except ValueError as exc:
        return "missing_fen", {"fen": fen, "error": str(exc)}
    return None


#: Stateless single-game checks, run in listed order.
_ANOMALY_CHECKS: tuple[Callable[[chess.pgn.Game], "tuple[str, dict] | None"], ...] = (
    _check_zero_ply,
    _check_single_ply_forfeit,
    _check_missing_fen,
)


def filter_broadcast_anomalies(
    games: list[chess.pgn.Game], log_path: str | Path | None = None
) -> list[chess.pgn.Game]:
    """Drop zero_ply / unplayed_forfeit / missing_fen / duplicate_game_id games."""
    kept: list[chess.pgn.Game] = []
    seen_ids_by_event: dict[str, set[str]] = {}

    for game in games:
        c = _ctx(game)
        dropped = False

        # stateful check: duplicate game_id within a source file
        seen = seen_ids_by_event.setdefault(c["event"], set())
        if c["game_id"] in seen:
            _log(log_path, game, "anomaly_filter", "duplicate_game_id",
                 {"game_id": c["game_id"], "event": c["event"]})
            dropped = True
        else:
            seen.add(c["game_id"])

        # stateless checks
        if not dropped:
            for check in _ANOMALY_CHECKS:
                result = check(game)
                if result is not None:
                    reason, details = result
                    _log(log_path, game, "anomaly_filter", reason, details)
                    dropped = True
                    break

        if not dropped:
            kept.append(game)

    return kept


# Filter 2 — Elo floor


def _parse_elo(value: str | None) -> int | None:
    """Parse header Elo string to int, or None if missing/?/non-numeric."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "?":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def filter_by_elo(
    games: list[chess.pgn.Game], min_elo: int = MIN_ELO, log_path: str | Path | None = None
) -> list[chess.pgn.Game]:
    """Drop games unless both players' Elo is present, parseable, and >= min_elo."""
    kept: list[chess.pgn.Game] = []
    for game in games:
        we_raw = game.headers.get("WhiteElo")
        be_raw = game.headers.get("BlackElo")
        we, be = _parse_elo(we_raw), _parse_elo(be_raw)

        if we is None or be is None:
            _log(log_path, game, "elo_filter", "elo_unparseable",
                 {"white_elo_raw": we_raw, "black_elo_raw": be_raw})
            continue
        if we < min_elo or be < min_elo:
            _log(log_path, game, "elo_filter", "elo_below_floor",
                 {"white_elo": we, "black_elo": be, "min_elo": min_elo})
            continue
        kept.append(game)
    return kept
