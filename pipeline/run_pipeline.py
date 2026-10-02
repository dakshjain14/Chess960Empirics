"""run_pipeline.py — CLI orchestration for scalar extraction.

Stockfish analysis is NOT run from here — it runs separately via the
self-contained ``pipeline/ingest/engine_annotate_standalone.py`` (see
ENGINE.md), which reads ``Updated_Time/`` and writes ``Updated_engine_eval/``.
H1a/H1b/C2/gradient read ``game_features.parquet`` (fed by that script, not
this file) via ``h1_stage4_hypothesis_tests.py`` — not run from here either.
C3/C4 read ``{corpus}_{format}_scalars.parquet``, written by this file's
``run_extract_scalars()``, via their own scripts
(``c3_close_game_drawrate.py``, ``c5_upset_tests.py``, ``c5_bin_table.py``,
``c4_elo_scale.py``).

Per-(corpus, format[, source_type]) scalar extraction — independent,
parallelisable. Writes ``{slug}_scalars.parquet`` and
``{slug}_scalars_audit_summary.csv``.

    python -m pipeline.run_pipeline --corpus freestyle --format classical --stage extract_scalars
    python -m pipeline.run_pipeline --corpus freestyle --format rapid --stage extract_scalars --source-type otb

``--stage``: ``refresh_corrected_data``, ``extract_scalars``.

Every stage reads games only via ``manifest_loader.load_corpus``, which
reads only from ``data/processed/Updated_Time/`` (FIDE-corrected Elo,
``[%tspent]``-annotated). An event with no corrected copy there is skipped
and logged — no fallback to ``data/games/`` originals.

All outputs go to ``data/processed/`` and ``data/results/`` only.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

from pipeline import config
from pipeline.features import annotate_time_batch, extract_scalars
from pipeline.ingest import audit_log, filters, manifest_loader, rating_update, standard_rating_backfill

logging.getLogger("chess.pgn").setLevel(logging.CRITICAL)  # we capture game.errors ourselves


def _slug(corpus: str, fmt: str, source_type: str | None) -> str:
    """Filename stem for one ``(corpus, format[, source_type])`` stratum, e.g. ``"freestyle_rapid_otb"``."""
    return f"{corpus}_{fmt}" + (f"_{source_type}" if source_type else "")


def _paths(corpus: str, fmt: str, source_type: str | None) -> dict[str, Path]:
    """Every output-file path for one stratum, keyed by artifact name."""
    s = _slug(corpus, fmt, source_type)
    return {
        "exclusions": config.RESULTS_DIR / f"{s}_exclusions.parquet",
        "scalars": config.PROCESSED_DIR / f"{s}_scalars.parquet",
        "audit_summary": config.RESULTS_DIR / f"{s}_scalars_audit_summary.csv",
    }


# per-(corpus, format) stages


def _load_and_filter(corpus: str, fmt: str, source_type: str | None, log_path: Path | None,
                      source: str = "updated_time"):
    """Load both manifests, subset to this stratum, parse its PGNs, and run
    the two universal ingest filters (anomalies -> Elo floor) — every
    hypothesis needs a valid, rated game. Returns (manifest, subset, games).
    ``source`` picks which corrected-data tree to read from (narrowest the
    caller needs — see ``manifest_loader.load_corpus``'s docstring).
    ``log_path`` is deleted first so repeat calls don't double-count, since
    the audit_log writers always append rather than overwrite."""
    if log_path is not None:
        for f in (log_path, audit_log.observations_path_for(log_path)):
            Path(f).unlink(missing_ok=True)
    manifest = manifest_loader.load_manifest(
        config.FREESTYLE_MANIFEST_PATH, config.STANDARD_MANIFEST_PATH, observations_log=log_path
    )
    subset = manifest[(manifest["corpus"] == corpus) & (manifest["format"] == fmt)]
    if source_type is not None:
        subset = subset[subset["source_type"] == source_type]
    games = manifest_loader.load_corpus(manifest, corpus, fmt, source_type=source_type,
                                         log_path=log_path, source=source)
    n_raw = len(games)
    games = filters.filter_broadcast_anomalies(games, log_path)
    games = filters.filter_by_elo(games, config.MIN_ELO, log_path)
    print(f"[run_pipeline] {_slug(corpus, fmt, source_type)}: raw {n_raw} -> filtered {len(games)}")
    return manifest, subset, games


def run_refresh_corrected_data() -> None:
    """Regenerate the correction chain: data/games/ -> Updated_Ratings/ (FIDE
    rating correction) -> Updated_Time/ ([%tspent] annotation). Run whenever
    data/games/ or data/Rating_lists/ change — cheap, no engine calls."""
    print("[run_pipeline] refresh_corrected_data: rating_update (Freestyle)...")
    rating_update.main()
    print("[run_pipeline] refresh_corrected_data: standard_rating_backfill (Standard)...")
    standard_rating_backfill.main()
    print("[run_pipeline] refresh_corrected_data: annotate_time_batch (time annotation stage, both corpora)...")
    annotate_time_batch.main()
    print("[run_pipeline] refresh_corrected_data: done")


def run_extract_scalars(corpus: str, fmt: str, source_type: str | None = None) -> pd.DataFrame:
    """Per-game scalar extraction (Elo, result, provenance) — doesn't need
    engine eval to have run. Covers what C4 needs, and what C3's own script
    reads via the scalars parquet this writes. ``source_type="otb"`` excludes
    playin_online, writing to the _otb-suffixed path. Reads a single
    ``source="updated_time"`` tree deliberately, since game_id is assigned
    positionally and only aligns across two independently-regenerated trees
    if kept in lock-step (see extract_scalars.py's docstring) — run
    --stage refresh_corrected_data first so Updated_Time is current."""
    slug = _slug(corpus, fmt, source_type)
    log_path = config.RESULTS_DIR / f"{slug}_exclusions.parquet"
    out_path = config.PROCESSED_DIR / f"{slug}_scalars.parquet"
    Path(out_path).unlink(missing_ok=True)

    manifest, subset, games = _load_and_filter(corpus, fmt, source_type, log_path)
    df = extract_scalars.extract_scalars(games, output_path=out_path)

    audit_summary = audit_log.build_event_summary(log_path, subset, out_path)
    audit_path = _paths(corpus, fmt, source_type)["audit_summary"]
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    audit_summary.to_csv(audit_path, index=False)
    print(f"[run_pipeline] wrote audit summary -> {audit_path}")
    return df


# CLI


def _build_parser() -> argparse.ArgumentParser:
    """Define the CLI: which corpus/format/source-type/stage to run."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--corpus", choices=config.CORPORA)
    p.add_argument("--format", choices=config.FORMATS)
    p.add_argument("--source-type", choices=config.SOURCE_TYPES, default=None)
    p.add_argument("--stage", default="extract_scalars",
                   choices=("refresh_corrected_data", "extract_scalars"))
    return p


def main(argv: list[str] | None = None) -> int:
    """Parse args and dispatch to the right stage. refresh_corrected_data
    runs across all strata (no --corpus/--format needed); extract_scalars
    requires both."""
    args = _build_parser().parse_args(argv)
    t0 = time.time()

    if args.stage == "refresh_corrected_data":
        run_refresh_corrected_data()
        print(f"[run_pipeline] refresh_corrected_data done in {time.time() - t0:.0f}s")
        return 0

    if not args.corpus or not args.format:
        print("error: --corpus and --format are required for this stage", file=sys.stderr)
        return 2

    run_extract_scalars(args.corpus, args.format, args.source_type)

    print(f"[run_pipeline] {args.stage} done in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
