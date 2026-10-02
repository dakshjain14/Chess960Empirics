"""standard_rating_backfill.py — backfills missing WhiteElo/BlackElo tags in
Standard-corpus PGNs from the official FIDE monthly rating lists
(data/Rating_lists/FIDE_Rating_by_id_month/, the same source the Freestyle
enrichment uses).

Standard PGNs normally already carry an official FIDE Elo, but some
White/Black entries — concentrated in Rapid_OTB files — are missing it
entirely despite having a real FIDE ID whose rating the source scrape
didn't capture.

Before the automated backfill, every game is first checked against
data/Rating_lists/Standard_missing_fideid_candidates.xlsx — a manually
compiled list of players the automated FideId-based lookup can't resolve
on its own (see Data_Selection.md's "Manual corrections" section). A
matching row's player name tag and FideId are applied directly (so a
misspelled or FideId-less name tag is corrected before anything else
runs), and its rating is applied too if the row gives one (including an
explicit 0 for a confirmed-unrated player) — a row with a FideId but no
rating value is left for the automated lookup below to resolve, now that
it has a real id to search for. A candidate row that matches no game
anywhere in the corpus is printed as an ALERT.

Each game's WhiteFideId/BlackFideId is looked up in the (rating type, month)
XML named by Standard_Manifest.xlsx's `format`/`rating_month` columns —
month is read from the manifest, not derived from the PGN, since that
column was reviewed against TWIC's authoritative EventDate for events that
disagreed. A miss falls back to the *other* rating type's list for the same
month. A real FideId with no rating in either list is backfilled to "0"
(verified against ratings.fide.com as genuinely not-yet-rated, not a
download gap) — same convention as Freestyle. A side with no FideId at all
is left untouched and printed as an ALERT.

data/games/ is read-only; output mirrors it under
data/processed/Updated_Ratings/Standard_rating_updated/.
"""
import glob
import math
import os
import re
import xml.etree.ElementTree as ET

import openpyxl
import pandas as pd

from pipeline.config import DATA_GAMES_DIR, DATA_RATING_LISTS_DIR, STANDARD_MANIFEST_PATH, UPDATED_RATINGS_DIR

GAMES_ROOT = str(DATA_GAMES_DIR / 'Standard')
OUTPUT_ROOT = str(UPDATED_RATINGS_DIR / 'Standard_rating_updated')
MANIFEST_PATH = str(STANDARD_MANIFEST_PATH)
FIDE_RATING_ROOT = str(DATA_RATING_LISTS_DIR / 'FIDE_Rating_by_id_month')
MANUAL_CANDIDATES_PATH = str(DATA_RATING_LISTS_DIR / 'Standard_missing_fideid_candidates.xlsx')

GAME_SPLIT_RE = re.compile(r'\n\n(?=\[Event )')
TAG_RE = re.compile(r'^\[(\w+)\s+"(.*)"\]\s*$', re.MULTILINE)

RATING_TYPE_PREFIX = {'Classical': 'standard', 'Rapid': 'rapid'}
OTHER_TYPE = {'Classical': 'Rapid', 'Rapid': 'Classical'}
MONTH_ABBR = ['jan', 'feb', 'mar', 'apr', 'may', 'jun',
              'jul', 'aug', 'sep', 'oct', 'nov', 'dec']


MONTH_NAME_TO_IDX = {abbr: i + 1 for i, abbr in enumerate(MONTH_ABBR)}
RATING_MONTH_RE = re.compile(r'^([A-Za-z]{3})(\d{2})$')


