# chess960-empirics

An empirical comparison of Chess960 (Freestyle Chess) and standard chess, using engine- and clock-annotated games from elite over-the-board events and the online Freestyle Chess Play-in qualifiers (January 2025 – June 2026).

## Claims

1. **Chess960 removes the advantage of memorized opening preparation** (opening accuracy, opening time, within-player comparison).
2. **Chess960 rewards understanding over memorization** (within-band variance of opening accuracy and the rating–accuracy gradient, in absolute centipawns).
3. **Chess960 produces fewer draws** among evenly matched players (within 100 Elo).
4. **Between closely matched players, the lower-rated player wins more often in Chess960**: supported in rapid, as a consequence of fewer draws; not in classical.

Methods, results and caveats for each claim are in **`METHODOLOGY.md`**.

## Documents

| File | Contents |
|---|---|
| `METHODOLOGY.md` | Each claim's test, conventions, results and caveats |
| `data/games/Data_Selection.md` | Which events and games are included, and how ratings were assigned |
| `ENGINE.md` | Stockfish settings and how the evaluations were produced |
| `pipeline/README.md` | Code layout and function reference |
| `figure_scripts/README.md` | Figure scripts and what each figure shows |

## Reproducing the results

### Quick check (no external data needed)

```bash
python3.12 -m venv .venv-pipeline
.venv-pipeline/bin/pip install -r pipeline/requirements.txt
./run_all.sh --from-tracked
```

This reruns every analysis that works from the files in this repository:

- **Claims 1–2:** opening accuracy (H1a), opening time (H1b), within-band variance (C2), the rating–accuracy gradient, band-level tests, and the ply-by-ply, clock-coverage, matching and IPW checks
- **Claim 3:** close-game draw rates and leave-one-tournament-out
- **Claim 4:** close-game outcome models, outcome shares by rating gap, and leave-one-tournament-out
- **Both figures**

Two analyses need `data/processed/Updated_engine_eval/`, which is not in this repository, and are skipped with a message:

- in-game swings and outcome volatility (`volatility.py`)
- the within-player comparison (`player_overlap.py`)

### Full run

```bash
./run_all.sh
```

Reruns everything, including the two analyses above, once `Updated_engine_eval/` is available. `run_all.sh` defines every step in order and stops at the first failure; its comments say what each step produces and which steps need files not in this repository.

Rebuilding the intermediate files from the raw PGNs also needs:

1. **FIDE monthly rating lists** (rating steps): not included, for size and licensing reasons. See `data/Rating_lists/README.md` for which lists are needed and where to get them.
2. **Stockfish 19** (engine step): `brew install stockfish`, `apt-get install stockfish`, or [stockfishchess.org](https://stockfishchess.org/download/). See `ENGINE.md`; the engine step takes about 20 hours on 8 cores.

## Data availability

**Included**

- `data/games/`: source PGNs, the Standard and Freestyle manifests, and `twic_event_classification.xlsx`
- `data/processed/`: analysis-ready Parquet files
- `data/results/`: all result CSVs, figures and exclusion logs
- `data/Rating_lists/`: FIDE ID matches and per-player ratings used (`Playing_lists_with_Fide_id/`, `Playing_lists_with_Rating/`, `Standard_missing_fideid_candidates.xlsx`)

**Not included**

- Intermediate PGN trees in `data/processed/` (`Updated_Ratings/`, `Updated_Time/`, `Updated_engine_eval/`; see `data/processed/README.md`)
- FIDE monthly rating lists (`data/Rating_lists/FIDE_Rating_by_id_month/`)
- TWIC weekly PGNs (used only for event selection; see `data/games/Data_Selection.md`)

## License and attribution

Code: MIT License.

Data sources: games from Lichess broadcasts and Chess.com (Freestyle Play-ins, Coop Saaremaa); player lists with FIDE IDs from chess-results.com; FIDE ratings from ratings.fide.com; TWIC weekly issues for event listing and selection.
