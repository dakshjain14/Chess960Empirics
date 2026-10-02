"""manifest_loader.py — reads both corpus manifests, resolves PGN paths, and
parses matching PGNs into tagged game lists.

Normalizes corpus/format/source_type vocab (lowercases and maps to the
canonical `otb`/`playin_online` values); resolves each manifest
Filepath by literal path, then unique-basename search under the
corpus tree; assigns game_id as
f"{event_slug}_{index:05d}" (event slugs are unique across both corpora, so
ids are globally unique). Every normalization/resolution decision is logged
via audit_log.log_data_observation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import chess.pgn
import pandas as pd

from pipeline.config import (
    DATA_GAMES_DIR,
    REPO_ROOT,
    UPDATED_ENGINE_EVAL_DIR,
    UPDATED_RATINGS_DIR,
    UPDATED_TIME_DIR,
)
from pipeline.ingest import audit_log

# Corrected-data trees load_corpus's `source` picks between — never
# data/games/ directly, which is read-only raw input. Narrowest to widest:
# updated_ratings (Elo/result only; C3, C4), updated_time (+ per-move
# [%tspent], subset coverage; H1b), updated_engine_eval (+ Stockfish
# [%eval] on the opening window; H1a, C2).
CORRECTED_DATA_ROOTS: dict[str, Path] = {
    "updated_ratings": UPDATED_RATINGS_DIR,
    "updated_time": UPDATED_TIME_DIR,
    "updated_engine_eval": UPDATED_ENGINE_EVAL_DIR,
}

# Required columns.
REQUIRED_COLUMNS: tuple[str, ...] = ("event", "filepath", "corpus", "format", "source_type")

_CORPUS_MAP = {"freestyle": "freestyle", "standard": "standard"}
_FORMAT_MAP = {"classical": "classical", "rapid": "rapid"}
_SOURCE_TYPE_MAP = {
    "otb": "otb",
    "playin_online": "playin_online",
}


def _slugify(value: str) -> str:
    """Lowercase, strip trailing .pgn, collapse non-alphanumerics to _."""
    text = re.sub(r"\.pgn$", "", str(value).strip(), flags=re.IGNORECASE)
    text = re.sub(r"[^a-z0-9]+", "_", text.lower())
    return text.strip("_")


def _norm(value: object, mapping: dict[str, str], field: str) -> str:
    """Map raw manifest cell to canonical vocab; empty string if unmappable."""
    key = str(value).strip().lower()
    if key in mapping:
        return mapping[key]
    return key  # keep raw (lowercased); caller decides whether to flag


def _resolve_pgn_path(
    raw_filepath: str,
    corpus_dir_name: str,
    observations_log: str | Path | None,
    event: str,
) -> Path:
    """Resolve manifest Filepath to a real file: literal path, then
    unique-basename search; raises if unresolved or ambiguous."""
    raw = str(raw_filepath).strip().replace("\\", "/")
    basename = Path(raw).name

    # (1) literal, relative to repo root
    literal = (REPO_ROOT / raw).resolve()
    if literal.is_file():
        return literal

    # (2) unique basename search under the corpus subtree
    search_root = DATA_GAMES_DIR / corpus_dir_name
    matches = sorted(search_root.rglob(basename))
    matches = [m for m in matches if m.is_file()]
    if len(matches) == 1:
        if observations_log is not None:
            audit_log.log_data_observation(
                observations_log, "manifest_row", event,
                "PGN path resolved via unique-basename fallback search",
                details={"manifest_filepath": raw, "resolved": str(matches[0])},
            )
        return matches[0].resolve()
    if len(matches) > 1:
        if observations_log is not None:
            audit_log.log_data_observation(
                observations_log, "manifest_row", event,
                "PGN basename is AMBIGUOUS on disk — cannot resolve",
                details={"manifest_filepath": raw, "candidates": [str(m) for m in matches]},
            )
        raise RuntimeError(f"ambiguous PGN basename {basename!r}: {matches}")

    if observations_log is not None:
        audit_log.log_data_observation(
            observations_log, "manifest_row", event,
            "PGN path could NOT be resolved on disk",
            details={"manifest_filepath": raw, "search_root": str(search_root)},
        )
    raise FileNotFoundError(f"cannot resolve manifest Filepath {raw!r} for event {event!r}")


def _load_one_manifest(path: str | Path, sheet: str | int | None = None) -> pd.DataFrame:
    """Read one manifest xlsx; return with lowercased-key column index."""
    path = Path(path)
    if sheet is None:
        xl = pd.ExcelFile(path)
        sheet = xl.sheet_names[0]
    df = pd.read_excel(path, sheet_name=sheet)
    df = df.rename(columns={c: c for c in df.columns})
    df.attrs["source_path"] = str(path)
    return df


def _column(df: pd.DataFrame, *candidates: str) -> str:
    """Return first column in df matching any candidate, case-insensitively."""
    lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    raise KeyError(f"none of {candidates} present in manifest columns {list(df.columns)}")


def load_manifest(
    freestyle_manifest_path: str | Path,
    standard_manifest_path: str | Path,
    observations_log: str | Path | None = None,
) -> pd.DataFrame:
    """Load both manifests, normalize corpus/format/source_type/event_slug,
    resolve PGN filepaths, and concatenate into one dataframe. Columns
    unique to one manifest are NaN-filled on the other's rows."""
    frames: list[pd.DataFrame] = []
    for raw_path, default_corpus, corpus_dir in (
        (freestyle_manifest_path, "freestyle", "Freestyle"),
        (standard_manifest_path, "standard", "Standard"),
    ):
        df = _load_one_manifest(raw_path)
        df = df.copy()

        corpus_col = _column(df, "corpus")
        format_col = _column(df, "format")
        event_col = _column(df, "event")
        filepath_col = _column(df, "filepath", "Filepath")
        source_type_col = _column(df, "source_type", "sourcetype", "source type")

        df["corpus"] = df[corpus_col].map(lambda v: _norm(v, _CORPUS_MAP, "corpus")).replace(
            "", default_corpus
        )
        df["format"] = df[format_col].map(lambda v: _norm(v, _FORMAT_MAP, "format"))
        raw_source_types = df[source_type_col].astype(str)
        df["source_type"] = raw_source_types.map(lambda v: _norm(v, _SOURCE_TYPE_MAP, "source_type"))

        # flag any source_type value we had to remap or couldn't map
        for idx, (raw_st, norm_st) in enumerate(zip(raw_source_types, df["source_type"])):
            raw_key = raw_st.strip().lower()
            if raw_key not in ("otb", "playin_online") and observations_log is not None:
                if raw_key in _SOURCE_TYPE_MAP:
                    audit_log.log_data_observation(
                        observations_log, "manifest_row", str(df.iloc[idx][event_col]),
                        f"source_type {raw_st!r} normalised to {norm_st!r}",
                        corpus=default_corpus,
                        details={"raw": raw_st, "normalised": norm_st},
                    )
                else:
                    audit_log.log_data_observation(
                        observations_log, "manifest_row", str(df.iloc[idx][event_col]),
                        f"UNRECOGNISED source_type {raw_st!r} kept as-is (lowercased)",
                        corpus=default_corpus,
                        details={"raw": raw_st},
                    )

        df["event"] = df[event_col].astype(str)
        df["event_slug"] = df["event"].map(_slugify)
        df["source_manifest"] = Path(raw_path).name

        # resolve paths
        resolved: list[str] = []
        for _, row in df.iterrows():
            p = _resolve_pgn_path(
                row[filepath_col], corpus_dir, observations_log, str(row["event"])
            )
            resolved.append(str(p))
        df["filepath"] = resolved

        frames.append(df)

    combined = pd.concat(frames, ignore_index=True)

    # global game_id-prefix uniqueness check
    dup_slugs = combined["event_slug"][combined["event_slug"].duplicated(keep=False)]
    if len(dup_slugs) and observations_log is not None:
        audit_log.log_data_observation(
            observations_log, "manifest", "event_slug",
            "duplicate event_slug across manifest rows — game_ids may collide",
            details={"slugs": sorted(dup_slugs.unique().tolist())},
        )

    # concise summary in place of one print per resolved row
    if observations_log is not None:
        obs = audit_log.read_observations(observations_log)
        notes = obs["note"].value_counts().to_dict() if not obs.empty else {}
        fallback = notes.get("PGN path resolved via unique-basename fallback search", 0)
        print(
            f"[manifest_loader] {len(combined)} rows loaded "
            f"({(combined['filepath'].map(lambda p: Path(p).is_file())).sum()} PGNs resolved on disk; "
            f"{fallback} via basename fallback). "
            f"Full detail in {audit_log.observations_path_for(observations_log).name}"
        )

    return combined


