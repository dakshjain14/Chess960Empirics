# Engine Analysis

How the Stockfish opening evaluations in `data/processed/Updated_engine_eval/` were produced.

## Settings

| | |
|---|---|
| Engine | Stockfish 19 (the version string is printed at startup) |
| Depth | 20 per position |
| Window | First 15 moves per player (30 plies per game) |
| UCI options | `Threads=1`, `Hash=256MB`, `MultiPV=1`, full strength |
| Workers | 8 processes, each with its own single-threaded Stockfish instance, one PGN file per task |
| Runtime | About 20 hours on an 8-core server (110 files, 16,730 games) |

Single-threaded instances avoid run-to-run differences from multi-threaded search. These settings are defined in `pipeline/ingest/engine_annotate_standalone.py` itself (it has no repository imports), not in `pipeline/config.py`.

A different Stockfish version or build may give slightly different evaluations, even at the same depth.

## Run

```bash
python pipeline/ingest/engine_annotate_standalone.py \
    --input-root data/processed/Updated_Time \
    --output-root data/processed/Updated_engine_eval
```

## Output

- One output PGN per input PGN, in the same folder structure as `Updated_Time/`.
- Any `[%eval]` in the source is removed first; every `[%eval]` in the output comes from this run, for the first 30 plies only. `[%clk]` and `[%tspent]` are kept unchanged.
- A game that cannot be analyzed (illegal move sequence, engine error) is counted per file, not dropped silently; counts are printed at the end. A resumed run treats a file as done only if its output has as many games as its input.
- Every game in the analysis corpus has evaluations for all 15 opening moves. The only two games with missing evaluations (unplayed forfeits in the 36th Cracovia Open A: one move, then null moves) are removed by the unplayed-forfeit rule in `data/games/Data_Selection.md`.
