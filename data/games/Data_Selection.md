# Data Selection

How tournaments and games were selected for the Chess960-vs-standard-chess study, and how player ratings were assigned. Rules for banding and comparing games during analysis are in `METHODOLOGY.md`.

## 1. Scope

| Item | Value |
|---|---|
| **Period** | January 2025 – June 2026 |
| **Time controls** | Classical and Rapid only (definitions below). Blitz and Armageddon are excluded. |
| **Standard corpus** (`data/games/Standard/`) | Over-the-board (OTB) events |
| **Freestyle corpus** (`data/games/Freestyle/`) | Chess960/Freestyle OTB events, plus the online Freestyle Chess Play-in qualifiers |
| **Players** | Both players rated ≥2000 FIDE (applied at analysis time, §4) |

**Time-control definitions** (per player; with increment, use `base + 60 × increment`):

- **Classical:** at least 90 minutes for a 60-move game.
- **Rapid:** more than 10 and less than 60 minutes for a 60-move game.
- **Blitz** (excluded): more than 3 and at most 10 minutes. Excluded because games are played under extreme time pressure and there are too few elite Chess960 blitz events for a comparable corpus.
- **Armageddon:** excluded.

**Online games.** Only OTB events are included, except the Freestyle Chess Play-in qualifying stages (Swiss and KO). These are structured, high-stakes qualifiers feeding directly into the Grand Slam Tour, contested by the same elite player pool under tournament conditions (fixed pairings, official supervision). Informal and casual online series (Titled Tuesday, etc.) are excluded.

## 2. Event selection

### 2.1 Standard events (TWIC ledger)

Every OTB event in TWIC issues #1578–#1630 (covering the study period) and #1655 (a margin beyond it) is listed in `twic_event_classification.xlsx`, with its statistics computed from TWIC's weekly PGNs (game counts, `Games_2100_2399`, `Median_max`, etc.) and the rule that decided its status. `In_manifest = Yes` marks the events in the study.

Selection uses TWIC's PGNs; while the game pgn which are analyzed for a selected event have come from the event's own platform (Lichess broadcast, chess-results.com, etc.), recorded in each manifest row's `Source` column.

| `Rationale` | Rule | Events |
|---|---|---|
| `Included` | Passed all rules below and ranked within the shortlist | 61 |
| `ADDED FOR 2100-2400 REPRESENTATION` | More than 550 games with `max(WhiteElo, BlackElo)` in 2100–2399, added so that rating range is covered: 25th ch-EUR Indiv 2025 (648), Serbia Open 2025 (589), 36th Cracovia Open A (577) | 3 |
| `Lower rank on shortlist` | Shortlist was ranked by `Median_max`, and top 22 for Classical and top 39 for Rapid | 1,087 |
| `Excluded_low_game_count` | Fewer than 30 games (Classical) or 25 (Rapid), counted per event across its stage files | 146 (plus TechM GCL 3rd-4th 2025, kept as an exception; 147 below the floor in total) |
| `Games not available with clock data` | No move-level clock data (`%clk`) available from PGN sources like lichess and chess.com| 10 |
| `online_series` | Online event other than a Freestyle Play-in | 136 |
| `blitz_excluded` | Blitz time control | 79 |
| `tiebreak_ambiguous_excluded` | Tiebreak games cannot be reliably separated from regular games | 32 |
| `mixed_time_control_excluded` | Bundles several time controls that cannot be split reliably(§3) | 2 |
| `armageddon_excluded` | Armageddon games | 2 |
| `engine_game_excluded` | Bot or engine games | 3 |
| `chess960_reserved` | Chess960 event; handled under Freestyle selection (§2.2) | 34 |

**Exception.** `TechM GCL 3rd-4th 2025` (24 games) is kept although below the Rapid floor: it is the playoff stage of TechM GCL 2025, whose round-robin stage has 180 games, and the floor applies per event, not per stage file.

`Median_max` (median of `max(WhiteElo, BlackElo)` per event) exists only in this ledger; the study manifests carry statistics recomputed from the sourced PGNs.

## 2.2 Rebuilding the TWIC ledger