def manifest_time_controls(manifest_df: pd.DataFrame) -> tuple[dict[str, float], dict[str, float]]:
    """Per-event (increment, base) seconds from the manifest's
    time_control_pgn column only — no fallback to Freestyle's
    timecontrol/base_minutes shorthand; unparseable events are absent."""
    from pipeline.features.clock_parser import parse_pgn_time_control

    inc_by_event: dict[str, float] = {}
    base_by_event: dict[str, float] = {}
    cols = {c.lower().replace(" ", "_"): c for c in manifest_df.columns}
    pgn_col = cols.get("time_control_pgn") or cols.get("timecontrol_pgn")

    for _, row in manifest_df.iterrows():
        event = str(row["event"])

        if pgn_col is None or pd.isna(row[pgn_col]):
            continue
        base, inc = parse_pgn_time_control(row[pgn_col])

        if inc is not None:
            inc_by_event[event] = inc
        if base is not None:
            base_by_event[event] = base
    return inc_by_event, base_by_event


def manifest_time_control_periods(manifest_df: pd.DataFrame) -> dict[str, list]:
    """Per-event full multi-period time control (same no-fallback rule as
    manifest_time_controls, but keeps every period). Prefer this for
    move-by-move annotation — using only the first period silently drops
    later periods' bonus time/increment for moves-per-period controls,
    understating think time and producing impossible negative deltas."""
    from pipeline.features.clock_parser import parse_pgn_time_control_periods

    periods_by_event: dict[str, list] = {}
    cols = {c.lower().replace(" ", "_"): c for c in manifest_df.columns}
    pgn_col = cols.get("time_control_pgn") or cols.get("timecontrol_pgn")

    for _, row in manifest_df.iterrows():
        event = str(row["event"])
        if pgn_col is None or pd.isna(row[pgn_col]):
            continue
        periods = parse_pgn_time_control_periods(row[pgn_col])
        if periods:
            periods_by_event[event] = periods
    return periods_by_event