def load_manifest_info():
    """basename -> (rating_type, (year, month_idx)) from Standard_Manifest.xlsx's
    format/rating_month columns - a row missing rating_month is skipped with
    an alert rather than falling back to computing a month from the PGN."""
    wb = openpyxl.load_workbook(MANIFEST_PATH, data_only=True)
    ws = wb.active
    headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    idx = {h: i for i, h in enumerate(headers) if h}
    if 'rating_month' not in idx:
        raise RuntimeError("Standard_Manifest.xlsx has no 'rating_month' column - "
                            "run the rating_month backfill/review step first")
    mapping = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        fp = row[idx['Filepath']]
        fmt = row[idx['format']]
        rating_month = row[idx['rating_month']]
        if not fp:
            continue
        basename = os.path.basename(fp)
        if not fmt or not rating_month:
            mapping[basename] = None  # present in manifest, but incomplete
            continue
        m = RATING_MONTH_RE.match(str(rating_month).strip())
        if not m or m.group(1).lower() not in MONTH_NAME_TO_IDX:
            mapping[basename] = None
            continue
        month_idx = MONTH_NAME_TO_IDX[m.group(1).lower()]
        yy = int(m.group(2))
        year = 2000 + yy
        mapping[basename] = (fmt.strip().capitalize(), (year, month_idx))
    return mapping


