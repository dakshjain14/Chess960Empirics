"""C4's primary test
(METHODOLOGY.md's C4 section, "Between closely matched players, the
lower-rated player wins more often in Chess960"): on the same sample
C3 uses (|gap| <= 100, decisive-or-draw results, equal-rated games
dropped since "the underdog" is undefined with no gap), per time
control, a logistic model

    underdog_win ~ corpus + avg_rating + abs_gap

with the Chess960-minus-standard average marginal effect (AME) of
corpus and its delta-method 95% CI — two-way (White-player x
Black-player, bare player names) cluster-robust SEs substituted into
the delta method, the same construction c3_close_game_drawrate.fit_ame
uses. favourite_win is fit the same way, for context. Additionally
gets a leave-one-tournament-out sweep on the underdog_win model: every
tournament present in either corpus excluded in turn and the AME
refit, tracking whether the CI excludes zero under every exclusion.

The descriptive per-(format, gap_bin) outcome-shares table across the
full 0-100/101-250/251+ range (the numbers behind Figure 2, no
significance test on the 101-250/251+ bins, since the claim itself is
scoped to |gap| <= 100 only) lives in `c5_bin_table.py` ->
`c5_outcomes.csv`, not here.

Run:  PYTHONPATH=. .venv-pipeline/bin/python pipeline/analysis/c5_upset_tests.py
      PYTHONPATH=. .venv-pipeline/bin/python pipeline/analysis/c5_upset_tests.py --source-type otb
          # on-demand OTB sensitivity variant (see METHODOLOGY.md's Corpus
          # note) — needs freestyle_{format}_otb_scalars.parquet to already
          # exist (run_pipeline.py --stage extract_scalars --source-type otb
          # first); prints results, does not write a CSV
"""
from __future__ import annotations

import pandas as pd
import statsmodels.formula.api as smf
import statsmodels.stats.sandwich_covariance as swc

from pipeline import run_pipeline as rp
from pipeline.config import RESULTS_DIR

_WHITE, _BLACK, _DRAW = "1-0", "0-1", "1/2-1/2"
GAP_MAX = 100.0


def load_close(corpus: str, fmt: str, source_type: str | None = None) -> tuple[pd.DataFrame, int, int]:
    """Same filters as c3_close_game_drawrate.load() (|gap| <= 100),
    plus dropping equal-rated games (undefined underdog). Returns
    (df, n_before_equal_rated_drop, n_equal_rated_dropped).
    source_type="otb" reads the _otb-suffixed scalars file (on-demand
    sensitivity variant, not part of the standard reporting flow) — falls
    back to the full-corpus file if no _otb variant exists (e.g. standard,
    which is already entirely OTB)."""
    path = rp._paths(corpus, fmt, source_type)["scalars"]
    if source_type == "otb" and not path.exists():
        path = rp._paths(corpus, fmt, None)["scalars"]
    df = pd.read_parquet(path)
    df = df[df["result"].isin([_WHITE, _BLACK, _DRAW])].copy()
    we = pd.to_numeric(df["white_elo"], errors="coerce")
    be = pd.to_numeric(df["black_elo"], errors="coerce")
    df = df[we.notna() & be.notna()].copy()
    we, be = we[df.index], be[df.index]
    df["abs_gap"] = (we - be).abs()
    df["avg_rating"] = (we + be) / 2.0
    df = df[df["abs_gap"] <= GAP_MAX].copy()
    n_before = len(df)
    equal = df["abs_gap"] == 0
    n_equal = int(equal.sum())
    df = df[~equal].copy()
    we2, be2 = we[df.index], be[df.index]
    lower_is_white = we2 < be2
    white_won = df["result"] == _WHITE
    black_won = df["result"] == _BLACK
    draw = df["result"] == _DRAW
    df["underdog_win"] = ((lower_is_white & white_won) | (~lower_is_white & black_won)).astype(float)
    df["favourite_win"] = ((~draw) & (~df["underdog_win"].astype(bool))).astype(float)
    df["draw"] = draw.astype(float)
    df["_corpus"] = corpus
    return df, n_before, n_equal


def fit_ame(df: pd.DataFrame, outcome_col: str):
    """Two-way bare-player-clustered delta-method AME of corpus, or None
    if unfittable."""
    if df["_corpus"].nunique() < 2:
        return None
    formula = f"{outcome_col} ~ C(_corpus, Treatment(reference='standard')) + avg_rating + abs_gap"
    try:
        fit = smf.logit(formula, data=df).fit(disp=0)
        g1 = df["white_player"].astype("category").cat.codes.to_numpy()
        g2 = df["black_player"].astype("category").cat.codes.to_numpy()
        cov2way, _, _ = swc.cov_cluster_2groups(fit, g1, g2)
        fit._results.cov_params_default = cov2way
    except Exception:
        return None
    margeff = fit.get_margeff(at="overall", method="dydx")
    sf = margeff.summary_frame()
    row = [i for i in sf.index if "_corpus" in i.lower()]
    if not row:
        return None
    r = sf.loc[row[0]]
    hi_col = "Cont. Int. Hi." if "Cont. Int. Hi." in r else sf.columns[-1]
    return float(r["dy/dx"]), float(r["Conf. Int. Low"]), float(r[hi_col])


