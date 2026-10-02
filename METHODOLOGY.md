# Analysis Methodology

Documents each hypothesis under test, the claim it addresses, and exactly how included games (see Data_Selection.md for corpus inclusion criteria) are grouped, weighted, and compared to test it.



## Claims tested

**Claim 1: Chess960 removes the advantage of memorised opening preparation.** 
If true: without prepared lines, players must work out the opening at the board, so they spend more clock time on it and play it less accurately. Measured by: share of clock used on moves 1–15 (OTR) and opening accuracy (ACPL), comparing the same players in both formats to rule out who plays. Tested in: C1 (H1a, H1b) and the within-player comparison. Supported in both time controls.

**Claim 2: Chess960 rewards understanding over memorisation.** 
If true: with preparation gone, real differences in skill show up more in opening play: stronger players pull further ahead of weaker ones, and players of the same rating spread out more. Measured by: how steeply opening accuracy improves with rating, and how much accuracy varies among same-rated players, stated in absolute centipawns. Tested in: C2. Supported in absolute centipawns in both time controls.

**Claim 3: Chess960 produces fewer draws.** 
If true: evenly matched players, who most often draw in standard chess, draw less often in Chess960. Measured by: draw rate among players within 100 Elo of each other, adjusted for playing level. Tested in: C3. Supported in both time controls.

**Claim 4: Between closely matched players (within 100 Elo), the lower-rated player wins more often in Chess960 than in standard chess.** 
If true: with fewer draws between closely matched players, the lower-rated player should win more often, and so should the favorite. 
Measured by: underdog win rate, adjusted for average rating and rating gap, Chess960 vs standard, within 100 Elo. Tested in: C4. Supported in rapid as a consequence of fewer draws: both players win more often; not in classical.

## Claims Results

This is a record of what was tested and found, The claims formally reported are:

- **C1 — H1a:** Opening ACPL (moves 1-15) is lower in standard chess than Chess960, and the gap varies by rating band.
- **C1 — H1b:** Opening Time Ratio (proportion of clock time spent on moves 1-15) differs between formats, and by rating band.
- **C2 — rating/accuracy gradient:** Rating predicts opening ACPL more weakly in standard chess than in Chess960, in absolute centipawns.
- **C2:** Within-rating-band variance in opening ACPL (Brown–Forsythe), in absolute centipawns, is greater in Chess960 than standard chess.
- **C3:** Chess960 shows a lower draw rate than standard chess between evenly matched players (`|gap| <= 100`), adjusting for average rating.
- **C4:** Between closely matched players (within 100 Elo), the lower-rated player wins more often in Chess960 than in standard chess. Supported in rapid as a consequence of fewer draws: both players win more often; not in classical — see C4's own section.


## Shared conventions across all hypotheses

