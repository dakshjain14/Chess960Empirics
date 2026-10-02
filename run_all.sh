#!/usr/bin/env bash
# run_all.sh — defines and runs the full pipeline, 23 steps, in order.
#
# Starts from an existing data/processed/Updated_engine_eval/ tree — it does
# NOT run Stockfish. If you don't have that tree yet, see pipeline/README.md's
# "Full rebuild from raw PGNs" section first (needs FIDE rating-list data
# and a Stockfish install — see root README.md's "External Dependencies for
# Full Reproduction").
#
# Steps marked "[needs Updated_Time/]" or "[needs Updated_engine_eval/]" read
# that intermediate PGN tree directly; both are excluded from this repo (see
# root README.md's "Data included in this repository" section) and must
# already exist on disk. Every other step reads only tracked Parquet/CSV
# files and needs nothing beyond what's in this repo plus this script's own
# earlier steps.
#
# Stops at the first failure (set -e). Regenerates every Parquet file in
# data/processed/ and every result/figure in data/results/.

set -e

PY=.venv-pipeline/bin/python

# --- H1 path: per-move -> per-game -> banded -> hypothesis tests (1-5) ---
$PY -m pipeline.analysis.h1_stage1_extract_per_move           # [needs Updated_engine_eval/] -> per_move_data.parquet
$PY -m pipeline.analysis.h1_stage2_aggregate_game_features     # -> game_features.parquet
$PY -m pipeline.analysis.h1_stage3_band_gap                    # -> banded_h1_{corpus}_{format}.parquet
$PY -m pipeline.analysis.h1_stage4_hypothesis_tests             # -> h1a/h1b/c2/gradient results CSVs
PYTHONPATH=. $PY pipeline/analysis/h1_band_tests.py             # -> h1a/h1b_band_diff + _interaction, h1b_pooled_summary CSVs

# --- Scalars path: per-corpus/format extraction, then C3, then volatility (6-11) ---
$PY -m pipeline.run_pipeline --stage extract_scalars --corpus freestyle --format classical  # [needs Updated_Time/]
$PY -m pipeline.run_pipeline --stage extract_scalars --corpus freestyle --format rapid       # [needs Updated_Time/]
$PY -m pipeline.run_pipeline --stage extract_scalars --corpus standard --format classical    # [needs Updated_Time/]
$PY -m pipeline.run_pipeline --stage extract_scalars --corpus standard --format rapid        # [needs Updated_Time/]
PYTHONPATH=. $PY pipeline/analysis/c3_close_game_drawrate.py   # -> c3 close-game draw-rate results CSVs
PYTHONPATH=. $PY pipeline/analysis/volatility.py                # [needs Updated_engine_eval/ and the freestyle/standard
                                                                  # scalars parquet just written above] -> ingame_swings.csv, outcome_volatility.csv

# --- Claim 4 results: standalone scripts, not behind run_pipeline.py's CLI, but these
# produce the reported Claim 4 results, including the primary test (c5_upset_tests.py) (12-15) ---
PYTHONPATH=. $PY pipeline/analysis/c4_gap_restricted_bands.py  # -> c4_interaction_by_band_classical.csv
PYTHONPATH=. $PY pipeline/analysis/c5_bin_table.py              # -> c5_outcomes.csv
PYTHONPATH=. $PY pipeline/analysis/c4_elo_scale.py              # -> c4_codings.csv, c4_elo_scale.csv
PYTHONPATH=. $PY pipeline/analysis/c5_upset_tests.py            # -> c5_upset_tests.csv

# --- Robustness / matching / auxiliary analyses (16-21) ---
PYTHONPATH=. $PY pipeline/analysis/robustness.py                # -> loto_{h1a,c2,c4_interaction,gradient}.csv
PYTHONPATH=. $PY pipeline/analysis/loto_c4_expected_score.py    # -> loto_c4_expected_score.csv
PYTHONPATH=. $PY pipeline/analysis/matching.py                  # -> matching_{covariate_balance,ipw_h1a_shift,ipw_gradient}.csv
PYTHONPATH=. $PY pipeline/analysis/ply_by_ply.py                # -> ply_by_ply_{curve,summary}.csv
PYTHONPATH=. $PY pipeline/analysis/coverage_sensitivity.py      # -> h1b_coverage_by_corpus_format.csv, h1b_complete_case_sensitivity.csv
PYTHONPATH=. $PY pipeline/analysis/player_overlap.py            # [needs Updated_engine_eval/] (FIDE IDs read from engine-eval'd
                                                                  # PGNs) -> player_overlap_counts.csv, player_paired_comparison_{classical,rapid,stats}.csv

# --- Paper figures (22-23) ---
PYTHONPATH=. $PY figure_scripts/fig1_gradient.py                 # -> fig1_gradient.png
PYTHONPATH=. $PY figure_scripts/fig2_outcomes.py                 # -> fig2_outcomes.png