def _count_games_in_file(path: str | Path) -> int:
    """Headers-only count of games in a PGN file."""
    n = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        while chess.pgn.read_headers(fh) is not None:
            n += 1
    return n


def _iter_file_games(path: str | Path) -> Iterable[chess.pgn.Game]:
    """Yield games one at a time without loading the whole file into memory."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        while True:
            game = chess.pgn.read_game(fh)
            if game is None:
                return
            yield game


def _corrected_path(original_path: str | Path, corpus_dir: str, source: str) -> Path | None:
    """Map a resolved data/games/<corpus_dir>/... path to its corrected-tree
    equivalent (trees mirror the same relative layout); None if no
    corrected copy exists yet."""
    root = CORRECTED_DATA_ROOTS[source]
    games_root = (DATA_GAMES_DIR / corpus_dir).resolve()
    try:
        rel = Path(original_path).resolve().relative_to(games_root)
    except ValueError:
        return None
    candidate = root / f"{corpus_dir}_rating_updated" / rel
    return candidate if candidate.is_file() else None


def load_corpus(
    manifest_df: pd.DataFrame,
    corpus: str,
    format: str,  # noqa: A002 - shadows builtin
    source_type: str | None = None,
    log_path: str | Path | None = None,
    source: str = "updated_time",
) -> list[chess.pgn.Game]:
    """Parse every manifest-matching event's PGN into one tagged game list
    (SourceEvent/SourceType/GameId/Corpus/StratumFormat headers), reading
    exclusively from CORRECTED_DATA_ROOTS[source] — never raw data/games/.
    An event with no corrected copy, or a PGN that won't open, is skipped
    and logged rather than silently dropped."""
    if source not in CORRECTED_DATA_ROOTS:
        raise ValueError(f"source must be one of {list(CORRECTED_DATA_ROOTS)}, got {source!r}")
    mask = (manifest_df["corpus"] == corpus) & (manifest_df["format"] == format)
    if source_type is not None:
        mask &= manifest_df["source_type"] == source_type
    subset = manifest_df.loc[mask]
    corpus_dir = corpus.capitalize()

    games: list[chess.pgn.Game] = []
    for _, row in subset.iterrows():
        event = str(row["event"])
        slug = str(row["event_slug"])
        path = _corrected_path(row["filepath"], corpus_dir, source)
        if path is None:
            if log_path is not None:
                audit_log.log_data_observation(
                    log_path, "pgn_file", event,
                    f"no corrected copy under {CORRECTED_DATA_ROOTS[source]}/ — "
                    "event skipped entirely (run the correction scripts for it first)",
                    corpus=corpus, format=format,
                    details={"original_path": str(row["filepath"]), "source": source},
                )
            continue
        try:
            raw_count = _count_games_in_file(path)
        except OSError as exc:
            if log_path is not None:
                audit_log.log_data_observation(
                    log_path, "pgn_file", event,
                    "PGN file could not be opened — event skipped entirely",
                    corpus=corpus, format=format,
                    details={"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
                )
            continue

        if log_path is not None:
            audit_log.log_raw_game_count(log_path, event, corpus, format, raw_count)

        parsed = 0
        parse_error_ids: list[str] = []
        for idx, game in enumerate(_iter_file_games(path)):
            game_id = f"{slug}_{idx:05d}"
            game.headers["SourceEvent"] = event
            game.headers["SourceType"] = str(row["source_type"])
            game.headers["GameId"] = game_id
            game.headers["Corpus"] = corpus
            game.headers["StratumFormat"] = format

            # python-chess truncates the mainline at the first movetext error;
            # log it and keep the game (engine-eval logs its own error if
            # the truncation also breaks analysis).
            if game.errors and log_path is not None:
                parse_error_ids.append(game_id)
                audit_log.log_data_observation(
                    log_path, "game", game_id,
                    "python-chess reported movetext parse error(s); mainline truncated at first",
                    corpus=corpus, format=format,
                    details={
                        "event": event,
                        "white": game.headers.get("White"),
                        "black": game.headers.get("Black"),
                        "errors": [f"{type(e).__name__}: {e}" for e in game.errors][:5],
                        "plies_kept": sum(1 for _ in game.mainline_moves()),
                    },
                )

            games.append(game)
            parsed += 1

        if parsed != raw_count and log_path is not None:
            audit_log.log_data_observation(
                log_path, "pgn_file", event,
                "parsed game count differs from headers-only count",
                corpus=corpus, format=format,
                details={"headers_count": raw_count, "parsed_count": parsed, "path": str(path)},
            )
        if parse_error_ids:
            print(
                f"[manifest_loader] {event}: {len(parse_error_ids)} game(s) had movetext "
                f"parse errors (logged as observations, kept for downstream stages)"
            )

    return games


if __name__ == "__main__":  # pragma: no cover - self-check on the real manifests
    import tempfile

    from pipeline.config import FREESTYLE_MANIFEST_PATH, STANDARD_MANIFEST_PATH

    with tempfile.TemporaryDirectory() as td:
        obs_log = Path(td) / "selfcheck_exclusions.parquet"
        man = load_manifest(FREESTYLE_MANIFEST_PATH, STANDARD_MANIFEST_PATH, observations_log=obs_log)
        print(f"combined manifest: {man.shape[0]} rows, {man.shape[1]} cols")
        print("corpus x format x source_type counts:")
        print(man.groupby(["corpus", "format", "source_type"]).size().to_string())
        print()
        all_resolve = man["filepath"].map(lambda p: Path(p).is_file()).all()
        slugs_unique = man["event_slug"].is_unique
        print("all filepaths resolve on disk:", all_resolve)
        print("event_slugs globally unique:", slugs_unique)

        # tiny end-to-end: load the smallest freestyle rapid event
        fr = man[(man["corpus"] == "freestyle") & (man["format"] == "rapid")]
        smallest_event = fr.loc[fr["games"].idxmin(), "event"]
        one = man[man["event"] == smallest_event]
        gs = load_corpus(one, "freestyle", "rapid", log_path=obs_log)
        tagged_ok = all(
            g.headers.get("SourceEvent") and g.headers.get("GameId") and g.headers.get("SourceType")
            for g in gs
        )
        ids_unique = len({g.headers["GameId"] for g in gs}) == len(gs)
        print(f"\nloaded event {smallest_event!r}: {len(gs)} games, tagged_ok={tagged_ok}, ids_unique={ids_unique}")
        obs = audit_log.read_observations(obs_log)
        print(f"observations logged: {len(obs)}")

        ok = all_resolve and slugs_unique and tagged_ok and ids_unique and len(gs) > 0
        print("\nmanifest_loader self-check:", "PASS" if ok else "FAIL")
