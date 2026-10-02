"""C3: draw rate among close games (within 100 Elo), adjusted for average
rating via logistic regression, with two-way White/Black-player cluster-
robust SEs on the AME (see fit_ame). See METHODOLOGY.md's C3 section.
Writes the rate/AME/LOTO/share tables to data/results/c3_close_game_*.csv.

Run:  PYTHONPATH=. .venv-pipeline/bin/python pipeline/analysis/c3_close_game_drawrate.py
      PYTHONPATH=. .venv-pipeline/bin/python pipeline/analysis/c3_close_game_drawrate.py --source-type otb
          # on-demand OTB sensitivity variant (see METHODOLOGY.md's Corpus
          # note) — needs freestyle_{format}_otb_scalars.parquet to already
          # exist (run_pipeline.py --stage extract_scalars --source-type otb
          # first); prints results, does not write CSVs
"""
from __future__ import annotations

import pandas as pd
import statsmodels.formula.api as smf
import statsmodels.stats.sandwich_covariance as swc

from pipeline import run_pipeline as rp
from pipeline.analysis.hypothesis_tests import wilson_ci
from pipeline.config import FORMATS, RESULTS_DIR

_WHITE, _BLACK, _DRAW = "1-0", "0-1", "1/2-1/2"
GAP_MAX = 100.0


