"""PGN time-control parsing and per-move time computation.

The manifest's time_control_pgn column is always the source of a game's
time control — never the PGN's own TimeControl header, never a filename.

Per-move time = clock_before_N - clock_after_N + increment, where
clock_before_N is the clock reading after the player's previous move
([%clk] shows time remaining *after* the increment was credited, so
this recovers the true think time). A missing/malformed [%clk] breaks
the delta chain: that move and the player's next move are both skipped
(next move's clock_before is unknown), then the chain recovers — so one
bad annotation costs at most two per-move times.
"""

from __future__ import annotations

import re

import chess
import chess.pgn

# H:MM:SS(.fff)
_CLK_HMS = re.compile(r"\[%clk\s+(\d+):([0-5]?\d):([0-5]?\d(?:\.\d+)?)\s*\]")
# M:SS(.fff) — some fast broadcast PGNs
_CLK_MS = re.compile(r"\[%clk\s+(\d{1,3}):([0-5]?\d(?:\.\d+)?)\s*\]")

# one "base[+increment]" clause, e.g. "5400", "5400+30", "0+2"
_TC_CLAUSE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:\+\s*(\d+(?:\.\d+)?))?\s*$")

def extract_clock_seconds(comment: str | None) -> float | None:
    """Seconds remaining from a [%clk ...] move comment, or None if missing/garbled."""
    if not comment:
        return None
    m = _CLK_HMS.search(comment)
    if m:
        h, mm, ss = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mm * 60 + ss
    m = _CLK_MS.search(comment)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    return None


# A time-control period: (move_limit, base_seconds, increment_seconds).
# move_limit is None for the final ("sudden death") period, which applies for
# the rest of the game; every earlier period has an integer move count after
# which the *next* period's base is added on top of whatever time is left.
Period = tuple["int | None", float, float]

_PERIOD_CLAUSE = re.compile(r"^\s*(?:(\d+)/)?(\d+(?:\.\d+)?)\s*(?:\+\s*(\d+(?:\.\d+)?))?\s*$")


def parse_pgn_time_control_periods(tc: str | None) -> list[Period]:
    """Parse a PGN-standard TimeControl value (spec §9.6.1) into its full ordered list of
    (move_limit, base_seconds, increment_seconds) periods — unlike parse_pgn_time_control,
    keeps every period of a composite control so a caller can tell which period a given
    move falls in. Anything unrecognised returns []."""
    if tc is None:
        return []
    text = str(tc).strip()
    if text in ("", "-", "?"):
        return []
    if text.startswith("*"):  # hourglass — single unlimited period, no increment
        m = _TC_CLAUSE.match(text[1:])
        return [(None, float(m.group(1)), 0.0)] if m else []

    periods: list[Period] = []
    for clause in text.split(":"):
        m = _PERIOD_CLAUSE.match(clause)
        if not m:
            return []  # malformed period anywhere -> give up on the whole value
        move_limit = int(m.group(1)) if m.group(1) is not None else None
        base = float(m.group(2))
        inc = float(m.group(3)) if m.group(3) is not None else 0.0
        periods.append((move_limit, base, inc))
        if move_limit is None:
            break  # an unlimited period ends the sequence; anything after is unreachable
    return periods


def parse_pgn_time_control(tc: str | None) -> tuple[float | None, float | None]:
    """Parse a PGN-standard TimeControl value to (base_seconds, increment_seconds) for its
    first period only — for callers needing a single flat base/increment. For move-by-move
    annotation, prefer parse_pgn_time_control_periods, which keeps every period. Anything
    unrecognised returns (None, None)."""
    periods = parse_pgn_time_control_periods(tc)
    if not periods:
        return None, None
    _move_limit, base, inc = periods[0]
    return base, inc


def _locate_period(periods: list[Period], n: int) -> tuple[int, float | None, float]:
    """Return (period_index, base, increment) for a side's n-th (1-indexed) own move.

    base is None only for period_index==0 with an unknown base — every later period
    always has a concrete base (a fixed bonus the PGN spec grants at that period's start).
    """
    cumulative = 0
    for i, (move_limit, base, inc) in enumerate(periods):
        if move_limit is None:
            return i, base, inc
        cumulative += move_limit
        if n <= cumulative:
            return i, base, inc
    # own move count ran past every declared period (malformed/incomplete TC
    # string) - keep the last period's increment, but no base bonus to add.
    _move_limit, _base, inc = periods[-1]
    return len(periods), None, inc


def _per_side_times_periods(
    game: chess.pgn.Game, periods: list[Period]
) -> dict[chess.Color, dict]:
    """Walk the mainline; return per colour {played, computable, times}.

    times is (own_move_number, seconds) for moves whose time could be computed; a
    missing/garbled/negative reading breaks the chain, dropping that move and the
    next own move. Tracks each side's period so crossing into a new period switches
    increment and adds that period's base-time bonus, rather than understating think
    time by applying only the first period's (base, increment) for the whole game.
    """
    state = {
        c: {"played": 0, "computable": 0, "times": [], "prev_valid": None, "period_idx": -1}
        for c in (chess.WHITE, chess.BLACK)
    }
    own_no = {chess.WHITE: 0, chess.BLACK: 0}

    board = game.board()
    node = game
    while node.variations:
        node = node.variations[0]
        mover = board.turn
        try:
            board.push(node.move)
        except (ValueError, AssertionError):
            break  # corrupt line; stop here

        s = state[mover]
        s["played"] += 1
        own_no[mover] += 1
        n = own_no[mover]

        p_idx, p_base, p_inc = _locate_period(periods, n)
        prev = s["prev_valid"]
        if p_idx != s["period_idx"]:
            if p_idx == 0:
                # game clock starts already carrying its first increment (e.g. "6000+30"
                # reads 100:30 before move 1, not 100:00) - confirmed against real data
                prev = None if p_base is None else p_base + p_inc
            elif prev is not None and p_base is not None:
                # only the game start pre-loads an increment; a later period just adds its bonus
                prev = prev + p_base
            else:
                prev = None  # can't safely reconstruct across an unknown gap
            s["period_idx"] = p_idx

        clk = extract_clock_seconds(node.comment)
        if clk is None:
            s["prev_valid"] = None  # break the chain
            continue

        if prev is None:
            # no valid "before" (move 1 without a known base, or chain just broke)
            s["prev_valid"] = clk
            continue

        t = prev - clk + p_inc
        if t < 0 or t > prev + p_inc + 1e-6:
            # clock noise / corrupt annotation -> treat as missing
            s["prev_valid"] = clk
            continue

        s["times"].append((n, float(t)))
        s["computable"] += 1
        s["prev_valid"] = clk

    return state


def _per_side_times(
    game: chess.pgn.Game, increment: float, base_time: float | None
) -> dict[chess.Color, dict]:
    """Single-period convenience wrapper over _per_side_times_periods."""
    return _per_side_times_periods(game, [(None, base_time, increment)])