def _clean_str(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip()
    return s or None


def _clean_int_str(v):
    """float/int/str -> digit string, or None (handles NaN, blank, and the
    float formatting openpyxl/pandas gives numeric xlsx cells, e.g. 123.0)."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return str(int(float(s)))
    except ValueError:
        return None


def load_manual_candidates(path=MANUAL_CANDIDATES_PATH):
    """Reads Standard_missing_fideid_candidates.xlsx into a list of dicts:
    pgn_name, tournament_slug (lowercased, matched as a substring of the
    PGN's basename), fide_name, fide_id, fide_rating ("0" for a confirmed-
    unrated player, None if the rating is simply unknown - not the same
    thing), and a 'matched' flag main() sets as rows get applied, to ALERT
    on any row that matches no game anywhere."""
    df = pd.read_excel(path)
    rows = []
    for _, r in df.iterrows():
        pgn_name = _clean_str(r.get('PGN Name'))
        if not pgn_name:
            continue
        tournament = _clean_str(r.get('Tournament (file)'))
        rating_raw = r.get('FIDE Rating (that month)')
        fide_rating = None
        if rating_raw is not None and not (isinstance(rating_raw, float) and math.isnan(rating_raw)):
            fide_rating = '0' if float(rating_raw) == 0 else str(int(float(rating_raw)))
        rows.append({
            'pgn_name': pgn_name,
            'tournament_slug': tournament.lower() if tournament else None,
            'fide_name': _clean_str(r.get('Candidate FIDE Name')),
            'fide_id': _clean_int_str(r.get('FIDE Id')),
            'fide_rating': fide_rating,
            'matched': False,
        })
    return rows


def manual_overrides_for_file(basename, candidates):
    """Candidate rows whose tournament_slug is a substring of this file's
    basename (case-insensitive) - a row with no tournament_slug at all is
    never auto-matched, since player-name-only matching across the whole
    corpus risks colliding with an unrelated same-named player."""
    b = basename.lower()
    return [c for c in candidates if c['tournament_slug'] and c['tournament_slug'] in b]


def apply_manual_candidates(block, overrides):
    """Applies any override whose pgn_name matches this block's White or
    Black name tag: corrects/sets the name tag, FideId tag, and (if the
    row gives one) the Elo tag. Marks matched overrides in place. Returns
    (new_block, n_applied)."""
    tags = parse_tags(block)
    new_block = block
    n_applied = 0
    for color, name_key, fide_key, elo_key in (
        ('White', 'White', 'WhiteFideId', 'WhiteElo'),
        ('Black', 'Black', 'BlackFideId', 'BlackElo'),
    ):
        name = (tags.get(name_key) or '').strip()
        if not name:
            continue
        for ov in overrides:
            if ov['pgn_name'].lower() != name.lower():
                continue
            ov['matched'] = True
            if ov['fide_name']:
                new_block = set_tag(new_block, name_key, ov['fide_name'], (fide_key, name_key))
            if ov['fide_id']:
                new_block = set_tag(new_block, fide_key, ov['fide_id'], (name_key,))
            if ov['fide_rating'] is not None:
                new_block = set_tag(new_block, elo_key, ov['fide_rating'], (fide_key, name_key))
            n_applied += 1
            break  # one override per side per game
    return new_block, n_applied


def xml_path_for(rating_type, month_idx, year_2digit):
    prefix = RATING_TYPE_PREFIX[rating_type]
    abbr = MONTH_ABBR[month_idx - 1]
    return os.path.join(FIDE_RATING_ROOT, rating_type, f'{prefix}_{abbr}{year_2digit}frl_xml.xml')


def build_rating_index(xml_path, wanted_ids):
    """Stream-parse xml_path, returning {fideid: rating} for ids in wanted_ids."""
    result = {}
    remaining = set(wanted_ids)
    for event, elem in ET.iterparse(xml_path, events=('end',)):
        if elem.tag == 'player':
            fideid = elem.findtext('fideid', '').strip()
            if fideid in remaining:
                rating = elem.findtext('rating', '').strip()
                result[fideid] = rating
                remaining.discard(fideid)
            elem.clear()
    return result


def parse_tags(block):
    tags = {}
    for m in TAG_RE.finditer(block):
        tags.setdefault(m.group(1), m.group(2))
    return tags


def set_tag(block, tag, new_value, anchor_tags):
    """Set '[tag "new_value"]' in block: replaces an existing line if
    present, else inserts a new one right after the first anchor tag found
    (FideId, then the color's name tag) - same convention as
    pipeline/ingest/rating_update.py."""
    pattern = re.compile(r'^\[' + re.escape(tag) + r'\s+"(.*)"\]\s*$', re.MULTILINE)
    if pattern.search(block):
        return pattern.sub(lambda m: m.group(0).replace(m.group(1), new_value, 1), block, count=1)
    for anchor in anchor_tags:
        anchor_pattern = re.compile(r'^(\[' + re.escape(anchor) + r'\s+".*"\])\s*$', re.MULTILINE)
        m = anchor_pattern.search(block)
        if m:
            return block[:m.end()] + f'\n[{tag} "{new_value}"]' + block[m.end():]
    return block


def is_real_fide_id(fid):
    return fid.isdigit() and len(fid) > 0


def process_file(path, rtype, month_year, overrides=()):
    year, month_idx = month_year
    yy = f'{year % 100:02d}'
    xml_path = xml_path_for(rtype, month_idx, yy)
    fallback_xml_path = xml_path_for(OTHER_TYPE[rtype], month_idx, yy)

    with open(path, encoding='utf-8-sig') as f:
        content = f.read()
    blocks = [b for b in GAME_SPLIT_RE.split(content) if b.strip()]

    # manual candidates are applied first, so a game that was unresolvable
    # by FideId alone (no id, or a misspelled name tag) gets its name/id
    # corrected before the automated lookup below ever runs on it.
    n_manual = 0
    if overrides:
        patched = []
        for block in blocks:
            new_block, applied = apply_manual_candidates(block, overrides)
            n_manual += applied
            patched.append(new_block)
        blocks = patched

    # gather needed ids first, so each XML is parsed once
    needed = set()
    for block in blocks:
        tags = parse_tags(block)
        for elo_key, fide_key in (('WhiteElo', 'WhiteFideId'), ('BlackElo', 'BlackFideId')):
            if elo_key in tags:
                continue
            fid = tags.get(fide_key, '').strip()
            if is_real_fide_id(fid):
                needed.add(fid)

    if not needed:
        if n_manual:
            return {'blocks': blocks, 'content': content, 'n_filled': 0, 'n_fallback': 0,
                     'n_zeroed': 0, 'n_no_real_id': 0, 'n_manual': n_manual}
        return None  # nothing to backfill in this file

    index = build_rating_index(xml_path, needed) if os.path.exists(xml_path) else {}
    still_missing = needed - index.keys()
    fallback_index = (build_rating_index(fallback_xml_path, still_missing)
                       if still_missing and os.path.exists(fallback_xml_path) else {})

    n_filled = 0
    n_fallback = 0
    n_zeroed = 0
    n_no_real_id = 0
    out_blocks = []
    for i, block in enumerate(blocks, 1):
        tags = parse_tags(block)
        new_block = block
        for color, elo_key, fide_key in (('White', 'WhiteElo', 'WhiteFideId'),
                                          ('Black', 'BlackElo', 'BlackFideId')):
            if elo_key in tags:
                continue
            fid = tags.get(fide_key, '').strip()
            if not is_real_fide_id(fid):
                n_no_real_id += 1
                continue
            rating = index.get(fid) or fallback_index.get(fid)
            if not rating:
                # a real FideId with no rating in either type's list for this
                # month means genuinely not-yet-rated at that time (verified
                # against ratings.fide.com for a sample - our downloaded
                # monthly lists agree with FIDE's own site) - "0" per the
                # same "not rated" convention used for Freestyle.
                new_block = set_tag(new_block, elo_key, '0', (fide_key, color))
                n_zeroed += 1
                continue
            new_block = set_tag(new_block, elo_key, rating, (fide_key, color))
            n_filled += 1
            if fid not in index:
                n_fallback += 1
        out_blocks.append(new_block)

    return {
        'blocks': out_blocks, 'content': content,
        'n_filled': n_filled, 'n_fallback': n_fallback, 'n_zeroed': n_zeroed,
        'n_no_real_id': n_no_real_id, 'n_manual': n_manual,
    }


def main():
    info_map = load_manifest_info()
    candidates = load_manual_candidates()
    pgn_files = sorted(glob.glob(os.path.join(GAMES_ROOT, '**', '*.pgn'), recursive=True))
    print(f"found {len(pgn_files)} Standard PGN files on disk, {len(candidates)} manual candidate rows")

    for src_path in pgn_files:
        basename = os.path.basename(src_path)
        if basename not in info_map:
            print(f"ALERT: '{basename}' not referenced in Standard_Manifest.xlsx - skipping, no output written")
            continue
        info = info_map[basename]
        if info is None:
            print(f"ALERT: '{basename}' has no format or rating_month set in the manifest - skipping, no output written")
            continue
        rtype, start = info
        overrides = manual_overrides_for_file(basename, candidates)

        with open(src_path, encoding='utf-8-sig') as f:
            content = f.read()

        result = process_file(src_path, rtype, start, overrides)
        rel = os.path.relpath(src_path, GAMES_ROOT)
        dst_path = os.path.join(OUTPUT_ROOT, rel)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)

        if result is None:
            # nothing needed backfilling - still copy through unchanged so
            # every input file has a corresponding output file
            with open(dst_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"{basename}: no missing Elo tags -> {dst_path}")
            continue

        with open(dst_path, 'w', encoding='utf-8') as f:
            f.write('\n\n'.join(result['blocks']))
            if content.endswith('\n') and not result['blocks'][-1].endswith('\n'):
                f.write('\n')

        y, m = start
        msg = (f"{basename}: {rtype} {m:02d}/{y}, {result['n_filled']} Elo tags filled "
               f"({result['n_fallback']} via {OTHER_TYPE[rtype]} fallback) -> {dst_path}")
        if result['n_manual']:
            msg += f" - {result['n_manual']} sides patched from manual candidates"
        if result['n_zeroed']:
            msg += f" - {result['n_zeroed']} sides set to 0 (not rated that month)"
        if result['n_no_real_id']:
            msg += f" - {result['n_no_real_id']} sides had no usable FideId (left as-is)"
        print(msg)

    for c in candidates:
        if not c['matched']:
            print(f"ALERT: manual candidate row for '{c['pgn_name']}' "
                  f"(tournament '{c['tournament_slug']}') matched no game in any Standard PGN file")

    print("done")


if __name__ == '__main__':
    main()
