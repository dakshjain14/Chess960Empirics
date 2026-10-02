"""robustness.py — leave-one-tournament-out checks for H1a, C2,
C4-interaction, and the rating-accuracy-gradient. C3's own
LOTO (a different check — close-game draw rate, not a banded test) lives in
``c3_close_game_drawrate.py``, not here.

Reproduces the LOTO ranges reported in METHODOLOGY.md's per-hypothesis
"Leave-One-Tournament-Out Robustness" subsections. Band/gap-bin edges are
already fixed (derived once, upstream, from the full corpus) — excluding one
tournament's games from a downstream test does not shift them, so each check
here simply filters the already-built banded/scalars frames by
``source_event`` and re-runs the existing ``hypothesis_tests`` /
``h1_stage4_hypothesis_tests`` function once per exclusion, never re-deriving
bands.

Run:  .venv-pipeline/bin/python -m pipeline.analysis.robustness
"""

from __future__ import annotations

import pandas as pd

from pipeline import run_pipeline as rp
from pipeline.analysis import h1_stage4_hypothesis_tests as h1s4
from pipeline.analysis import hypothesis_tests as ht
from pipeline.banding import band_gap_builder as bg
from pipeline.config import PROCESSED_DIR, RESULTS_DIR


def _events(*frames: pd.DataFrame) -> list[str]:
    ev: set[str] = set()
    for f in frames:
        ev |= set(f["source_event"].dropna().unique())
    return sorted(ev)


def _range_row(label: str, baseline: float, values: dict[str, float]) -> dict:
    """One summary row: baseline + [min, max] across all exclusions + which
    excluded event produced each extreme."""
    if not values:
        return {"cell": label, "baseline": baseline, "min": float("nan"),
                "min_excluding": None, "max": float("nan"), "max_excluding": None,
                "n_exclusions": 0}
    lo_ev = min(values, key=values.get)
    hi_ev = max(values, key=values.get)
    return {
        "cell": label, "baseline": baseline,
        "min": values[lo_ev], "min_excluding": lo_ev,
        "max": values[hi_ev], "max_excluding": hi_ev,
        "n_exclusions": len(values),
    }


# H1a — opening ACPL by (corpus, format, band)


def loto_h1a(cells: list[tuple[str, str, str]]) -> pd.DataFrame:
    """cells: list of (corpus, format, band) to check, e.g.
    ``("freestyle", "classical", "2000 to 2099")``."""
    banded_h1 = h1s4.load_banded_h1()
    rows = []
    for corpus, fmt, band in cells:
        sub_all = banded_h1[(banded_h1.corpus == corpus) & (banded_h1["format"] == fmt) & (banded_h1.band == band)]
        events = sorted(sub_all["source_event"].dropna().unique())
        baseline = sub_all["opening_acpl"].astype(float).mean()
        vals = {}
        for ev in events:
            sub = sub_all[sub_all["source_event"] != ev]
            if len(sub) < 5:
                continue
            vals[ev] = float(sub["opening_acpl"].astype(float).mean())
        row = _range_row(f"H1a {corpus}/{fmt}/{band}", float(baseline), vals)
        rows.append(row)
    return pd.DataFrame(rows)


# C2 — Brown-Forsythe-test significance by (format, band)


def loto_c2(cells: list[tuple[str, str]]) -> pd.DataFrame:
    """cells: list of (format, band), e.g. ("classical", "2000 to 2099").

    Alongside the p-value LOTO range (the returned DataFrame's row), also
    checks whether ``sd_freestyle > sd_standard`` (the direction reported in
    METHODOLOGY.md's C2 result) ever flips under any single-tournament
    exclusion — recorded per cell in ``sd_order_never_flips``."""
    banded_h1 = h1s4.load_banded_h1()
    rows = []
    for fmt, band in cells:
        sub_all = banded_h1[(banded_h1["format"] == fmt) & (banded_h1.band == band)]
        events = sorted(sub_all["source_event"].dropna().unique())

        def levene_p_and_sds(df: pd.DataFrame) -> tuple[float, float, float]:
            fs = pd.to_numeric(df.loc[df.corpus == "freestyle", "opening_acpl"], errors="coerce").dropna()
            st = pd.to_numeric(df.loc[df.corpus == "standard", "opening_acpl"], errors="coerce").dropna()
            if len(fs) < 2 or len(st) < 2:
                return float("nan"), float("nan"), float("nan")
            from scipy import stats
            p = float(stats.levene(fs.to_numpy(), st.to_numpy(), center="median")[1])
            return p, float(fs.std()), float(st.std())

        base_p, base_sd_fs, base_sd_st = levene_p_and_sds(sub_all)
        vals = {}
        sd_order_never_flips = True
        for ev in events:
            sub = sub_all[sub_all["source_event"] != ev]
            p, sd_fs, sd_st = levene_p_and_sds(sub)
            if pd.notna(sd_fs) and pd.notna(sd_st) and (sd_fs > sd_st) != (base_sd_fs > base_sd_st):
                sd_order_never_flips = False
            # volume share = this event's share of its OWN corpus's rows in
            # this cell (matches METHODOLOGY.md's convention), not
            # of the combined-corpus cell total
            ev_rows = sub_all[sub_all["source_event"] == ev]
            own_corpus = ev_rows["corpus"].iloc[0] if len(ev_rows) else None
            corpus_total = (sub_all["corpus"] == own_corpus).sum() if own_corpus else 0
            share = len(ev_rows) / corpus_total * 100 if corpus_total else 0
            vals[f"{ev} ({share:.1f}% of {own_corpus}-side cell volume)"] = p
        row = _range_row(f"C2 {fmt}/{band} p-value", base_p, vals)
        row["sd_order_never_flips"] = sd_order_never_flips
        rows.append(row)
    return pd.DataFrame(rows)


