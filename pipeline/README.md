# Analysis pipeline

Code that turns the selected PGN corpora (`data/games/`, see `data/games/Data_Selection.md`) into analysis datasets, test results and figures for the claims in `METHODOLOGY.md`.

The pipeline makes no data-selection decisions. `data/games/` is read-only; outputs go to `data/processed/` and `data/results/`. Exclusions are logged per game with `audit_log.log_exclusion()`, and non-exclusion data issues (unresolvable paths, unparseable movetext, missing time controls) with `log_data_observation()`.

## Setup

```bash
python3.12 -m venv .venv-pipeline
.venv-pipeline/bin/pip install -r pipeline/requirements.txt
.venv-pipeline/bin/python -m pytest pipeline/tests -q      # test suite
```

The engine step also needs Stockfish 19 (`apt-get install stockfish`, `brew install stockfish`, or set `STOCKFISH_PATH`). See `ENGINE.md`.

## Data flow

```
data/games/                     raw PGNs + manifests (read-only)
  └─ ratings      → data/processed/Updated_Ratings/     standard_rating_backfill.py, rating_update.py
  └─ clock times  → data/processed/Updated_Time/        annotate_time_batch.py ([%tspent] from [%clk])
  └─ engine       → data/processed/Updated_engine_eval/ engine_annotate_standalone.py (run separately; see ENGINE.md)
       └─ analysis-ready Parquet → data/processed/      h1_stage1–3, extract_scalars
            └─ results, figures  → data/results/
```

Input layout:

```
data/games/Freestyle/{Classical_OTB, Rapid_OTB, Rapid_online_playin}/*.pgn   + freestyle_manifest.xlsx
data/games/Standard/{Classical_OTB, Rapid_OTB}/*.pgn                        + Standard_Manifest.xlsx
```

Both manifests are loaded and combined at startup (`manifest_loader.load_manifest`).

## Running