def load(corpus: str, fmt: str, source_type: str | None = None) -> pd.DataFrame:
    """source_type="otb" reads the _otb-suffixed scalars file (on-demand
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
    df["_gap"] = (we - be).abs()
    df["_avg_rating"] = (we + be) / 2.0
    df["_draw"] = (df["result"] == _DRAW).astype(float)
    df["_corpus"] = corpus
    return df[df["_gap"] <= GAP_MAX].reset_index(drop=True)


def fit_ame(df: pd.DataFrame, quadratic: bool):
    """AME of corpus=freestyle vs. standard, with two-way (White-player x
    Black-player) cluster-robust SEs substituted into the delta-method CI
    (same Cameron-Gelbach-Miller construction C4 uses) — or None if
    unfittable."""
    if df["_corpus"].nunique() < 2:
        return None
    formula = "_draw ~ C(_corpus, Treatment(reference='standard')) + _avg_rating"
    if quadratic:
        formula += " + I(_avg_rating**2)"
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
    row = [i for i in sf.index if "corpus" in i.lower()]
    if not row:
        return None
    r = sf.loc[row[0]]
    hi_col = "Cont. Int. Hi." if "Cont. Int. Hi." in r else sf.columns[-1]
    return float(r["dy/dx"]), float(r["Conf. Int. Low"]), float(r[hi_col]), len(df)


def main(source_type: str | None = None) -> dict[str, pd.DataFrame]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    rates_rows, avg_rating_rows, ame_rows = [], [], []
    loto_summary_rows, loto_detail_rows, share_rows = [], [], []

    for fmt in FORMATS:
        fs = load("freestyle", fmt, source_type)
        std = load("standard", fmt, source_type)
        pooled = pd.concat([fs, std], ignore_index=True)

        print(f"\n{'='*70}\nFORMAT: {fmt}  (|white_elo - black_elo| <= {GAP_MAX:.0f})\n{'='*70}")

        print("\n--- Raw draw rate ---")
        rates = {}
        for name, d in (("freestyle", fs), ("standard", std)):
            n = len(d)
            n_draws = int(d["_draw"].sum())
            rate = n_draws / n if n else float("nan")
            lo, hi = wilson_ci(n_draws, n)
            rates[name] = rate
            rates_rows.append({"format": fmt, "corpus": name, "n": n, "n_draws": n_draws,
                                "draw_rate": rate, "ci_lower": lo, "ci_upper": hi})
            print(f"{name:10s} n={n:5d}  draws={n_draws:5d}  rate={rate*100:5.2f}%  95% CI=[{lo*100:.2f}%, {hi*100:.2f}%]")
        diff = (rates["freestyle"] - rates["standard"]) * 100
        print(f"Chess960 - standard (raw, unadjusted): {diff:+.2f} percentage points")

        print("\n--- Average rating (mean of white_elo, black_elo) ---")
        for name, d in (("freestyle", fs), ("standard", std)):
            mean_r, median_r = d["_avg_rating"].mean(), d["_avg_rating"].median()
            avg_rating_rows.append({"format": fmt, "corpus": name, "mean_avg_rating": mean_r,
                                     "median_avg_rating": median_r})
            print(f"{name:10s} mean={mean_r:.1f}  median={median_r:.1f}")

        print("\n--- Logistic regression AME of Chess960 vs standard ---")
        for model_id, quad in ((1, False), (2, True)):
            r = fit_ame(pooled, quadratic=quad)
            label = "draw ~ corpus + avg_rating + avg_rating^2" if quad else "draw ~ corpus + avg_rating"
            if r is None:
                print(f"Model {model_id} ({label}): FIT FAILED")
                continue
            ame, lo, hi, n = r
            ame_rows.append({"format": fmt, "model": model_id, "formula": label,
                              "ame_pp": ame * 100, "ci_lower_pp": lo * 100, "ci_upper_pp": hi * 100, "n": n})
            print(f"Model {model_id} ({label}): AME={ame*100:+.2f}pp  95% CI=[{lo*100:+.2f}, {hi*100:+.2f}]  n={n}")

        print("\n--- Leave-one-tournament-out (model 1 estimate) ---")
        events = sorted(pooled["source_event"].dropna().unique())
        loto_results = []
        for ev in events:
            r = fit_ame(pooled[pooled["source_event"] != ev], quadratic=False)
            if r is not None:
                loto_results.append((ev, *r))
                loto_detail_rows.append({"format": fmt, "excluded_event": ev, "ame_pp": r[0] * 100,
                                          "ci_lower_pp": r[1] * 100, "ci_upper_pp": r[2] * 100, "n": r[3]})
        if loto_results:
            min_r = min(loto_results, key=lambda r: r[1])
            max_r = max(loto_results, key=lambda r: r[1])
            crosses = [r for r in loto_results if r[2] <= 0 <= r[3]]

            def dist_to_zero(r):
                lo, hi = r[2], r[3]
                return 0.0 if lo <= 0 <= hi else min(abs(lo), abs(hi))

            closest = min(loto_results, key=dist_to_zero)
            loto_summary_rows.append({
                "format": fmt, "n_exclusions": len(loto_results),
                "min_ame_pp": min_r[1] * 100, "min_excluding": min_r[0],
                "max_ame_pp": max_r[1] * 100, "max_excluding": max_r[0],
                "ci_crosses_zero_count": len(crosses),
                "ci_crosses_zero_events": "; ".join(r[0] for r in crosses),
                "closest_to_zero_excluding": closest[0],
                "closest_ci_lower_pp": closest[2] * 100, "closest_ci_upper_pp": closest[3] * 100,
            })
            print(f"n exclusions = {len(loto_results)}")
            print(f"min AME = {min_r[1]*100:+.2f}pp  (excluding '{min_r[0]}'), CI=[{min_r[2]*100:+.2f}, {min_r[3]*100:+.2f}]")
            print(f"max AME = {max_r[1]*100:+.2f}pp  (excluding '{max_r[0]}'), CI=[{max_r[2]*100:+.2f}, {max_r[3]*100:+.2f}]")
            print(f"CI crosses zero under {len(crosses)} exclusion(s): {[r[0] for r in crosses]}")
            print(f"closest to crossing zero: excluding '{closest[0]}', CI=[{closest[2]*100:+.2f}, {closest[3]*100:+.2f}]")
        else:
            print("no successful LOTO fits")

        print("\n--- Largest single tournament's share of each corpus's close-game pool ---")
        for name, d in (("freestyle", fs), ("standard", std)):
            counts = d["source_event"].value_counts()
            if len(counts) == 0:
                print(f"{name:10s} no games")
                continue
            top_event, top_n = counts.index[0], int(counts.iloc[0])
            share = top_n / len(d) * 100
            share_rows.append({"format": fmt, "corpus": name, "largest_event": top_event,
                                "largest_event_n": top_n, "corpus_n": len(d), "share_pct": share})
            print(f"{name:10s} largest = '{top_event}' ({top_n}/{len(d)} = {share:.1f}%)")

    out = {
        "c3_close_game_rates": pd.DataFrame(rates_rows),
        "c3_close_game_avg_rating": pd.DataFrame(avg_rating_rows),
        "c3_close_game_ame": pd.DataFrame(ame_rows),
        "c3_close_game_loto_summary": pd.DataFrame(loto_summary_rows),
        "c3_close_game_loto_detail": pd.DataFrame(loto_detail_rows),
        "c3_close_game_source_share": pd.DataFrame(share_rows),
    }
    print()
    if source_type is None:
        for name, df in out.items():
            path = RESULTS_DIR / f"{name}.csv"
            df.to_csv(path, index=False)
            print(f"[c3_close_game_drawrate] wrote {path.name} ({len(df)} rows)")
    else:
        print(f"[c3_close_game_drawrate] source_type={source_type!r}: on-demand "
              f"sensitivity run, not writing CSVs (see printed output above)")
    return out


def _build_parser():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--source-type", choices=("otb",), default=None)
    return p


if __name__ == "__main__":
    main(_build_parser().parse_args().source_type)
