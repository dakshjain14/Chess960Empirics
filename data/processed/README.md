# data/processed/

Pipeline output. Two different kinds of content, with different tracking
status — see the root `README.md`'s "Data included in this repository"
section for the full explanation.

## Tracked (included in this repository)

The final, analysis-ready Parquet files actually consumed by the
hypothesis-testing scripts — roughly 6MB total:

- `per_move_data.parquet`, `game_features.parquet` — H1a/H1b/C2/the
  rating-accuracy-gradient's inputs (`pipeline/analysis/h1_stage1-2`).
- `banded_h1_{corpus}_{format}.parquet` — Stage 3's banded output,
  shared by H1a, H1b, and C2.
- `{corpus}_{format}[_otb]_scalars.parquet` — C3/C4's input
  (`pipeline/features/extract_scalars.py`).

A reviewer needs nothing beyond these files (plus `data/results/`) to
verify this study's results.

## Ignored (excluded from version control, see .gitignore)

Three intermediate PGN-tree stages of the correction/annotation pipeline,
~242MB combined:

- `Updated_Ratings/` — FIDE-rating-corrected PGNs (`pipeline/ingest
  /rating_update.py`, `standard_rating_backfill.py`). Needs FIDE
  rating-list data, not regeneratable from `data/games/` alone.
- `Updated_Time/` — the above plus `[%tspent]` time annotation
  (`pipeline/features/annotate_time_batch.py`). Needs `Updated_Ratings/`
  as input; the annotation step itself needs nothing external.
- `Updated_engine_eval/` — the above plus Stockfish `[%eval]` annotation
  (`pipeline/ingest/engine_annotate_standalone.py`). Needs `Updated_Time/`
  as input and a Stockfish install.

These are excluded because they're large, and each needs more than
`data/games/` alone to regenerate — see root `README.md`'s "External
Dependencies for Full Reproduction" section for what's needed to rebuild
them (FIDE rating-list data, a Stockfish 19 install, ~20 hours of
engine-eval runtime).