**Full rebuild from raw PGNs** (only if you don't have `Updated_engine_eval/`, which is not in the public repository; needs FIDE rating lists and Stockfish):

1. `python -m pipeline.run_pipeline --stage refresh_corrected_data`: `data/games/` → `Updated_Ratings/` → `Updated_Time/`.
2. `engine_annotate_standalone.py`: `Updated_Time/` → `Updated_engine_eval/` (about 20 hours on 8 cores).
3. `./run_all.sh`.

**Everything, from `Updated_engine_eval/`:** `./run_all.sh`. It defines and runs every step in order and stops at the first failure; its comments say what each step produces and which steps need files not in the repository.


**Adding or replacing one PGN.** Each stage re-derives only missing or stale files, so this is fast:

1. Add the PGN under `data/games/` and update its manifest row (`Filepath`; also `games`, `total_players`, `Games_2100_2399` and `Comment` if they change, computed from the PGN).
2. Ratings: `standard_rating_backfill.py` (Standard) or `rating_update.py` (Freestyle). Files missing from the manifest are skipped with an `ALERT`.
3. Times: `annotate_time_batch.py`.
4. Engine: `engine_annotate_standalone.py --input-root data/processed/Updated_Time --output-root data/processed/Updated_engine_eval`. It reruns only files whose output game count doesn't match the input.
5. If the filename changed, delete the old file's copies from the three derived folders.
6. `./run_all.sh`.

**Over-the-board-only variant.** `--source-type otb` (on `run_pipeline.py`, `c3_close_game_drawrate.py` and `c5_upset_tests.py`) excludes the online Play-ins and writes `_otb`-suffixed outputs, which are not tracked. It reproduces the numbers in METHODOLOGY.md's Corpus note and is not part of `run_all.sh`.

## Modules

| Module | Role |
|---|---|
| **Configuration** | |
| `config.py` | Shared constants: `OPENING_WINDOW_MOVES` (15), `MIN_ELO` (2000), `MIN_CELL_COUNT` (20), `BOOTSTRAP_ITERATIONS` (5000), `DEFAULT_SEED` (12345), `CORPORA`, `FORMATS`, `SOURCE_TYPES`. The only place file paths are hard-coded. |
| `run_pipeline.py` | CLI for scalar extraction and the rebuild stages (`--help` lists stages) |
| **Ingest** | |
| `ingest/manifest_loader.py` | Load and normalize both manifests; parse and tag PGNs |
| `ingest/filters.py` | Broadcast-anomaly filter (forfeits, <2 real plies, bad FEN, duplicates) and Elo filter (both players ≥2000) |
| `ingest/audit_log.py` | Per-game exclusion log and per-event funnel table |
| `ingest/standard_rating_backfill.py`, `ingest/rating_update.py` | Write FIDE ratings into Standard / Freestyle PGNs |
| `ingest/engine_annotate_standalone.py` | Stockfish pass; self-contained, run separately (see `ENGINE.md`) |
| `ingest/twic_event_stats.py` | Recompute the statistics columns of `twic_event_classification.xlsx` |
| **Features** | |
| `features/clock_parser.py` | Time-control parsing and `[%clk]` → per-move time |
| `features/annotate_time.py`, `annotate_time_batch.py` | Write `[%tspent]` using the manifest's `time_control_pgn` |
| `features/extract_scalars.py` | One row per game: players, ratings, result, provenance (used by C3 and Claim 4) |
| **Banding** | |
| `banding/band_gap_builder.py` | `derive_bins` (rating bands for C1/C2, used by `h1_stage3_band_gap.py`); `build_bands_c4c5` (Elo cleaning for Claim 4) |
| **Analysis: Claims 1–2** | |
| `analysis/h1_stage1`–`h1_stage4_*.py` | Per-move data → per-game features → bands → H1a, H1b, C2 and gradient tests |
| `analysis/h1_band_tests.py` | Per-band Chess960 − standard differences (player-block bootstrap), Cochran's Q, pooled H1b |
| `analysis/player_overlap.py` | Within-player comparison across corpora |
| `analysis/volatility.py` | In-game swings and lead changes (moves 1–15); outcome volatility (C3) |
| `analysis/ply_by_ply.py` | Ply-by-ply accuracy-gap curve |
| `analysis/coverage_sensitivity.py` | H1b clock-coverage disclosure and complete-case check |
| `analysis/matching.py` | Covariate balance and IPW check on the gradient |
| `analysis/hypothesis_tests.py` | Test functions and CI helpers (below) |
| **Analysis: Claims 3–4** | |
| `analysis/c3_close_game_drawrate.py` | C3: draw rate for \|gap\| ≤ 100, adjusted for average rating |
| `analysis/c5_upset_tests.py` | Claim 4 primary test: underdog and favorite win on the C3 sample |
| `analysis/c5_bin_table.py` | Claim 4 descriptive outcome shares by gap bin (Figure 2 data) |
| `analysis/c4_elo_scale.py`, `loto_c4_expected_score.py`, `c4_gap_restricted_bands.py` | Supplementary fractional-score predictability model, its leave-one-out and per-band checks |
| **Robustness** | |
| `analysis/robustness.py` | Leave-one-tournament-out for H1a, C2, the gradient and the supplementary interaction model |
| **Figures** | |
| `figures/figures.py` | `rating_accuracy_gradient_plot` (Figure 1), `outcome_stacked_bars` (Figure 2) |

Claim 4 is computed by the `c5_*` files; the `c4_*` files hold the supplementary predictability models.

All models with player clustering use two-way (White × Black) clustering on bare player names, except the player-side gradient fit, which clusters by player.

## Conventions

- **Organized by pipeline stage.** Corpus (`standard`/`freestyle`) and format (`classical`/`rapid`) are function arguments, never separate code paths, so both corpora are treated identically.
- **No hard-coded paths** outside `config.py`; everything else takes paths as arguments.
- **Time controls come only from the manifest's `time_control_pgn` column**; the PGN `TimeControl` header is never used. An event with no value is logged as an observation. OTR divides time on moves 1–15 by time on the whole game, so every period's increments matter.
- **Libraries:** pandas and pyarrow (data), scipy.stats and statsmodels (tests), numpy, python-chess (PGN and engine).

## Function reference

Every public function has a full docstring in its source file. The main entry points:

| Function | Input → output |
|---|---|
| `manifest_loader.load_manifest(freestyle_path, standard_path)` | Both manifests → one DataFrame with normalized `corpus`/`format`/`source_type` and resolved file paths |
| `manifest_loader.load_corpus(manifest, corpus, format, source_type=None, source="updated_time")` | Games from a derived tree (never `data/games/`), tagged with `GameId`, `SourceEvent`, `SourceType`, `Corpus`, `StratumFormat` |
| `manifest_loader.manifest_time_controls(manifest)` | `(increment_by_event, base_by_event)` in seconds, from `time_control_pgn` |
| `filters.filter_broadcast_anomalies(games)`, `filters.filter_by_elo(games)` | Shorter game list; one log row per dropped game |
| `audit_log.build_event_summary(...)` | Per-event funnel: raw count → each exclusion reason → games analyzed |
| `clock_parser.parse_pgn_time_control(tc)` / `parse_pgn_time_control_periods(tc)` | `(base, increment)` for the first period / all periods |
| `annotate_time.annotate_time_one_game(game, increment, base_time, periods=None)` | Tags each computable move with `[%tspent]`; idempotent |
| `extract_scalars.extract_scalars(games)` | `{corpus}_{format}_scalars.parquet`: `game_id, source_event, source_type, corpus, format, white_player, black_player, white_elo, black_elo, result` |
| `band_gap_builder.derive_bins(values, min_cell_count, starting_width)` | Bin edges, merging the sparsest bin until each has `min_cell_count` |
| `band_gap_builder.build_bands_c4c5(df)` | `BandGapResult(.data, .band_edges)`; one row per game |
| `hypothesis_tests.test_h1a_opening_acpl`, `test_h1b_opening_time_ratio`, `test_c2_variance`, `test_rating_accuracy_gradient`, `test_c4_interaction` | Banded frames for both corpora → tidy results table |
| `hypothesis_tests.bootstrap_ci`, `cluster_bootstrap_ci`, `wilson_ci` | Percentile, player-block and Wilson intervals |
| `figures.rating_accuracy_gradient_plot(...)`, `figures.outcome_stacked_bars(...)` | 300-DPI PNG; returns the `Figure` |