`pipeline/ingest/twic_event_stats.py` recomputes the statistics columns of `twic_event_classification.xlsx` from TWIC weekly PGNs (theweekinchess.com, issues #1578–#1630 and #1655). It merges by event name, so the judgment columns (`Study_status`, `Rationale`, `In_manifest`, `Game Availability`, `Comment`, etc.) are kept; new events are left blank for review. TWIC PGNs have no `TimeControl` tag, so `Classification` is guessed from the event name and manually verified.

```bash
PYTHONPATH=. .venv-pipeline/bin/python pipeline/ingest/twic_event_stats.py \
    --twic-dir path/to/twic/ --out data/games/twic_event_classification.xlsx
```

### 2.3 Freestyle events

TWIC does not cover Chess960 events comprehensively, so Freestyle selection uses a fixed list of elite events, and every stage file of these events is included regardless of its own game count (the game-count floor does not apply):

Freestyle Chess Grand Slam (Weissenhaus, Paris, Las Vegas, Cape Town) and its Play-in qualifiers; FIDE Freestyle Chess World Championship; GRENKE Freestyle Open; Biel960 events; 6th Internationales Schach960 Festival; ClutchChessLegends. The game count and other data in manifest comes from PGN files of these tournaments downloaded from source mentioned in the Freestyle manifest - `data/games/Freestyle/freestyle_manifest.xlsx`

## 3. Event files


- **Mixed-format files** are split by tier and only the Classical and Rapid parts are kept; files that cannot be split reliably are excluded.
  - *FIDE World Cup 2025.* Each round's broadcast file mixes the classical mini-match with rapid tiebreaks. Files were split on the `BroadcastURL` tier slug: `game-1`/`game-2` → `FIDE_World_Cup_2025_Classical.pgn` (412 games); `tiebreak-1` (15+10) → `FIDE_World_Cup_2025_Rapid_tiebreak1.pgn` (158 games); `tiebreak-2` (10+10) → `FIDE_World_Cup_2025_Rapid_tiebreak2.pgn` (54 games). Each is its own manifest row.
- **Sources.** Each manifest row's `Source` column records the platform the PGN came from. `FIDE_World_Cup_2025_Classical.pgn` and `PragueChallengers2025-Classical.pgn` are Lichess broadcasts despite their filenames.
- **Filename labels.** `ParisFreestyleRR_10+05.pgn` was played at 10+10 (`time_control_pgn = 600+10`); the filename label differs.

## 4. Game-level filters (applied at analysis time)

Source files are not modified; these games are dropped during analysis.

- **Rating:** both players rated ≥2000. Unrated players (rating `0`, §5) are therefore excluded.
- **Bots:** games with `WhiteTitle`/`BlackTitle` = `"BOT"`, or otherwise identifiable as engine games, are excluded.
- **Unplayed and forfeited games** (`h1_stage1_extract_per_move.py`):
  - `Termination = "Unplayed"` with fewer than 10 real plies. Games labelled unplayed but with ≥10 real plies are kept, since some broadcasts mislabel played games.
  - Fewer than 2 real plies, whatever the label. No legal game can end after one ply, so these are forfeits or defaults; all 29 such games are decisive or forfeit results, none drawn.
  - Games with 2–9 real plies are kept (see `_exclude_unplayed_forfeits` for the reasoning).
  - **Clock data.** Games without clock data are excluded from Claim 1 OTR related Analysis.

## 5. Ratings

All ratings are official FIDE ratings of the game's type (Classical or Rapid) for the event's month, taken from FIDE's monthly lists (`data/Rating_lists/FIDE_Rating_by_id_month/`, not included; download from ratings.fide.com).

**Lookup rule (both corpora).** Find the player's FIDE ID in the list for the event's type and month. If absent, use the other type's list for the same month. If absent from both, the player is unrated and gets rating `0`, meaning *not rated*, never a literal rating.

### Standard corpus (`pipeline/ingest/standard_rating_backfill.py`)

Standard PGNs carry FIDE ratings for their time control. Games with a FIDE ID but no rating tag are backfilled with the lookup rule, using the manifest's `format` and `rating_month` columns. `rating_month` is the start month of the file's game dates, checked against TWIC's event dates. 

FIDE IDs missing from Standard PGNs were identified manually; the matches are in `data/Rating_lists/Standard_missing_fideid_candidates.xlsx` (player name tag, FIDE ID, and rating, or `0` for a confirmed-unrated player). `standard_rating_backfill.py` applies each row's name/FIDE ID/rating to the matching game (matched by tournament file and player name tag) before running the automated lookup above, so a row that only supplies a FIDE ID still gets its rating filled in by the lookup. A row that matches no game in any Standard PGN file is printed as an `ALERT`.

### Freestyle corpus (`pipeline/ingest/rating_update.py`)

Freestyle PGNs carry inconsistent ratings (chess.com, organizer "Freestyle" ratings, or FIDE ratings of unclear type and month), so every player's rating is reassigned:

1. **FIDE ID.** Play-in games from chess.com identify players by chess.com username. These players were matched to FIDE IDs through the ratings.fide.com links on their chess.com player pages. Unresolvable players are marked `NOT FOUND`. Matches are in `data/Rating_lists/Playing_lists_with_Fide_id/`: one roster CSV per tournament series (15 files for 43 manifest rows; 4 rows already carry complete FIDE IDs and ratings).
2. **Month and type** come from the manifest. The event's original type is kept in `Base Rating Type`; `Rating_Type` records the list actually used after any fallback.
3. **Rating** follows the lookup rule above. Where a roster already held a rating, a mismatch is flagged and the existing value kept.
4. `rating_update.py` writes the ratings into the PGNs, matching players by FIDE ID (or normalized name); players missing from a roster are left unchanged and flagged.

Both scripts patch rating tags as plain text rather than re-exporting the PGN (a strict parser can damage some Chess960 movetext), and write to `data/processed/Updated_Ratings/`; `data/games/` is never modified.