# C4-interaction — pooled interaction coefficient/p-value, per format


def loto_c4_interaction(formats: tuple[str, ...] = ("classical", "rapid")) -> pd.DataFrame:
    rows = []
    for fmt in formats:
        fs = pd.read_parquet(rp._paths("freestyle", fmt, None)["scalars"])
        std = pd.read_parquet(rp._paths("standard", fmt, None)["scalars"])
        fs_c34, std_c34 = bg.build_bands_c4c5(fs).data, bg.build_bands_c4c5(std).data
        events = _events(fs_c34, std_c34)

        base = ht.test_c4_interaction(fs_c34, std_c34)
        base_coef = float(base["interaction_coefficient"].iloc[0])
        base_p = float(base["interaction_p_value"].iloc[0])

        coefs, pvals = {}, {}
        for ev in events:
            fs_sub = fs_c34[fs_c34.source_event != ev]
            std_sub = std_c34[std_c34.source_event != ev]
            if len(fs_sub) < 20 or len(std_sub) < 20:
                continue
            out = ht.test_c4_interaction(fs_sub, std_sub)
            coefs[ev] = float(out["interaction_coefficient"].iloc[0])
            pvals[ev] = float(out["interaction_p_value"].iloc[0])

        rows.append(_range_row(f"C4-interaction {fmt} coefficient", base_coef, coefs))
        rows.append(_range_row(f"C4-interaction {fmt} p-value", base_p, pvals))
    return pd.DataFrame(rows)


# rating-accuracy-gradient — interaction coefficient/p-value, per format


def loto_gradient(formats: tuple[str, ...] = ("classical", "rapid")) -> pd.DataFrame:
    gf = pd.read_parquet(PROCESSED_DIR / "game_features.parquet")
    rows = []
    for fmt in formats:
        sub_all = gf[gf["format"] == fmt]
        fs_all = sub_all[sub_all.corpus == "freestyle"]
        std_all = sub_all[sub_all.corpus == "standard"]
        events = _events(fs_all, std_all)

        base = ht.test_rating_accuracy_gradient(fs_all, std_all, fmt)
        base_coef = float(base["interaction_coefficient"].iloc[0])
        base_p = float(base["interaction_p_value"].iloc[0])

        coefs, pvals = {}, {}
        for ev in events:
            fs_sub = fs_all[fs_all.source_event != ev]
            std_sub = std_all[std_all.source_event != ev]
            if len(fs_sub) < 20 or len(std_sub) < 20:
                continue
            out = ht.test_rating_accuracy_gradient(fs_sub, std_sub, fmt)
            coefs[ev] = float(out["interaction_coefficient"].iloc[0])
            pvals[ev] = float(out["interaction_p_value"].iloc[0])

        rows.append(_range_row(f"gradient {fmt} interaction coefficient", base_coef, coefs))
        rows.append(_range_row(f"gradient {fmt} interaction p-value", base_p, pvals))
    return pd.DataFrame(rows)


# driver


def _all_h1a_cells() -> list[tuple[str, str, str]]:
    """Every (corpus, format, band) combination actually present in the
    shared H1a/H1b grid — matches METHODOLOGY.md's "in every band, both
    formats" LOTO claim (9 bands x 2 corpora x 2 formats = 36 cells)."""
    banded_h1 = h1s4.load_banded_h1()
    combos = banded_h1[["corpus", "format", "band"]].drop_duplicates()
    return sorted(combos.itertuples(index=False, name=None))


def _all_c2_cells() -> list[tuple[str, str]]:
    """Every (format, band) combination in the shared H1a/H1b/C2 band grid
    (9 bands x 2 formats = 18 cells)."""
    banded_h1 = h1s4.load_banded_h1()
    combos = banded_h1[["format", "band"]].drop_duplicates()
    return sorted(combos.itertuples(index=False, name=None))


def main() -> dict[str, pd.DataFrame]:
    out = {
        "h1a": loto_h1a(_all_h1a_cells()),
        "c2": loto_c2(_all_c2_cells()),
        "c4_interaction": loto_c4_interaction(),
        "gradient": loto_gradient(),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in out.items():
        path = RESULTS_DIR / f"loto_{name}.csv"
        df.to_csv(path, index=False)
        print(f"[robustness] wrote {path.name} ({len(df)} rows)")
        print(df.to_string(index=False))
        print()
    return out


if __name__ == "__main__":
    main()