- All comparisons are made **within a time-control stratum** (classical vs. classical, rapid vs. rapid) — classical and rapid data are never pooled together in any test.
- **Rating bands are a SHARED grid, common to both corpora, within each time-control format** — this applies to H1a/H1b (fixed 100-point bands anchored at round numbers, e.g. 2000-2099, derived once from the pooled Freestyle+Standard rating distribution per format) and to C2. C2 (variance comparison, Brown–Forsythe/median-centred Levene test) requires both corpora to be compared within the same nominal rating band, the same requirement H1a/H1b share — C2 reads the same shared `banded_h1_*` bands H1a/H1b use, grouping by (format, band) and ignoring gap_bin, since C2's test doesn't need gap-bin granularity. Gap-bin edges within a band remain derived **independently per corpus** — sharing those isn't needed for a within-band cross-corpus comparison. C4's descriptive outcome-shares supplement uses a different convention entirely: one row per game, raw unsigned rating-gap bins 0–100 / 101–250 / 251+, no rating band — it bins games only by their own raw unsigned rating gap, pooled across every rating level; the band-based convention above never applies to it. C4's claim itself is scoped to `|gap| <= 100` only, with no band dimension either. **C3 is not band-based at all** — it's a close-game (|gap|<=100) logistic test, see C3's own section.
- Every rating-band x gap-bin cell must contain a minimum of ~20-25 games to be reported. Cells below this floor on the shared 100-point grid are merged with an adjacent band only if the pooled distribution itself can't clear the floor at that width (not observed in this data — see H1a/H1b's Results below); gap-bin cells below floor are still merged with an adjacent gap-bin during gap-bin derivation. Because H1a, H1b, and C2 draw on different underlying data (engine eval only, vs. clock data too), a cell can independently clear the floor for one measure and not another — each result row carries its own `n` and a `status` (`"ok"` / `"insufficient_n (<20)"`) rather than a single pass/fail per cell. See "Clock data coverage" under H1b below for a traced, real example (standard-chess classical, 2100-2199 band).
- Opening window is defined as **moves 1-15** (each player's first 15 moves, i.e. the first 30 plies) for every measure that requires one — opening ACPL, the Opening Time Ratio numerator, and per-move time/accuracy pairs. This is a single configurable parameter applied identically across the engine analysis, clock parsing, and the engine-annotated PGN export.

---

**Statistical approach.** Players appear in many games, so standard errors are clustered by both players (game-level models) or by player (player-side models), and bootstrap intervals resample players. Most Chess960 − standard comparisons are additionally checked by leaving out one tournament at a time (H1a, C2 — including its Rating/Accuracy Gradient subsection, C3, Claim 4, and the C4 supplementary predictability model — see each one's own "Leave-One-Tournament-Out Robustness" subsection). H1b has no dedicated tournament-exclusion check; instead its complete-case draw rule is stress-tested by `coverage_sensitivity.py`'s row bootstrap, comparing it against a partial-data method band-by-band (see "H1b Coverage and Partial-Data Robustness Check" below).

---

## C1 — Claim: Chess960 removes the advantage of memorized opening preparation

**Claim:** Chess960 removes the advantage of memorized opening preparation.

Games played January 2025–June 2026 (see Data_Selection.md).

Opening preparation is not measured directly: the data cannot show whether a move was memorised or whether a player knew a theoretical line. The analyses measure behavioural consequences expected when preparation is unavailable: opening accuracy (ACPL), opening clock allocation (OTR), within-rating variance, and the rating–accuracy relationship. Results are therefore interpreted as consistent with reduced reliance on memorised preparation, not as a direct measurement of it.

**Sub-hypotheses:**
- H1a: Opening ACPL (moves 1-15) is lower in standard chess than Chess960, and this gap varies by rating band.
- H1b: Opening Time Ratio (proportion of clock time spent on moves 1-15) differs between formats, and by rating band.

**Band/gap assignment:** TWO rows per game (one per player). `band = own rating`, assigned from a **shared 100-point grid common to both corpora per format** (see "Shared conventions" above). `gap = own_rating - opponent_rating`, SIGNED (preserves whether the player was favored or the underdog), derived independently per corpus within each band. Games are pooled across both player-sides, with standard errors clustered by player, since each player's move quality and time usage are independently generated — not an algebraic mirror of the opponent's.

**Tests:**
- H1a: mean opening ACPL by band, bootstrap CI (5,000 iterations).
- H1b: mean OTR by band, same bootstrap approach.

**Data requirements:** move-level clock annotations (%clk) and Stockfish evaluation (depth 20, moves 1-15) for every game.

**Implementation (H1a/H1b pipeline).** Built as four inspectable, Parquet-backed stages, each independently auditable rather than going straight from annotated PGN to final statistics:
1. `pipeline/analysis/h1_stage1_extract_per_move.py` — parses `data/processed/Updated_engine_eval/` (Stockfish eval + clock annotations co-located on each move, see ENGINE.md) into one row per player per ply for the whole game -> `per_move_data.parquet`.
2. `h1_stage2_aggregate_game_features.py` — aggregates to one row per (game, side): `opening_acpl`, `otr` (complete-case — null unless `full_clock_coverage`), `gap_signed` -> `game_features.parquet`.
3. `h1_stage3_band_gap.py` — derives the shared rating-band grid per format (pooled Freestyle+Standard distribution), then per-corpus gap-bin edges within each band -> `banded_h1_{corpus}_{format}.parquet` + `bin_boundaries_{corpus}_{format}.json` (full merge audit trail).
4. `h1_stage4_hypothesis_tests.py` — the Stage 4 driver -> `h1a_results.csv`, `h1b_results.csv`, `c2_results.csv`, `rating_accuracy_gradient_results.csv`.

**Known data-quality caveats:**
- The production engine run only recorded each ply's post-move evaluation, not a pre-move one, since CPL requires an eval both before and after a move and the starting position's eval was never computed by the annotation pipeline (`engine_annotate_standalone.py` only records the post-move eval on each ply). So **White's move-1 CPL is always null** — White's opening ACPL is therefore a mean over 14 analyzed moves, Black's remains a mean over 15. This asymmetry is symmetric in direction across both corpora (Chess960 and standard) and both time-control strata, so it does not bias the cross-corpus comparison, only slightly widens White's individual confidence interval relative to Black's. More generally, a missing evaluation on the current or previous ply gives a null CPL for that ply, which is excluded from the ACPL mean, not counted as zero.
- A game is excluded only if `Termination == "Unplayed"` with fewer than 10 real plies, or it has fewer than 2 real plies regardless of label (catching forfeits under other labels — `timeout`, `abandoned`, `resigned`, blank) — not on the `Termination` header field alone (Data_Selection.md's "Analysis-time filters").
- OTR is complete-case: null unless every move of the game has a recorded clock time, not just the opening window (see "Clock data coverage" under H1b below).

**Results (full corpus).**

**Shared-grid floor check.** At the default 100-point resolution, the shared, pooled-distribution grid is `[2000, 2100, ..., 2900]` for both classical and rapid (9 bands each), and every (corpus, format, band) cell must clear `MIN_CELL_COUNT` (20). Every cell clears floor on `opening_acpl`. One cell falls below floor on `otr`: standard classical's 2000-2099 band (n=13) — flagged `insufficient_n` and excluded from H1b's reported range (see "Clock data coverage" under H1b below). No band merges were applied; 100-point resolution is used as final.

*H1a.* Freestyle opening ACPL is dramatically and consistently higher than standard's: in every one of the 18 (format, band) groups, freestyle's full range of per-gap-bin means lies entirely above standard's (checked across all 341 (corpus, format, band, gap-bin) rows). N-weighted means: freestyle 20.8 (classical) / 28.8 (rapid) vs. standard 7.6 / 10.8. Per band, the Chess960/standard opening-ACPL ratio (N-weighted means, `h1a_results.csv`) ranges 2.1-2.7x in classical and 2.7-3.0x in rapid. Bootstrap CIs are player-block bootstrapped (resampling whole players, not rows, so a player appearing in several games doesn't overstate precision — `cluster_bootstrap_ci` in `hypothesis_tests.py`); across each corpus's full per-band range they are non-overlapping in 14 of 17 testable (format, band) groups (e.g. band 2400-2499/classical: freestyle 13.5-29.4 across gap-bins, standard 5.5-11.3 — a clean, non-overlapping separation); the three exceptions, all at the high-rated tail where the widest bounds touch, are classical 2600-2699 (freestyle 10.1-22.3 vs. standard 4.7-10.1), classical 2700-2799 (freestyle 8.4-17.6 vs. standard 4.5-8.9), and rapid 2700-2799 (freestyle 10.0-32.0 vs. standard 4.6-11.8). The 18th group, **rapid 2800+, is a single-player band on the freestyle side (both its gap-bin cells and the standard side's single cell have only one distinct player) — `cluster_bootstrap_ci` returns no CI there, so it's excluded from this count rather than counted either way.** No `insufficient_n` flags anywhere (0/341 rows) — the single-player issue is a clustering-reliability gap, not a row-count one. A band-level Chess960-minus-standard CI and a band x corpus interaction test are reported separately below ("Band-level difference and interaction test").

*H1b.* Chess960 opening time allocation exceeds standard's in both formats, pooled across bands (player-block bootstrap): classical Chess960 0.635 [0.625, 0.645] (n=1,840) vs. standard 0.403 [0.393, 0.412] (n=5,181), difference +0.232 [0.219, 0.246]; rapid Chess960 0.510 [0.500, 0.520] (n=4,255) vs. standard 0.362 [0.356, 0.368] (n=11,658), difference +0.148 [0.136, 0.159] (`h1_band_tests.py` -> `h1b_pooled_summary.csv`). Per-band range (min-max of the 9 per-band means, excluding the one `insufficient_n` band): classical Chess960 60-67%, standard 37-47%. See "Clock data coverage" and "H1b Coverage and Partial-Data Robustness Check" below for the complete-case rule and its robustness to the partial-data alternative.

**Band-level difference and interaction test** (`pipeline/analysis/h1_band_tests.py` -> `h1a_band_diff.csv`, `h1a_band_interaction.csv`, `h1b_band_diff.csv`, `h1b_band_interaction.csv`). Replacing the informal "CIs non-overlapping" characterization above with a direct test: per (format, band), the Chess960-minus-standard difference with a player-block bootstrap 95% CI, and a Cochran's-Q heterogeneity test per format (does the difference vary across bands — a band x corpus interaction — rather than just whether it's nonzero anywhere). For H1a (opening ACPL): every one of the 17 testable bands (rapid 2800+ excluded — a single player there means `cluster_bootstrap_ci` has no second cluster to resample, so it returns no CI) has a diff CI excluding zero, and both formats show significant heterogeneity across bands (classical Q = 120.0, df=8, p<0.001; rapid Q = 110.2, df=7, p<0.001) — the gap between corpora is not constant across the rating range. The raw Chess960-minus-standard ACPL difference shrinks as ACPL levels fall with rating in both formats (per the H1a per-band means above); this is a statement about the absolute-centipawn scale, not a claim that the format effect itself narrows. For H1b (OTR): classical shows no significant heterogeneity (Q=6.7, df=7, p=0.46 — the +0.22 gap is roughly constant across bands), while rapid does (Q=30.4, df=7, p<0.001).

### H1a — Leave-One-Tournament-Out Robustness

The core H1a finding (Chess960 opening ACPL exceeds standard's) holds under exclusion of any single tournament, in every one of all 36 (corpus, format, band) cells — no exclusion approaches closing the gap between corpora anywhere (full sweep: `robustness.py::loto_h1a()` -> `loto_h1a.csv`).

Three bands show elevated (but not conclusion-threatening) sensitivity, all at the thin tails of the rating range where a single tournament naturally carries outsized weight: standard-classical's 2800+ band (range 24.9% of baseline, driven by the 87th Tata Steel Masters at 56.5% of that band's volume), freestyle-classical's 2000-2099 band (range 12.8%, driven by Grenke 2026 at 48.7% of that band's volume), and standard-classical's 2000-2099 band (range 11.8%, driven by 36th Cracovia Open A at 75.6% of that band's volume). All other 33 bands/formats show point-estimate ranges under ~8% across every exclusion tested.

