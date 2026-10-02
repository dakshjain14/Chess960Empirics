"""audit_log.py — structured, event-level audit trail.

Every stage that drops, excludes, or degrades (nulls a value for) a game must
record it here — not just print a summary. The exclusion log and the per-event
summary it feeds are **first-class pipeline outputs**, on the same footing as
the Parquet feature files.

Two write surfaces:

* :func:`log_exclusion` — one row per game that a filter/parser drops or
  degrades. Fixed schema, enumerated ``stage`` / ``reason`` vocab.
* :func:`log_data_observation` — one row per *non-game-level* data oddity that
  is not an exclusion (a manifest row with an unrecognised ``source_type``, a
  PGN file on disk that isn't in the manifest, a game whose movetext python-
  chess could not fully parse, …). ``log_exclusion``'s schema has no room for
  a file-level note, so this companion function exists for that. It writes to
  a sibling ``*_observations.parquet`` file and does not print — callers
  print their own concise summaries.

Read surface:

* :func:`build_event_summary` — the per-event funnel table, written to
  ``data/results/{corpus}_{format}_scalars_audit_summary.csv``.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

# --------------------------------------------------------------------------- #
# Vocabulary — extend this set as new signatures are discovered               #
# --------------------------------------------------------------------------- #

STAGES: tuple[str, ...] = (
    "manifest_load",  # used only by log_data_observation
    "anomaly_filter",
    "elo_filter",
)

REASONS: tuple[str, ...] = (
    "zero_ply",
    "missing_fen",
    "duplicate_game_id",
    "elo_unparseable",
    "elo_below_floor",
    "unplayed_forfeit",  # fewer than 2 real plies, regardless of Termination
                         # label (catches any forfeit/no-show, not just
                         # games literally labeled "Unplayed") — see
                         # filters._check_single_ply_forfeit
)

EXCLUSION_COLUMNS: tuple[str, ...] = (
    "event",
    "game_id",
    "corpus",
    "format",
    "stage",
    "reason",
    "details",
    "timestamp",
)

OBSERVATION_COLUMNS: tuple[str, ...] = (
    "scope",  # e.g. "manifest_row", "pgn_file", "corpus"
    "identifier",  # event name / file path / etc.
    "corpus",
    "format",
    "stage",
    "note",
    "details",
    "timestamp",
)

# A process-local lock so concurrent appends from a multiprocessing driver that
# funnels results back through the parent don't interleave a partial row. (The
# engine driver collects worker results in the parent and logs there, so this
# is belt-and-braces, not the primary safety mechanism.)
_LOCK = threading.Lock()


def _now_iso() -> str:
    """Current UTC timestamp as an ISO-8601 string, for the log rows' ``timestamp`` column."""
    return datetime.now(timezone.utc).isoformat()


def _details_to_str(details: dict[str, Any] | None) -> str:
    """JSON-encode the free-form details dict for stable Parquet storage.

    Stored as a string (not a struct) so heterogeneous keys across reasons
    never fight over a column type.
    """
    if not details:
        return ""
    try:
        return json.dumps(details, default=str, sort_keys=True)
    except (TypeError, ValueError):
        return str(details)


def _append_rows(log_path: str | Path, rows: list[dict], columns: Iterable[str]) -> None:
    """Append ``rows`` to the Parquet log at ``log_path``.

    Parquet has no native append, so we read-existing + concat + rewrite
    atomically (temp file + ``os.replace``) — a long-running pipeline never
    loses the log on a crash, since the previous file stays intact until the
    replace. Log volume is small (one row per excluded game), so the
    rewrite cost is negligible.
    """
    if not rows:
        return
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame(rows, columns=list(columns))
    with _LOCK:
        if log_path.exists():
            existing = pd.read_parquet(log_path)
            combined = pd.concat([existing, new], ignore_index=True)
        else:
            combined = new
        tmp = log_path.with_suffix(log_path.suffix + ".tmp")
        combined.to_parquet(tmp, engine="pyarrow", index=False)
        tmp.replace(log_path)