def _loto(fs: pd.DataFrame, std: pd.DataFrame) -> dict:
    events = sorted(set(fs["source_event"].dropna().unique()) | set(std["source_event"].dropna().unique()))
    ames, excludes_zero_flags = [], []
    for ev in events:
        fs_ex, std_ex = fs[fs["source_event"] != ev], std[std["source_event"] != ev]
        if len(fs_ex) == len(fs) and len(std_ex) == len(std):
            continue
        if len(fs_ex) == 0 or len(std_ex) == 0:
            continue
        pooled_ex = pd.concat([fs_ex, std_ex], ignore_index=True)
        r = fit_ame(pooled_ex, "underdog_win")
        if r is None:
            continue
        ame, lo, hi = r
        ames.append(ame)
        excludes_zero_flags.append(bool(lo > 0 or hi < 0))
    if not ames:
        return {"loto_min": float("nan"), "loto_max": float("nan"), "loto_n_exclusions": 0,
                "significant_under_every_exclusion": None}
    return {
        "loto_min": min(ames), "loto_max": max(ames), "loto_n_exclusions": len(ames),
        "significant_under_every_exclusion": bool(all(excludes_zero_flags)),
    }


def primary_table(source_type: str | None = None) -> pd.DataFrame:
    """The claim's primary model: one row per format, |gap| <= 100."""
    rows = []
    for fmt in ["classical", "rapid"]:
        fs, fs_before, fs_equal = load_close("freestyle", fmt, source_type)
        std, std_before, std_equal = load_close("standard", fmt, source_type)
        pooled = pd.concat([fs, std], ignore_index=True)

        row = {
            "format": fmt,
            "chess960_n": len(fs), "standard_n": len(std),
            "chess960_n_tournaments": int(fs["source_event"].nunique()),
            "standard_n_tournaments": int(std["source_event"].nunique()),
            "chess960_n_equal_rated_dropped": fs_equal, "standard_n_equal_rated_dropped": std_equal,
            "chess960_underdog_win_rate": float(fs["underdog_win"].mean()),
            "standard_underdog_win_rate": float(std["underdog_win"].mean()),
            "chess960_draw_rate": float(fs["draw"].mean()),
            "standard_draw_rate": float(std["draw"].mean()),
            "chess960_favourite_win_rate": float(fs["favourite_win"].mean()),
            "standard_favourite_win_rate": float(std["favourite_win"].mean()),
        }
        for label, d in (("chess960", fs), ("standard", std)):
            underdog_rate = float(d["underdog_win"].mean())
            favourite_rate = float(d["favourite_win"].mean())
            draw_rate = float(d["draw"].mean())
            decisive_rate = underdog_rate + favourite_rate
            row[f"{label}_underdog_decisive_share"] = underdog_rate / decisive_rate if decisive_rate else float("nan")
            row[f"{label}_underdog_score"] = underdog_rate + 0.5 * draw_rate

        for label, col in (("underdog_win", "underdog_win"), ("favourite_win", "favourite_win")):
            r = fit_ame(pooled, col)
            if r is None:
                row[f"{label}_ame"] = float("nan")
                row[f"{label}_ame_ci_lower"] = float("nan")
                row[f"{label}_ame_ci_upper"] = float("nan")
                row[f"{label}_significant"] = None
            else:
                ame, lo, hi = r
                row[f"{label}_ame"] = ame
                row[f"{label}_ame_ci_lower"] = lo
                row[f"{label}_ame_ci_upper"] = hi
                row[f"{label}_significant"] = bool(lo > 0 or hi < 0)

        loto = _loto(fs, std)
        row["underdog_win_loto_min"] = loto["loto_min"]
        row["underdog_win_loto_max"] = loto["loto_max"]
        row["underdog_win_loto_n_exclusions"] = loto["loto_n_exclusions"]
        row["underdog_win_significant_under_every_loto_exclusion"] = loto["significant_under_every_exclusion"]
        rows.append(row)
    return pd.DataFrame(rows)


def main(source_type: str | None = None) -> pd.DataFrame:
    primary = primary_table(source_type)

    with pd.option_context("display.max_columns", None, "display.width", 240):
        print(primary.round(4).to_string(index=False))

    if source_type is None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        primary_path = RESULTS_DIR / "c5_upset_tests.csv"
        primary.to_csv(primary_path, index=False)
        print(f"\n[c5_upset_tests] wrote {primary_path.name} ({len(primary)} rows)")
    else:
        print(f"\n[c5_upset_tests] source_type={source_type!r}: on-demand "
              f"sensitivity run, not writing a CSV (see printed output above)")
    return primary


def _build_parser():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--source-type", choices=("otb",), default=None)
    return p


if __name__ == "__main__":
    main(_build_parser().parse_args().source_type)
