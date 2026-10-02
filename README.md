# chess960-empirics

An empirical comparison of Chess960 (Freestyle Chess) and standard chess, using engine- and clock-annotated games from elite over-the-board events and the online Freestyle Chess Play-in qualifiers (January 2025 – June 2026).

## Claims

Full Claims, methods, results and caveats are in **`METHODOLOGY.md`**.


## Documents

| File | Contents |
|---|---|
| `METHODOLOGY.md` | Each claim's test, conventions, results and caveats |
| `data/games/Data_Selection.md` | Which events and games are included, and how ratings were assigned |
| `ENGINE.md` | Stockfish settings and how the evaluations were produced |
| `pipeline/README.md` | Code layout and function reference |
| `figure_scripts/README.md` | Figure scripts and what each figure shows |

## Reproducing the results

**Quick check, from a fresh clone, no external data needed:**

```bash
./run_all.sh --from-tracked
```

This skips every step that needs `data/processed/Updated_Time/` or `Updated_engine_eval/` (both excluded from this repo — see "Data availability" below), printing one line per skipped step, and reproduces everything else from the tracked Parquet/CSV files already committed. It reproduces: H1a (opening ACPL), H1b (opening time ratio), C2 (the rating/accuracy gradient), the band-level difference/interaction tests, C3 (close-game draw-rate AME, including its LOTO sweep), C4/C5 (upset-win AME, outcome bins, LOTO sweep), and every robustness/matching/IPW/ply-by-ply/coverage-sensitivity check and figure. It does **not** reproduce the in-game swings/lead-change analysis or the outcome-volatility ratio (`volatility.py` re-parses the raw engine-annotated PGNs directly) or the within-player paired comparison (`player_overlap.py` reads FIDE IDs from those same PGNs).

**Full run, once `Updated_engine_eval/` exists on disk:**

```bash
./run_all.sh
```

`run_all.sh` defines and runs every step in order (main tests and all robustness checks), stopping at the first failure. Its comments say what each step produces and which steps need files not in this repository. This mode additionally reproduces the in-game swings/lead-change analysis, the outcome-volatility ratio, and the within-player paired comparison.

Rebuilding the intermediate files from the raw PGNs needs:

1. **FIDE monthly rating lists** (for the rating steps): not included, for size and licensing reasons. See `data/Rating_lists/README.md` for which lists are needed and where to get them.
2. **Stockfish 19** (for the engine step): `brew install stockfish`, `apt-get install stockfish`, or [stockfishchess.org](https://stockfishchess.org/download/). See `ENGINE.md`; the engine step takes about 20 hours on 8 cores.

## Data availability

**Included**

- `data/games/`: source PGNs, manifests for both Standard and Freestyle chess game sources, `twic_event_classification.xlsx`
- `data/processed/`: analysis-ready Parquet files
- `data/results/`: all result CSVs, figures and exclusion logs
- `data/Rating_lists/`: FIDE ID matches (`Playing_lists_with_Fide_id/`, `Playing_lists_with_Rating/`, `Standard_missing_fideid_candidates.xlsx`)

**Not included**

- Intermediate PGN trees in `data/processed/` (see `data/processed/README.md`), including `Updated_engine_eval/`
- FIDE monthly rating lists in `data/Rating_lists/FIDE_Rating_by_id_month/Classical/` and `data/Rating_lists/FIDE_Rating_by_id_month/Rapid`
- TWIC weekly PGNs (used only for event selection; see `data/games/Data_Selection.md`)


## License and attribution

Code: MIT License. Games come from Lichess broadcasts, Chess.com Play-ins; chess-results.com was used to download playing lists with FideId; TWIC weekly issues were used for event listing and selection.