### Within-Player Paired Comparison

**Question:** H1a/H1b's accuracy and time-allocation gap could in principle reflect different *players* appearing in each corpus (e.g. Chess960 attracting weaker or more error-prone players) rather than a genuine format effect on the same players. This check isolates the format effect by comparing each player against themselves across corpora.

**Method.** `pipeline/analysis/player_overlap.py` — for each format, finds every FIDE-ID-matched player with >=5 games in both Chess960 and standard, computes their `mean_opening_acpl` and `mean_otr` in each corpus, and runs a paired Wilcoxon signed-rank test on the within-player differences. FIDE IDs are read from the same `Updated_engine_eval/` tree `game_features.parquet` is built from, so the per-game join between the two is guaranteed consistent. Writes `player_paired_comparison_{format}.csv` (per-player rows) and `player_paired_comparison_stats.csv` (the test result itself — n pairs, Wilcoxon statistic, p-value, direction — one row per format x metric).

**Result:** classical **76 players**, rapid **130 players** (this is the number of players with valid paired values for *both* metrics — a distinct, smaller quantity than the raw FIDE-ID overlap count at the same 5-game threshold, which is 135 for rapid; some overlapping players lack a valid metric in one corpus and drop out of the paired test specifically). Both formats confirm the accuracy gap within the same players:

| format | n pairs | metric | mean diff (Chess960 − standard) | p-value |
|---|---|---|---|---|
| classical | 76 | opening ACPL | +10.04 | 3.6e-14 |
| classical | 76 | OTR | +0.247 | 3.6e-14 |
| rapid | 130 | opening ACPL | +17.42 | 4.5e-23 |
| rapid | 130 | OTR | +0.172 | 1.2e-21 |

Every comparison is positive (Chess960 higher) and significant at p<1e-13, ruling out player-composition differences as the driver of H1a's/H1b's accuracy and time-allocation gap. Every player had higher opening ACPL in Chess960 than in standard chess (76 of 76 classical, 130 of 130 rapid) — `player_paired_comparison_stats.csv`'s `n_positive`/`n_negative` columns, filtered to `metric="mean_opening_acpl"`.

### Ply-by-Ply Accuracy Gap

Bins: moves 1-3, 4-6, 7-9, 10-12, 13-15. Reliability-weighting method: all 9 rating bands, requiring `MIN_CELL_COUNT` at every move position.