def log_exclusion(
    log_path: str | Path,
    event: str,
    game_id: str,
    corpus: str,
    format: str,  # noqa: A002 - shadows builtin
    stage: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Append one exclusion/degradation row to the running log at log_path
    (e.g. data/results/freestyle_classical_exclusions.parquet). stage/reason
    should be from STAGES/REASONS but the vocab is extensible — an unknown
    value is stored as-is with a printed warning, never raises."""
    if stage not in STAGES:
        print(f"[audit_log] note: unrecognised stage {stage!r} (stored anyway)")
    if reason not in REASONS:
        print(f"[audit_log] note: unrecognised reason {reason!r} (stored anyway)")
    row = {
        "event": event,
        "game_id": game_id,
        "corpus": corpus,
        "format": format,
        "stage": stage,
        "reason": reason,
        "details": _details_to_str(details),
        "timestamp": _now_iso(),
    }
    _append_rows(log_path, [row], EXCLUSION_COLUMNS)


def log_data_observation(
    log_path: str | Path,
    scope: str,
    identifier: str,
    note: str,
    corpus: str = "",
    format: str = "",  # noqa: A002 - parallel to log_exclusion
    stage: str = "manifest_load",
    details: dict[str, Any] | None = None,
) -> None:
    """Append one non-exclusion data observation (see module docstring).

    Written to a sibling file: ``<log_path stem>_observations.parquet``. Kept
    separate from the exclusion log so the exclusion log's schema stays fixed
    while nothing questionable in the data goes unrecorded.
    """
    log_path = Path(log_path)
    obs_path = log_path.with_name(log_path.stem + "_observations.parquet")
    row = {
        "scope": scope,
        "identifier": identifier,
        "corpus": corpus,
        "format": format,
        "stage": stage,
        "note": note,
        "details": _details_to_str(details),
        "timestamp": _now_iso(),
    }
    _append_rows(obs_path, [row], OBSERVATION_COLUMNS)


def read_exclusions(log_path: str | Path) -> pd.DataFrame:
    """Load an exclusion log (empty typed frame if it does not exist)."""
    log_path = Path(log_path)
    if log_path.exists():
        return pd.read_parquet(log_path)
    return pd.DataFrame({c: pd.Series(dtype="object") for c in EXCLUSION_COLUMNS})


def observations_path_for(log_path: str | Path) -> Path:
    """The sibling observations file for a given exclusion log path."""
    log_path = Path(log_path)
    return log_path.with_name(log_path.stem + "_observations.parquet")


def read_observations(log_path: str | Path) -> pd.DataFrame:
    """Load the observations log sibling of ``log_path`` (empty typed frame if absent)."""
    obs_path = observations_path_for(log_path)
    if obs_path.exists():
        return pd.read_parquet(obs_path)
    return pd.DataFrame({c: pd.Series(dtype="object") for c in OBSERVATION_COLUMNS})


def log_raw_game_count(
    log_path: str | Path,
    event: str,
    corpus: str,
    format: str,  # noqa: A002
    count: int,
) -> None:
    """Record an event's pre-filter game count.

    Stored in the observations log with ``note="raw_game_count"`` so
    :func:`build_event_summary` can read it back as ``total_games_in_file``.
    """
    log_data_observation(
        log_path,
        scope="pgn_file",
        identifier=event,
        note="raw_game_count",
        corpus=corpus,
        format=format,
        stage="manifest_load",
        details={"total_games_in_file": int(count)},
    )


def _count_reason(excl: pd.DataFrame, event: str, reason: str) -> int:
    """Count exclusion rows for one ``(event, reason)`` pair.

    Logic: a simple boolean-mask-and-sum over the exclusion log; 0 for an
    empty log rather than raising on missing columns.
    """
    if excl.empty:
        return 0
    return int(((excl["event"] == event) & (excl["reason"] == reason)).sum())


def build_event_summary(
    exclusion_log_path: str | Path,
    manifest_df: pd.DataFrame,
    processed_features_path: str | Path,
) -> pd.DataFrame:
    """Per-event funnel table: raw game count, one column per exclusion reason,
    and final_games_analyzed (rows in the merged feature Parquet, 0 if it doesn't
    exist yet), plus a rolled-up total row per (corpus, format)."""
    excl = read_exclusions(exclusion_log_path)
    obs = read_observations(exclusion_log_path)

    # Pre-filter raw counts logged by manifest_loader.load_corpus.
    raw_counts: dict[str, int] = {}
    if not obs.empty and "note" in obs.columns:
        for _, o in obs[obs["note"] == "raw_game_count"].iterrows():
            try:
                raw_counts[o["identifier"]] = int(json.loads(o["details"])["total_games_in_file"])
            except (KeyError, ValueError, TypeError):
                continue

    features_path = Path(processed_features_path)
    if features_path.exists():
        feats = pd.read_parquet(features_path, columns=None)
        final_by_event = feats.groupby("source_event").size() if "source_event" in feats else pd.Series(dtype=int)
    else:
        final_by_event = pd.Series(dtype=int)

    rows: list[dict] = []
    for _, m in manifest_df.iterrows():
        event = m["event"]
        # Prefer the raw count logged at ingest; fall back to the manifest's
        # own declared `games` count if the pipeline hasn't ingested yet.
        raw = raw_counts.get(event)
        if raw is None:
            raw = m.get("games")
        rows.append(
            {
                "event": event,
                "corpus": m.get("corpus", ""),
                "format": m.get("format", ""),
                "source_type": m.get("source_type", ""),
                "total_games_in_file": int(raw) if pd.notna(raw) else pd.NA,
                "excluded_zero_ply": _count_reason(excl, event, "zero_ply"),
                "excluded_unplayed_forfeit": _count_reason(excl, event, "unplayed_forfeit"),
                "excluded_missing_fen": _count_reason(excl, event, "missing_fen"),
                "excluded_duplicate_game_id": _count_reason(excl, event, "duplicate_game_id"),
                "excluded_elo_unparseable": _count_reason(excl, event, "elo_unparseable"),
                "excluded_elo_below_floor": _count_reason(excl, event, "elo_below_floor"),
                "final_games_analyzed": int(final_by_event.get(event, 0)),
            }
        )

    summary = pd.DataFrame(rows)

    # Rolled-up totals per (corpus, format).
    if not summary.empty:
        num_cols = [
            "total_games_in_file",
            "excluded_zero_ply",
            "excluded_unplayed_forfeit",
            "excluded_missing_fen",
            "excluded_duplicate_game_id",
            "excluded_elo_unparseable",
            "excluded_elo_below_floor",
            "final_games_analyzed",
        ]
        totals = []
        for (corpus, fmt), grp in summary.groupby(["corpus", "format"], dropna=False):
            trow = {c: grp[c].sum(min_count=1) for c in num_cols}
            trow.update(
                {
                    "event": f"__TOTAL__ {corpus}/{fmt}",
                    "corpus": corpus,
                    "format": fmt,
                    "source_type": "",
                }
            )
            totals.append(trow)
        summary = pd.concat([summary, pd.DataFrame(totals)], ignore_index=True)

    return summary
