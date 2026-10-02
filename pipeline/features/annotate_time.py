"""Time annotation stage of the annotated-PGN pipeline: tag every move with
[%tspent SS.ss] time-spent, computed from existing [%clk] annotations (no
engine call). Reuses clock_parser's chain-break semantics — an uncomputable
move is left untagged, never guessed.

Writes an intermediate PGN under data/processed/Updated_Time/ (via annotate_time_batch.py).
The engine evaluation stage (engine_annotate_standalone.py, run separately)
adds [%eval] on top and writes Updated_engine_eval/; scalars are then
extracted from those two trees downstream.

Increment/base resolution order: scalar arg -> per-event manifest map -> (if
header_fallback) the game's own TimeControl header -> none. No header fallback by
default — the manifest's time_control_pgn column is always authoritative.
"""

from __future__ import annotations

import re
from pathlib import Path

import chess
import chess.pgn

from pipeline.features.clock_parser import (
    _per_side_times,
    _per_side_times_periods,
    parse_pgn_time_control,
)
from pipeline.ingest import audit_log

_TSPENT_RE = re.compile(r"\[%tspent[^\]]*\]\s*")


def _strip_tspent(comment: str | None) -> str:
    """Remove any existing [%tspent …] tag from a move comment, keep the rest."""
    return _TSPENT_RE.sub("", comment or "").strip()


def _with_tspent(comment: str | None, seconds: float) -> str:
    """Return comment with [%tspent SS.ss] prepended, replacing any prior tag."""
    rest = _strip_tspent(comment)
    tag = f"[%tspent {seconds:.2f}]"
    return f"{tag} {rest}" if rest else tag


def annotate_time_one_game(
    game: chess.pgn.Game, increment: float, base_time: float | None,
    periods: list | None = None,
) -> dict:
    """Tag every computable move of game with [%tspent], in place.

    periods, if given, takes precedence over the flat increment/base_time pair, so a
    composite time control's later periods are honoured past the first period's move
    limit. Fully idempotent: every node's [%tspent] is cleared before deciding whether
    to write a new one, so a ply that can't be computed this run never keeps a stale
    value from a previous run under a different time control.

    Returns {"played": int, "tagged": int}.
    """
    if periods:
        state = _per_side_times_periods(game, periods)
    else:
        state = _per_side_times(game, increment, base_time)
    time_by_n = {
        chess.WHITE: dict(state[chess.WHITE]["times"]),
        chess.BLACK: dict(state[chess.BLACK]["times"]),
    }
    own_no = {chess.WHITE: 0, chess.BLACK: 0}

    board = game.board()
    node = game
    played = 0
    tagged = 0
    while node.variations:
        node = node.variations[0]
        mover = board.turn
        try:
            board.push(node.move)
        except (ValueError, AssertionError):
            break  # corrupt line; matches _per_side_times' own stopping point
        played += 1
        own_no[mover] += 1
        t = time_by_n[mover].get(own_no[mover])
        if t is not None:
            node.comment = _with_tspent(node.comment, t)
            tagged += 1
        else:
            # no fresh value - clear any stale [%tspent] rather than leaving it in place
            node.comment = _strip_tspent(node.comment)

    return {"played": played, "tagged": tagged}


def annotate_time_games(
    games: list[chess.pgn.Game],
    out_path: str | Path,
    increment_seconds: float | None = None,
    base_seconds: float | None = None,
    increment_by_event: dict[str, float] | None = None,
    base_by_event: dict[str, float] | None = None,
    periods_by_event: dict[str, list] | None = None,
    header_fallback: bool = False,
    log_path: str | Path | None = None,
) -> dict:
    """Write the time-annotated PGN for one stratum (idempotent, overwrites out_path
    in full). periods_by_event, when set for an event, takes precedence over
    increment_by_event/base_by_event so a composite time control's later periods are
    honoured. header_fallback controls whether the game's own TimeControl header is used
    when no manifest value is found (default off — manifest is authoritative).

    Returns {"n_games", "total_plies", "tagged_plies", "coverage_pct"}.
    """
    increment_by_event = increment_by_event or {}
    base_by_event = base_by_event or {}
    periods_by_event = periods_by_event or {}
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    events_without_increment: set[str] = set()
    total_plies = 0
    tagged_plies = 0

    with open(out_path, "w", encoding="utf-8") as fh:
        exporter = chess.pgn.FileExporter(fh)
        for game in games:
            event = game.headers.get("SourceEvent", "")
            periods = periods_by_event.get(event)
            if periods:
                stats = annotate_time_one_game(game, 0.0, None, periods=periods)
                total_plies += stats["played"]
                tagged_plies += stats["tagged"]
                game.accept(exporter)
                continue

            _tc_base, _tc_inc = (
                parse_pgn_time_control(game.headers.get("TimeControl")) if header_fallback else (None, None)
            )
            inc = increment_seconds if increment_seconds is not None else increment_by_event.get(event, _tc_inc)
            base = base_seconds if base_seconds is not None else base_by_event.get(event, _tc_base)

            if inc is None and event not in events_without_increment:
                events_without_increment.add(event)
                if log_path is not None:
                    audit_log.log_data_observation(
                        log_path, "event", event,
                        "no increment available for time annotation (manifest column empty/"
                        "unparseable, header_fallback off) — tspent coverage for this event will be near zero",
                        corpus=game.headers.get("Corpus", ""),
                        format=game.headers.get("StratumFormat", ""),
                    )
            inc = 0.0 if inc is None else inc

            stats = annotate_time_one_game(game, inc, base)
            total_plies += stats["played"]
            tagged_plies += stats["tagged"]
            game.accept(exporter)

    coverage = (tagged_plies / total_plies * 100.0) if total_plies else float("nan")
    summary = {
        "n_games": len(games),
        "total_plies": total_plies,
        "tagged_plies": tagged_plies,
        "coverage_pct": coverage,
    }
    if log_path is not None:
        audit_log.log_data_observation(
            log_path, "run", str(out_path.name),
            f"Time annotation: {len(games)} games, {tagged_plies}/{total_plies} "
            f"plies tagged ({coverage:.1f}% coverage)",
        )
    print(f"[annotate_time] wrote {len(games)} games, {tagged_plies}/{total_plies} plies "
          f"tagged ({coverage:.1f}%) -> {out_path}")
    return summary
