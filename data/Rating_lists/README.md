# data/Rating_lists/

Source data for the FIDE-rating correction/backfill stage
(`pipeline/ingest/rating_update.py`, `pipeline/ingest/standard_rating_backfill.py`)
that produces `data/processed/Updated_Ratings/`. This directory mixes two
things with very different provenance, reproducibility, and inclusion
status — see below.

## Two different kinds of content here

1. **`FIDE_Rating_by_id_month/{Classical,Rapid}/*.xml`** — official FIDE
   monthly rating lists, downloaded directly from FIDE. **Third-party data,
   excluded from this repo** (size — see below). Fully
   reconstructable by re-downloading from FIDE; instructions below.
2. **`Playing_lists_with_Fide_id/*.csv`, `Playing_lists_with_Rating/*.csv`,
   `Standard_missing_fideid_candidates.xlsx`** — this project's own compiled
   per-event roster files, read by `rating_update.py` for the Freestyle
   corpus. **Included in this repo** (tracked in version control) — not
   FIDE's redistributable data, and not reproducible from the public repo
   alone (see "Provenance" below — the lookup script that fills most of
   these columns is archived, not tracked), so they have to ship with it
   to be usable at all.

## Why the FIDE monthly lists are excluded

Size: the full set used for this study (Standard + Rapid, 18
months, January 2025 through June 2026 — the manifest's `rating_month`
span) is several GB uncompressed.


## How to obtain the identical FIDE source data

1. Go to FIDE's official ratings download page:
   **https://ratings.fide.com/download_lists.phtml**
2. For each month below, download that month's **Standard** and **Rapid**
   rating lists in **XML** format (FIDE publishes one archive per rating
   type per month; the site's own filename convention is used verbatim
   below).
3. Months used in this study (Standard + Rapid, both needed for every
   month): **Jan 2025 – Jun 2026** — 18 months, 36 files total.

### Expected file naming and layout

FIDE's own downloaded filename convention is `{type}_{mon}{yy}frl_xml.zip`
(e.g. `standard_apr25frl_xml.zip`, `rapid_jan25frl_xml.zip`) — `type` is
`standard` or `rapid`, `mon` is a lowercase 3-letter month abbreviation,
`yy` is the 2-digit year. Unzip each archive to its `.xml` file and place it
under:

```
data/Rating_lists/FIDE_Rating_by_id_month/
  Classical/
    standard_jan25frl_xml.xml
    ...
    standard_jun26frl_xml.xml
  Rapid/
    rapid_jan25frl_xml.xml
    ...
    rapid_jun26frl_xml.xml
```

Note the folder names are FIDE's rating-*type* labels as used by this
project's manifests (`Classical`/`Rapid`), not FIDE's own filename prefix
(`standard`/`rapid`) — `standard_*.xml` files go under `Classical/`,
`rapid_*.xml` files go under `Rapid/`. This exact path is read by
`pipeline/ingest/standard_rating_backfill.py`'s `FIDE_RATING_ROOT` lookup
(`{Classical,Rapid}/{standard,rapid}_{mon}{yy}frl_xml.xml`).

## Provenance of `Playing_lists_with_Fide_id/` and `Playing_lists_with_Rating/`

**The roster itself is manually compiled; the FIDE ID and rating columns
on top of it are scripted, by an archived script not part of the public
repo:**

- **Roster (player names).** Each CSV's header cites a specific source URL
  — mostly tournament pages on **chess-results.com**, some on chess.com
  event pages, one Lichess broadcast, one tournament's own site
  (`freestyle-chess.com`) — compiled by hand from those pages.
- **FIDE ID, `Month_for_rating`, `Rating_Type`, `Fide_Rating`, `Base Rating
  Type`.** All five columns are filled in from FIDE ID via each player's
  chess.com profile page's linked `ratings.fide.com/profile/<id>` link (for
  rosters that don't already carry it), `Fide_Rating` via a lookup against
  that row's `(Rating_Type, Month_for_rating)` FIDE monthly list
  (`FIDE_Rating_by_id_month/` above), with a same-month other-type fallback.

**Practical implication:** even with the FIDE monthly lists obtained per
the instructions above, `rating_update.py` cannot be run end-to-end from
raw source alone — it depends on these pre-compiled roster CSVs as input.
Reproducing the CSVs themselves needs both the manual roster-scrape step
and a rerun of the archived lookup script above; a newly-added Freestyle
event needs the same treatment before `rating_update.py` can write ratings
into its PGN. That's exactly why these files are included in the repo
rather than treated as regeneratable on demand.