The Chess960-standard opening ACPL gap grows monotonically through moves 1-9 in all four (format, side) combinations tested (8/8 consecutive steps positive, each exceeding 1cp on 3-move-block deltas). This early growth accounts for effectively all of the net gap increase across the full 15-move window (99.8-158% of the bin1-to-bin5 total, depending on series) — moves 10-15 add no net additional gap in any series, and in three of four series represent a partial reversal rather than a plateau: classical/Black is flat late (99.8% of total growth occurs by move 9); classical/White gives back a small amount (109.9%); rapid/White and rapid/Black give back proportionally more (116.1% and 157.8% respectively), with rapid consistently showing a larger late-window reversal than classical for both sides. Within each format, though, the White/Black ordering is not consistent: in rapid, Black shows a larger reversal than White (157.8% vs. 116.1%); in classical it runs the other way — White shows more give-back than Black (109.9% vs. 99.8%, where Black's late segment is flat-to-slightly positive rather than a reversal at all). Side asymmetry is not a stable pattern across formats here, only the rapid-vs-classical reversal-size difference is.

### In-Game Swings (moves 1-15)

A further measure of opening play beyond ACPL and OTR: how volatile the position's evaluation is through the opening, not just how accurately it's played. Re-parsed directly from the engine-annotated PGNs (not `per_move_data.parquet`, which stores only CPL) via `pipeline/analysis/volatility.py` -> `ingame_swings.csv`.

**Definitions:**
- Restricted to games with an engine eval present on every one of the first 30 plies (moves 1-15, both colours) — games ending early or missing an eval anywhere in that window are excluded from this measure.
- Every eval is capped at **+-1000cp** before any comparison, so a mate score (which this pipeline encodes as +-100,000cp) doesn't register as an arbitrarily large, meaningless swing.
- A **swing** is a move where the (capped) eval changes by >=100cp from the previous move.
- A **lead change** is a move where the (capped) eval goes from >=+100cp to <=-100cp, or the reverse (White's point of view).

**Method.** Per corpus x format, and per (format, gap_bin) using the same shared 0-100/101-250/251+ gap bins C4's descriptive outcome-shares table uses: mean swings per game, mean lead changes per game, the share of games with >=1 lead change. The Chess960-minus-standard difference on each measure carries a two-way (White-player x Black-player) multiplicative cluster-bootstrap 95% CI — the standard "pigeonhole" construction for a multiway cluster bootstrap on an arbitrary per-game statistic, each iteration independently resampling both player dimensions and weighting a game by the product of how many times its two players were drawn — and a leave-one-tournament-out range.

**Result.** A swing of 100cp or more almost always coincides with a move of CPL (centipawn loss) 100 or more — 99.7% of swings (8,679 of 8,702) do — so the swing count is close to H1a's own error rate counted per game: moves with CPL >=100 (a pawn or more) number 1.16 (classical) / 1.93 (rapid) per game in Chess960 vs. 0.18 / 0.37 in standard, essentially matching the swing counts below move-for-move. Chess960 shows substantially more swings and lead changes than standard in both formats and at every gap bin: overall, mean swings per game 1.17 (classical) / 1.93 (rapid) in Chess960 vs. 0.18 / 0.37 in standard (CPL>=100 moves: 1.16 / 1.93 vs. 0.18 / 0.37 — errors of a pawn or more are 5-7x as frequent in Chess960), and the Chess960-minus-standard difference's CI excludes zero in every (format, gap_bin) cell for swings. Lead changes are rare in both corpora — the highest share of games with at least one lead change in any cell is 3.1% for Chess960 (rapid, 251+ bin) and 0.5% for standard (same cell). Lead-change differences exclude zero in rapid at every gap bin, but not reliably in classical: the CI straddles zero at 0-100 and 101-250, and at 251+ its lower bound sits exactly at zero (the standard side has zero lead changes in that bin's 246 games, a floor effect on the cluster bootstrap). LOTO ranges stay on the same side of zero as the baseline CI in every cell where the baseline is significant, so no single tournament is driving these differences.

### Clock data coverage

**No game is dropped for missing clock data.** Only H1b needs clock data, and it degrades gracefully (that side's OTR is nulled) rather than dropping the game outright, which would wrongly remove it from H1a/C2/C3/C4 too.

Beyond clock data being simply missing, the source broadcasts also contain genuine clock-reading anomalies (a `%clk` value that's corrupted, mistimed, or otherwise inconsistent with the surrounding moves) scattered across many files — this is a property of the input data itself and isn't fixable upstream. Per-move time computation treats an anomalous or missing reading the same way: that move's time is left uncomputed rather than guessed, and the delta chain recovers cleanly from the next valid reading, so a bad reading costs at most the one move (occasionally two) it directly affects, not the rest of the game.

**OTR is complete-case.** OTR is the ratio of opening time to total game time, so it is computed only for player-sides whose clock times are recorded for every move — a gap anywhere in the game, not just inside the opening window, makes the whole-game denominator unreliable and nulls that side's OTR (`h1_stage2_aggregate_game_features.py`'s `full_clock_coverage` column; `otr` is null whenever it's `False`). This is the same rule for every OTR consumer — H1b and the within-player OTR comparison (`player_overlap.py`) both read this one column, so there is no second, looser gate elsewhere in the pipeline. This pipeline never imputes or approximates a missing value where the clock data doesn't actually exist; a partially-covered side is excluded outright rather than averaged in on an incomplete denominator.

**Coverage shares** (share of sides with every move's clock time recorded) differ substantially by format: classical shows meaningfully worse full-game coverage than rapid in both corpora — freestyle classical 71.6%, standard classical 65.7%, vs. freestyle rapid 98.5%, standard rapid 85.7%.

**Incomplete coverage is concentrated in specific events, not spread uniformly.** For example, in standard-classical's 2100-2199 band, 477 of 682 sides (69.9%) lack full coverage; of those, 451 (94.5%) come from a single event, the 36th Cracovia Open A, whose broadcast has substantial whole-game clock-capture gaps — a known limitation of that event's relay, not a pipeline defect. Most of the missing per-move readings in that band fall outside the opening window (6,305 of 9,877, 63.8%, after move 15), so a majority of these sides' opening-window data is intact, though a meaningful share (3,572, 36.2%) of the missing readings fall inside it too; it is specifically the whole-game denominator that complete-case's rule excludes them for.

### H1b Coverage and Partial-Data Robustness Check

H1b's headline direction (Chess960 opening time allocation exceeds standard's) holds under complete-case in all 17 testable bands (9 rating bands x 2 formats, minus one), significant at the 95% level in every one. The 18th cell, classical/standard's 2000-2099 band, is directionally consistent with the rest but is flagged `insufficient_n` (13 complete-case sides, below the `MIN_CELL_COUNT` floor of 20) and excluded from any reported range, per this pipeline's standard thin-cell convention.

**Partial-data method, as a robustness check.** `pipeline/analysis/coverage_sensitivity.py` recomputes OTR with the partial-coverage method — opening time / total time over whatever moves are tagged, regardless of whole-game coverage — and compares it band-by-band against complete-case. Direction (Chess960 > standard) and significance (95% CI excludes zero) hold in **all 17 testable bands** under both methods; zero sign flips between methods anywhere. Rapid is near-identical between methods in every band (both methods' CIs overlap heavily); classical shows a larger, consistent gap between methods in standard's bands specifically (complete-case running 3-11pp higher than partial-data, every classical/standard band), since standard-classical has the lowest full-coverage share of the four corpus x format strata and complete-case's exclusion has more partial sides to act on there. The Chess960-minus-standard difference itself is not sensitive to the choice between methods in either format — see the Results section below for the pooled numbers.

---

## C2 — Claim: Chess960 rewards understanding over memorization

**Claim:** Chess960 rewards genuine chess understanding rather than memorized preparation; players who succeed through memorization should be affected unevenly relative to those who succeed through understanding.

### Rating/Accuracy Gradient

This test asks whether accuracy is *more rating-dependent* in one format than the other — i.e. whether standard chess's accuracy is available more uniformly across skill levels (consistent with shared memorized theory) in a way Chess960's is not.

**Hypothesis:** Rating predicts opening ACPL more weakly in standard chess than in Chess960 — standard's opening accuracy is substantially theory-driven and thus available across a wide rating range, while Chess960 has no such theory, so accuracy should depend more directly on calculation skill, which scales more tightly with rating.

**Data and method:** `game_features.parquet` directly (`own_rating`, `opening_acpl`) — no band/gap-bin derivation, continuous rating variable. Per corpus per format: Pearson and Spearman correlation of rating vs. opening ACPL, plus each corpus's own OLS slope, **in absolute centipawns** (ACPL per 100 rating points), with a player-clustered 95% CI. The formal comparison is a pooled OLS interaction model, `opening_acpl ~ own_rating + corpus_standard + own_rating:corpus_standard` — the interaction coefficient and its p-value are the direct test of whether the two slopes differ, with the same player-clustered SE (one-way, by bare `player_name` — not corpus-prefixed, so a player who appears in both corpora is treated as a single cluster across them, matching C3's clustering convention; one-way is still sufficient here since there's no second player-role dimension to cross, unlike C4's White/Black two-way setup).

**Implementation:** `hypothesis_tests.test_rating_accuracy_gradient` (the function itself), wired into `h1_stage4_hypothesis_tests.py` alongside H1a/H1b/C2's variance test -> `rating_accuracy_gradient_results.csv`.

**Result — confirms the hypothesized direction (player-clustered CIs):**

| format | chess960 slope (ACPL/100 rating pts) | standard slope | interaction coef. | interaction p-value |
|---|---|---|---|---|
| classical | -2.59 [-2.86, -2.31] | -1.15 [-1.26, -1.03] | +0.0144 | 9.88e-23 |
| rapid | -3.33 [-3.73, -2.94] | -1.29 [-1.39, -1.19] | +0.0204 | 1.98e-23 |

The slopes above are stated **in absolute centipawns** (ACPL points per 100 rating points), not normalized to either corpus's own error level. On that absolute scale, rating predicts opening accuracy roughly 2.3-2.6x more steeply in Chess960 than in standard chess, in both time controls, with a player-clustered interaction term still significant at p<1e-22 in both (point estimates are unchanged from clustering — only the CI widens; the non-clustered p-values were 1.1e-49/6.8e-78). Pearson r: chess960 -0.36/-0.32 (classical/rapid) vs. standard -0.34/-0.27; n: chess960 2,568/4,317, standard 7,884/13,606.

### Rating/Accuracy Gradient — Leave-One-Tournament-Out Robustness

The interaction coefficient stays positive and significant under exclusion of any single tournament, in both formats (player-clustered, full sweep: `robustness.py::loto_gradient()` -> `loto_gradient.csv`, 30 exclusions classical, 80 rapid): classical ranges **0.01407-0.01527** (min excluding the 2025 Grenke freestyle event, max excluding 36th Cracovia Open A), p-value **5.0e-24 to 5.3e-14**; rapid ranges **0.01865-0.02184** (min excluding Weissenhaus Play-in Swiss, max excluding Las Vegas Play-in Swiss), p-value **8.5e-25 to 1.9e-15**. No exclusion in either format comes remotely close to flipping the sign or crossing p=0.05 — the steeper-in-Chess960 gradient is not driven by any single tournament.

### Within-Rating-Band Variance

**Hypothesis:** Within-rating-band variance of opening ACPL is greater in Chess960 than in standard chess — if some players in a band were winning mainly through memorized theory, removing that theory should cause similarly-rated players to separate in performance, rather than shift uniformly together.

**Band/gap assignment:** Same as C1 (two rows per game, own rating, signed gap) — this is a per-player variance measure.

**Test:** within-band standard deviation of opening ACPL, Chess960 vs. standard, compared via Brown–Forsythe (median-centred Levene) test for variance equality.

**Why not a moderator-based test:** Testing C2 directly via proxies for "reliance on memorization" (opening entropy, book depth, book agreement rate) would be circular — any such proxy is definitionally entangled with the opening-theory elimination already tested in C1, since "how book-reliant was this player" and "how much do they lose when book disappears" are measuring the same underlying fact from two angles. The variance test instead measures a *consequence* of C2 without requiring an independent, non-circular measure of memorization-reliance.

**Implementation.** C2 shares Stage 1-3 (`per_move_data.parquet`, `game_features.parquet`, `banded_h1_{corpus}_{format}.parquet`) with C1 above — `test_c2_variance` groups those same shared-grid rows by (format, band), ignoring gap_bin, rather than deriving its own band grid — see the shared-conventions note above on why C2's convention differs from C4's.

**Result.** Freestyle's opening-ACPL SD is **larger in absolute centipawns in every one of the 18 (format x band) cells**, both classical and rapid, across the full 2000-2800+ rating range — not normalized to either corpus's own mean error: **SD ratio 1.71x-3.02x** (variance ratio 2.9x-9.1x), with two classical bands under 2x SD ratio (2100-2199: 1.92x, 2200-2299: 1.71x, the weakest). The Brown–Forsythe test is significant in all 17 testable bands, but only **15 of 17 clear p<0.0001** — two miss it: classical 2000-2099 (p=0.0039, the weakest by p-value) and classical 2800+ (p=0.00061). All 17 remain significant at the much looser p<0.004 threshold. (Rapid 2800+ is a single-player band — see the player-clustered supplement below — and is not tested; its own Brown–Forsythe p-value, p=0.00035, is not counted toward these totals.) No `insufficient_n` flags — every cell clears the floor for both corpora. Representative rows (`c2_results.csv`):

| format | band | sd_freestyle | sd_standard | n_freestyle | n_standard | p_value |
|---|---|---|---|---|---|---|
| classical | 2100-2199 | 19.00 | 9.90 | 343 | 682 | <1e-4 |
| classical | 2600-2699 | 9.65 | 4.44 | 390 | 2,723 | <1e-4 |
| rapid | 2200-2299 | 30.81 | 10.21 | 464 | 1,527 | <1e-4 |
| rapid | 2700-2799 | 13.14 | 5.22 | 549 | 880 | <1e-4 |

**Player-clustered supplement.** Levene's/Brown-Forsythe's test has no natural clustered variant (it's a test on dispersion, not a mean); as a player-clustered check, `sd_diff` (freestyle SD minus standard SD) carries its own player-block bootstrap CI, each corpus's SD resampled by player independently (`h1_stage4_hypothesis_tests.py` -> `c2_results.csv`'s `sd_diff`/`sd_diff_ci_lower`/`sd_diff_ci_upper` columns). The CI excludes zero in all 17 testable bands, agreeing with the row-level Brown-Forsythe result above — **rapid 2800+ is a single-player band** (one side has only one distinct player contributing opening-ACPL rows), so `cluster_bootstrap_ci` has no second cluster to resample and returns no CI there; its row-level Brown-Forsythe result (17/17 testable bands, see above) is unaffected, since that test doesn't use player clustering.

### C2 — Leave-One-Tournament-Out Robustness

The core direction (Chess960 variance exceeds standard's) holds under exclusion of any single tournament, in every one of all 18 (format, band) cells — the SD ordering never flips anywhere (full sweep: `robustness.py::loto_c2()` -> `loto_c2.csv`, which checks `sd_freestyle > sd_standard` per exclusion alongside the p-value range).

One band's SIGNIFICANCE, specifically, does not survive exclusion of a single tournament: classical's 2000-2099 band's Brown–Forsythe test (baseline p=0.0039) becomes non-significant (p=0.1116) when 36th Cracovia Open A is excluded, which supplies 75.6% of that band's standard-side volume — a single large tournament dominating a thin band's volume. All other 17 bands remain significant under every tested exclusion; classical's 2800+ band shows elevated but not conclusion-threatening p-value variability (0.0006-0.0391, never crossing 0.05).

---

## C3 — Claim: Chess960 reduces draw rates

**Claim:** Chess960 produces more decisive, dynamic games and fewer draws than standard chess.

**Hypothesis:** Among closely matched players, Chess960 shows a lower draw rate than standard chess. Restricting to games within 100 Elo prevents differences in how mismatched each corpus's games are from driving the comparison.

**Method.** Draw rates are compared among games between players within 100 Elo of each other, adjusting for the players' average rating, since draw rates depend strongly on both rating gap and playing level. `gap = abs(WhiteElo - BlackElo) <= 100`; `avg_rating = (WhiteElo + BlackElo) / 2`. Only decisive-or-draw results are used (the unresolved `*` result code is dropped). ONE row per game — a draw is a single real-world fact regardless of which player's perspective is taken, so games are never double-counted by player perspective.

**Test.** Logistic regression, `draw ~ corpus + avg_rating`, average marginal effect (AME) of Chess960 vs. standard with a delta-method 95% CI, the delta method itself fed a two-way (White-player x Black-player) cluster-robust covariance (same Cameron-Gelbach-Miller construction as C4's) rather than the model's default — the primary estimate. A second specification, `draw ~ corpus + avg_rating + avg_rating^2`, checks whether a nonlinear rating effect changes the result.

**Implementation.** `pipeline/analysis/c3_close_game_drawrate.py` -> `c3_close_game_rates.csv` (raw rate + Wilson CI per corpus), `c3_close_game_avg_rating.csv` (mean/median average rating per corpus), `c3_close_game_ame.csv` (both model specifications), `c3_close_game_loto_summary.csv` + `c3_close_game_loto_detail.csv` (leave-one-tournament-out), `c3_close_game_source_share.csv` (each corpus's largest single source tournament's share of its close-game pool).

**Game-count disclosure.** C3/C4 (this section onward) run on `extract_scalars`'s output filtered to decisive-or-draw results only (dropping the unresolved `*` result code) — **3,434 Chess960 / 10,729 standard classical+rapid games combined**, not the 3,445/10,746 the H1a/H1b/C2 (including gradient) pipeline reports (that pipeline doesn't apply this result filter). Neither figure is the fully unfiltered manifest total (17,177 games across both corpora, before the broadcast-anomaly/Elo-floor/ forfeit exclusions both pipelines apply). The 28-game difference between the two post-exclusion totals (11 Chess960, 17 standard) is the unresolved-result count across all four `(corpus, format)` scalars files. Restricting further to `gap <= 100` leaves far fewer games than this base population — see the C3 rates below.

**Exclusion funnel** (full detail in each `(corpus, format)`'s `{corpus}_{format}_scalars_audit_summary.csv`), 17,177 raw manifest games down to 14,191 analysed:

| exclusion reason | games dropped |
|---|---|
| Elo floor (either player < 2000) | 2,244 |
| zero-ply (no real moves) | 711 |
| unplayed forfeit | 29 |
| Elo unparseable | 1 |
| missing FEN | 1 |
| **total excluded** | **2,986** |

17,177 - 2,986 = 14,191.

**Result — raw rates.**

| format | corpus | n | draws | draw rate | 95% CI |
|---|---|---|---|---|---|
| classical | Chess960 | 134 | 65 | 48.5% | [40.2%, 56.9%] |
| classical | standard | 2,103 | 1,237 | 58.8% | [56.7%, 60.9%] |
| rapid | Chess960 | 924 | 224 | 24.2% | [21.6%, 27.1%] |
| rapid | standard | 1,881 | 740 | 39.3% | [37.2%, 41.6%] |

Raw (unadjusted) Chess960-minus-standard difference: classical -10.3 points, rapid -15.1 points.

Average rating differs substantially between corpora within this close-gap subset, in both formats — mean / median: classical Chess960 2671.2 / 2692.3 vs. standard 2584.8 / 2633.5; rapid Chess960 2543.1 / 2594.3 vs. standard 2493.2 / 2502.0. Chess960's close games skew to notably stronger players than standard's in this subset — exactly the confound the rating-adjusted model below controls for.

**Result — rating-adjusted estimate (primary, two-way player-clustered SEs).** Average marginal effect of Chess960 vs. standard, `draw ~ corpus + avg_rating`: classical **-13.07 percentage points** (classical Chess960: 134 games from 5 tournaments) (95% CI [-21.87, -4.28], n=2,237); rapid **-17.66 percentage points** (95% CI [-22.02, -13.29], n=2,805). Both exclude zero. Adding a quadratic rating term barely moves either estimate — classical -12.10pp (95% CI [-20.67, -3.53]); rapid -17.81pp (95% CI [-22.25, -13.38]) — so the linear specification is not masking a nonlinear rating effect. (Point estimates are unchanged from the model's own non-clustered SE; only the CI widens slightly under two-way clustering — both results stay comfortably significant either way.)

### C3 — Leave-One-Tournament-Out Robustness

Refitting the primary two-way player-clustered close-game model's estimate excluding each tournament in turn: classical (30 exclusions) ranges from **-15.84pp** (excluding the 2025 Grenke Chess Festival) to **-10.71pp** (excluding `ParisKO_90+30.pgn`); rapid (79 exclusions — far more than classical's 30, since rapid draws on many more distinct source tournaments in both corpora: Chess960's rapid pool alone spans 38 separate Play-in Swiss/KO stage files and online events, versus 5 for classical, and standard's rapid pool spans 42 events versus 25 for classical) ranges from **-18.59pp** (excluding the 6th Internationales Schach960 Festival) to **-16.38pp** (excluding `ParisPlayinSwiss_10+2.pgn`). **Every CI excludes zero under every single-tournament exclusion, in both formats** — closest: classical excluding `weissenhausKO.pgn`, CI [-20.68, -1.57]; rapid excluding `ParisPlayinSwiss_10+2.pgn`, CI [-21.12, -11.63].

Each corpus's close-game pool draws on multiple source tournaments, none of which supplies the entire sample: the largest single tournament contributes 34.3% of Chess960's classical close games (2026 Grenke Freestyle Open, 46/134), 22.2% of standard's classical close games (FIDE Grand Swiss 2025, 466/2,103), 18.5% of Chess960's rapid close games (Weissenhaus Play-in Swiss, 171/924), and 11.7% of standard's rapid close games (FIDE World Rapid Team Matches 1-10, 221/1,881).

### Outcome Volatility

A second framing of the same draw-rate result, by rating-gap bin rather than the close-game (|gap|<=100) restriction above. For the favorite's score (win=1, draw=0.5, loss=0), the per-game variance is `Var = w + d/4 - (w + d/2)^2`, where `w` is the favorite win rate and `d` the draw rate. **This is mathematically equivalent to the draw-rate result at a fixed expected score**: with the expected score `m = w + d/2` held fixed, `Var = m(1-m) - d/4`, so fewer draws means higher variance — not an independent finding, a restatement of C3's result on the outcome-variance scale.

**Method.** Per (format, gap_bin) — the same shared 0-100/101-250/251+ bins C4 uses — `w` and `d` computed for each corpus, `Var` from the formula above, and the Chess960/standard ratio with a two-way (favorite-player x underdog-player) cluster-bootstrap 95% CI and a leave-one-tournament-out range for the ratio (`pipeline/analysis/volatility.py::outcome_volatility` -> `outcome_volatility.csv`).

**Result.** The ratio exceeds 1 (Chess960 more volatile) in all six cells: classical 0-100 1.17 [0.80, 1.52], 101-250 1.12 [0.92, 1.33], 251+ 1.31 [0.80, 2.24]; rapid 0-100 1.24 [1.12, 1.38], 101-250 1.22 [1.08, 1.36], 251+ 1.31 [0.96, 1.68]. The CI excludes 1 only in rapid's 0-100 and 101-250 bins; it includes 1 in classical's three bins and rapid's 251+, where either a thin cell (chess960 n=134 at classical 0-100, standard n=246 at classical 251+) or a wider spread at the largest gaps (both 251+ bins) widens the bootstrap CI enough to not exclude parity. LOTO ranges stay on the same side of 1 as the baseline point estimate in every cell.

---

## C4 — Claim: Between closely matched players, the lower-rated player wins more often in Chess960

**Claim:** between closely matched players (within 100 Elo), the lower-rated player wins more often in Chess960 than in standard chess.

**Method.** Same sample as C3: games with `|white_elo - black_elo| <= 100` (unsigned gap), decisive-or-draw results only. The claim uses the same `|gap| <= 100` sample as C3, where the lower-rated player is clearly identified. Equal-rated games are additionally dropped here, since "the underdog" is undefined with no gap at all — 0 Chess960 / 9 standard classical games, 7 Chess960 / 15 standard rapid games. Per format, a logistic model

`underdog_win ~ corpus + avg_rating + abs_gap`

(`avg_rating = (white_elo + black_elo) / 2`, `abs_gap = |white_elo - black_elo|`), with the Chess960-minus-standard average marginal effect (AME) of corpus and its delta-method 95% CI — two-way (White-player x Black-player, bare player names) cluster-robust SEs substituted into the delta method, the same Cameron-Gelbach-Miller construction (`cov_cluster_2groups`) C3's AME uses. `favourite_win` is fit the same way, for context. Underdog win is primary and additionally gets a leave-one-tournament-out sweep: every tournament present in either corpus excluded in turn, the AME refit each time, tracking whether the CI excludes zero under every exclusion.

Produced by `pipeline/analysis/c5_upset_tests.py` -> `c5_upset_tests.csv`.

**Results.**

| format | n (chess960/standard) | underdog-win AME | 95% CI | sig? | favorite-win AME | 95% CI | sig? | underdog-win LOTO range | sig. under every exclusion? |
|---|---|---|---|---|---|---|---|---|---|
| classical | 134 / 2,094 | +1.6pp | [-4.0, +7.2] | No | +10.6pp | [+2.8, +18.4] | Yes | [+0.8, +3.7]pp | No |
| rapid | 917 / 1,866 | +6.7pp | [+3.3, +10.1] | **Yes** | +10.6pp | [+6.8, +14.3] | Yes | [+5.2, +8.0]pp | **Yes** |

(AME coded Chess960-minus-standard; tournament counts from `c5_upset_tests.csv`'s `chess960_n_tournaments`/`standard_n_tournaments` columns: classical 134 Chess960 games from 5 tournaments, 2,094 standard games from 25; rapid 917 Chess960 games from 37 tournaments, 1,866 standard games from 42.) Raw (unadjusted) shares, for reference: classical underdog-win 14.9% (Chess960) vs. 15.0% (standard), draw 48.5% vs. 58.8%, favorite-win 36.6% vs. 26.1%; rapid underdog-win 32.2% vs. 26.7%, draw 24.2% vs. 39.5%, favorite-win 43.6% vs. 33.8%.

**Underdog outcome composition (raw shares; `c5_upset_tests.csv`'s `chess960_underdog_decisive_share`/`standard_underdog_decisive_share` and `chess960_underdog_score`/`standard_underdog_score` columns).** Alongside the underdog-win AME above, the underdog's share of decisive games (wins among decisive results only) and the underdog's score (wins + ½ draws), Chess960 vs. standard:

| format | underdog share of decisive games | underdog score (wins + ½ draws) |
|---|---|---|
| classical | 29.0% (Chess960) / 36.5% (standard) | 39.2% (Chess960) / 44.5% (standard) |
| rapid | 42.4% (Chess960) / 44.1% (standard) | 44.3% (Chess960) / 46.5% (standard) |

**Supported in rapid as a consequence of fewer draws: both players win more often; robust to excluding any single tournament. Not supported in classical**, where both the baseline CI and every LOTO exclusion include zero. The underdog's share of decisive games and average score do not rise; the extra underdog wins come from fewer draws.

**Outcome shares by rating gap (descriptive; Figure 2).** The sample above is restricted to `|gap| <= 100` to keep "underdog" well-defined at a consistent rating distance; it is not the full rating-gap range. For descriptive context only — **no significance test on the 101-250 or 251+ bins**, since the claim itself is scoped to `|gap| <= 100` — here is the same underdog-win/draw/favorite-win breakdown across the full unsigned-gap range C4's figure uses (`pipeline/analysis/ c5_bin_table.py` -> `c5_outcomes.csv`):

| format | gap_bin | chess960 underdog/draw/favorite | standard underdog/draw/favorite |
|---|---|---|---|
| classical | 0-100 | 14.9% / 48.5% / 36.6% | 15.0% / 58.8% / 26.1% |
| classical | 101-250 | 14.4% / 30.7% / 54.9% | 13.1% / 43.2% / 43.8% |
| classical | 251+ | 6.5% / 14.9% / 78.5% | 2.4% / 23.6% / 74.0% |
| rapid | 0-100 | 32.2% / 24.2% / 43.6% | 26.7% / 39.5% / 33.8% |
| rapid | 101-250 | 27.2% / 19.2% / 53.5% | 19.3% / 29.1% / 51.6% |
| rapid | 251+ | 17.0% / 9.2% / 73.9% | 10.6% / 16.9% / 72.5% |

The pattern at larger gaps (Chess960 underdogs winning more often at 101-250 and 251+ too) is visible here but **is not part of this claim** and carries no formal test in this document.

**Context: rating and results.** Rating predicts results about as well in Chess960 as in standard chess: at a 100-point edge the stronger player scores 58.7% vs 60.3% in rapid (colour-neutral) and a similar amount in classical (62.7% vs. 61.4%). The small rapid difference is not robust to single-tournament exclusion. (`c4_elo_scale.csv`, `c4_codings.csv`; full model detail in "Supplementary: predictability models" below.)

---

## Matched/Weighted Robustness Check

**Question:** is H1a or the rating-accuracy-gradient interaction an artifact of a rating-distribution imbalance between the hand-selected standard-chess corpus and the Chess960 corpus, rather than a genuine format effect? This check is scoped to that one imbalance — `own_rating` — and does not claim the two corpora are comparable on any other dimension, or that composition differences between them are otherwise eliminated; see "What this doesn't adjust for" below.

**Covariate balance (diagnostic, run first).** Per format, comparing Chess960 vs. standard on `own_rating` (Cohen's d): classical d=−0.404, rapid d=+0.242 — both exceed the 0.1 imbalance threshold. `own_rating` is the one covariate this check addresses.

**Method:** inverse-probability weighting, ATT-style. Propensity model `is_chess960 ~ own_rating`, fit separately per format on the full corpus (`game_features.parquet`, no source_type restriction — source_type reflects corpus-construction happenstance, not a skill difference, and is not treated as a matching covariate). Chess960 rows keep weight 1; standard rows are weighted by the odds of being Chess960 given `own_rating`, reweighting the standard sample toward Chess960's rating distribution.

**H1a re-run, original vs. IPW-weighted** (`pipeline/analysis/matching.py`). The IPW-weighted standard-corpus mean `opening_acpl` is close to the original unweighted mean in most bands, both formats: the largest shift is **0.88cp** (classical 2000-2099, the thinnest band, n=41 standard rows), followed by **0.34cp** (classical 2800+, n=46 — also a thin band). Every other band shows a shift under 0.31cp, and the direction is not systematic (both positive and negative shifts occur). No shift is large enough relative to H1a's between-corpus gaps (multiple cp, see H1a's own result) to change which corpus has higher opening ACPL in any band.

**Rating-accuracy-gradient interaction coefficient, original vs. IPW-weighted (player-clustered SE on the weighted fit, one-way, bare `player_name` — the same convention the baseline gradient test (C2's "Rating/Accuracy Gradient" section, above) uses; IPW weighting induces heteroskedasticity on top of the within-player correlation the clustering already accounts for):**

| format | original coef. (p, player-clustered) | IPW-weighted coef. (p, player-clustered) | change |
|---|---|---|---|
| classical | 0.01440 (9.88e-23) | 0.01398 (1.7e-20) | −3.0%, still p<1e-19 |
| rapid | 0.02045 (1.98e-23) | 0.02074 (2.7e-24) | +1.4%, still p<1e-23 |

**Result: barely moves under reweighting.** Reweighting the standard corpus to match Chess960's `own_rating` distribution changes neither finding's magnitude nor significance — both move by 1-3%, remain overwhelmingly significant even under player-clustered SEs. This rules out a rating-distribution imbalance as the driver of H1a or the rating-accuracy-gradient interaction; it is not evidence that the corpora are comparable on any other dimension.

**Colour** is balanced by design, not by this check: every game contributes one White row and one Black row to every player-side analysis in this document (H1a, H1b, C2 — including the rating-accuracy-gradient), so neither corpus can be systematically White- or Black-heavy relative to the other. (C3, C4, and C4's descriptive outcome-shares table are one-row-per-game, not player-side — see "Cross-cutting notes" below.)

**Player-level characteristics** (age, playing generation, individual style) are not addressed by IPW at all — reweighting on `own_rating` cannot control for who the players *are*, only their rating distribution. That question is addressed separately by the within-player comparison (see "Within-Player Paired Comparison" above), which compares each overlapping player against themselves across corpora and found every one of the 76 classical and 130 rapid players had higher opening ACPL in Chess960 — the strongest available evidence against a player-composition explanation, since it holds the player fixed entirely.

**What this doesn't adjust for.** IPW here reweights on `own_rating` only. It does not adjust for, and this document makes no claim about, event type, playing setting and year (see Data_Selection.md), or time-control sub-variant within a format — the last of these has too little overlap between the two corpora to support any adjustment.

---

## Cross-cutting notes

- **C1/C2 use per-player, signed-gap, two-rows-per-game assignment.** **Claim 4's test uses the same `|gap| <= 100` sample as C3, with no rating band at all** (see C4's section). Only C4's descriptive outcome-shares table (Figure 2) uses gap bins: one row per game, raw unsigned rating-gap bins 0–100 / 101–250 / 251+, no rating band. (C3 uses neither — it's not band-based at all, see C3's section.) These are not interchangeable — using the wrong convention for a given hypothesis either introduces pseudo-replication (doubling a per-player test) or loses the favored/underdog distinction (using unsigned gap for C1/C2). Claim 4 itself is computed by the `c5_*` scripts and outputs; the `c4_*` files hold the supplementary predictability models (see "Supplementary: predictability models" below).
- All bootstrap procedures use 5,000 iterations by default (configurable).
- See Data_Selection.md for which games and tournaments are eligible to enter these analyses in the first place.
- **Reproducibility.** Every leave-one-tournament-out, matched/weighted, ply-by-ply, and coverage-sensitivity check in this document is a committed script: `pipeline/analysis/robustness.py` (LOTO checks: H1a, C2 — including its Rating/Accuracy Gradient subsection, and the C4 supplementary predictability model's interaction coefficient — C3's own LOTO is built into `c3_close_game_drawrate.py` directly, and Claim 4's own LOTO (the underdog-win AME sweep) is built into `c5_upset_tests.py` directly, see each one's own section above), `pipeline/analysis/matching.py` (Cohen's d + IPW), `pipeline/analysis/ply_by_ply.py`, `pipeline/analysis/ coverage_sensitivity.py`, and (outside `pipeline/` on purpose — see `figure_scripts/README.md`) `figure_scripts/fig1_gradient.py` and `figure_scripts/fig2_outcomes.py`, which regenerate the two abstract figures from their tracked underlying CSVs (`rating_accuracy_gradient_results.csv`, `c5_outcomes.csv`) — reading the CSV directly is sufficient to verify a figure isn't misrepresenting its data, without needing to run the plotting code itself.
---

## Supplementary: predictability models

Model detail behind the "Context: rating and results" note in C4.

**Pooled interaction model.** Each game's outcome is White's score: 1 for a win, ½ for a draw, 0 for a loss. A fractional logit (binomial family, logit link) of score on `signed_gap + corpus_standard + signed_gap:corpus_standard`, fit once per format over the full-sample stratum, with standard errors two-way cluster-robust by White's player name AND Black's player name (Cameron-Gelbach-Miller: cov = cov_white + cov_black - cov_white_x_black, via statsmodels' `cov_cluster_2groups`) (`pipeline/analysis/c4_elo_scale.py` -> `c4_codings.csv`). The White-win and decisive-games-only codings (binary, not fractional) are reported alongside as sensitivity checks, using the same two-way-clustered pooled-interaction setup.

| format | interaction coef. | 95% CI | p-value | n (chess960/standard) |
|---|---|---|---|---|
| classical | -0.000505 | [-0.00111, 0.00010] | 0.101 | 1,274 / 3,933 |
| rapid | 0.000689 | [0.00014, 0.00124] | 0.0142 | 2,153 / 6,772 |

(Interaction coded standard-minus-Chess960 — positive means standard's gap predicts outcome more strongly.) In rapid, the White-win and decisive-only sensitivity codings agree in sign and significance pattern with the fractional-score model. In classical, both sensitivity codings flip sign relative to the fractional-score model's negative coefficient (White-win +0.00054, decisive-only +0.00149); decisive-only is additionally significant (p = 0.017) where the fractional-score model and White-win are not — see `c4_codings.csv` for all three codings' full numbers.

**Expected score on the Elo scale** (`c4_elo_scale.csv`): colour-neutral expected score for the stronger player, gap=100/200 — classical Chess960 62.7%/73.8% vs. standard 61.4%/71.7%; rapid Chess960 58.7%/66.9% vs. standard 60.3%/69.8%. For reference, White's own expected score at gap=0 (first-move advantage alone, no rating gap) is 51.5% in Chess960 classical, 55.4% in standard classical, 51.5% in Chess960 rapid, and 55.0% in standard rapid.

**Leave-one-tournament-out (fractional-score model).** Full sweep: `loto_c4_expected_score.py` -> `loto_c4_expected_score.csv` — refits the fractional-logit model above once per excluded tournament (30 exclusions classical, 80 rapid). Rapid: baseline coefficient 0.000689 (p = 0.0142); across exclusions, coefficient range [0.000446, 0.000854], p-value range [0.0043, 0.1667] — excluding `LasVegasPlayinSwiss_10+2.pgn` alone pushes p past 0.05. Classical: baseline coefficient -0.000505 (p = 0.1009); coefficient range [-0.000713, -0.000383], p-value range [0.0362, 0.3223] — excluding `25th ch-EUR Indiv 2025` pushes p below 0.05. Both strata's significance status changes under at least one single-tournament exclusion.

**Leave-one-tournament-out (White-win coding, sensitivity).** Full sweep: `robustness.py::loto_c4_interaction()` -> `loto_c4_interaction.csv`. Rapid: coefficient range [0.000742, 0.001246], p-value range [4.7e-05, 0.0234], never crossing 0.05. Classical: coefficient range [0.000252, 0.000970], p-value range [0.048, 0.630] — excluding 36th Cracovia Open A pushes p to 0.048. The two codings disagree on how stable rapid's LOTO range is (never crosses 0.05 under White-win coding, crosses it once under the fractional-score model).

**Classical, gap-restricted per-band check (fractional-score model).** Restricting to a common gap range (|gap|<=250, present in force in both corpora at four bands: 2400-2499, 2500-2599, 2600-2699, 2700-2799) and fitting the same two-way-clustered fractional-logit model per band (`pipeline/analysis/c4_gap_restricted_bands.py` -> `c4_interaction_by_band_classical.csv`; interaction coded standard-minus-Chess960) gives, per band — alongside each band's minimum detectable effect (MDE) at alpha=0.05/power=0.80:

| band | n (fs / std) | interaction coefficient | 95% CI | p-value | MDE | excludes zero? |
|---|---|---|---|---|---|---|
| 2400-2499 | 167 / 247 | -0.000396 | [-0.00236, 0.00156] | 0.692 | 0.00280 | No |
| 2500-2599 | 80 / 465 | 0.000883 | [-0.00170, 0.00346] | 0.502 | 0.00369 | No |
| 2600-2699 | 152 / 1511 | -0.001593 | [-0.00352, 0.00033] | 0.105 | 0.00275 | No |
| 2700-2799 | 169 / 776 | 0.000191 | [-0.00149, 0.00187] | 0.824 | 0.00240 | No |

The CI includes zero at all four bands. Every band's MDE (0.0024-0.0037) is several times the pooled classical interaction coefficient's own magnitude (0.000505) — these bands individually have enough power to detect an effect roughly 4.8-7.3x the pooled estimate's size, not the pooled estimate itself.


**Corpus note.** The rapid Chess960 corpus includes high-stakes online Play-in qualifiers (78% of rapid Chess960 games), selected as described in Data_Selection.md; all standard games are over-the-board. All results use the full corpus. Restricting rapid Chess960 to over-the-board games leaves every result in the same direction and with the same significance, with smaller rapid effects: the close-game draw-rate difference is −10.5 pp (95% CI −17.5 to −3.5) and the close-game underdog-win difference is +6.3 pp (95% CI +0.2 to +12.5). Reproduce with: `run_pipeline --stage extract_scalars --corpus freestyle --format rapid --source-type otb`, then `c3_close_game_drawrate.py --source-type otb` and `c5_upset_tests.py --source-type otb` (prints results, does not write CSVs — on-demand only, not part of the standard reporting flow).
