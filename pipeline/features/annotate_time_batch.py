"""Run time annotation (annotate_time.py) per input PGN file, mirroring
Updated_Ratings/ into Updated_Time/ with one output file per input file.

Per-event time control comes from the manifest's time_control_pgn column, matched to
each PGN file via its basename. Uses the full multi-period time control, so a
moves-per-period value like "40/6000:3000+30" correctly switches periods past move 40.
Only appends [%tspent] to existing [%clk] data - ratings/headers are untouched.
"""
import glob
import os

import chess.pgn
import pandas as pd

from pipeline.config import FREESTYLE_MANIFEST_PATH, STANDARD_MANIFEST_PATH, UPDATED_RATINGS_DIR, UPDATED_TIME_DIR
from pipeline.features.annotate_time import annotate_time_games
from pipeline.ingest.manifest_loader import load_manifest, manifest_time_control_periods

FREESTYLE_MANIFEST = str(FREESTYLE_MANIFEST_PATH)
STANDARD_MANIFEST = str(STANDARD_MANIFEST_PATH)

INPUT_ROOTS = {
    'Freestyle_rating_updated': str(UPDATED_RATINGS_DIR / 'Freestyle_rating_updated'),
    'Standard_rating_updated': str(UPDATED_RATINGS_DIR / 'Standard_rating_updated'),
}
OUTPUT_ROOT = str(UPDATED_TIME_DIR)


def build_event_maps():
    manifest_df = load_manifest(FREESTYLE_MANIFEST, STANDARD_MANIFEST)
    periods_by_event = manifest_time_control_periods(manifest_df)
    basename_to_event = {}
    for _, row in manifest_df.iterrows():
        fp = row['filepath']
        if pd.isna(fp):
            continue
        basename_to_event[os.path.basename(str(fp))] = str(row['event'])
    return periods_by_event, basename_to_event


def load_games(path, source_event):
    """Parse every game in path, stamping SourceEvent on each - annotate_time_games needs
    it for the per-event lookup, and we bypass load_corpus (which normally stamps it) by
    reading files directly, so we must stamp it ourselves."""
    games = []
    with open(path, encoding='utf-8-sig') as fh:
        while True:
            game = chess.pgn.read_game(fh)
            if game is None:
                break
            game.headers['SourceEvent'] = source_event
            games.append(game)
    return games


def main():
    periods_by_event, basename_to_event = build_event_maps()

    grand_total_games = 0
    grand_total_plies = 0
    grand_tagged_plies = 0

    for label, input_root in INPUT_ROOTS.items():
        pgn_files = sorted(glob.glob(os.path.join(input_root, '**', '*.pgn'), recursive=True))
        print(f"=== {label}: {len(pgn_files)} input files ===")
        for src_path in pgn_files:
            basename = os.path.basename(src_path)
            event = basename_to_event.get(basename)
            if event is None:
                print(f"ALERT: '{basename}' not found in manifest - skipping, no output written")
                continue

            games = load_games(src_path, event)
            rel = os.path.relpath(src_path, input_root)
            dst_path = os.path.join(OUTPUT_ROOT, label, rel)

            summary = annotate_time_games(
                games, dst_path,
                periods_by_event=periods_by_event,
                header_fallback=False,
            )
            grand_total_games += summary['n_games']
            grand_total_plies += summary['total_plies']
            grand_tagged_plies += summary['tagged_plies']

    coverage = (grand_tagged_plies / grand_total_plies * 100.0) if grand_total_plies else float('nan')
    print(f"\ndone: {grand_total_games} games, {grand_tagged_plies}/{grand_total_plies} "
          f"plies tagged ({coverage:.1f}% coverage)")


if __name__ == '__main__':
    main()
