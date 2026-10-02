"""matching.py — covariate balance (Cohen's d) and IPW (inverse-probability
weighting) robustness check, reproducing METHODOLOGY.md's
"Matched/Weighted Robustness Check" section.

Question: does the hand-selected standard-chess comparison corpus differ
systematically from the Chess960 corpus on ``own_rating`` in a way that
could confound H1a / the rating-accuracy-gradient with corpus-composition
differences rather than genuine format effects?

Method: ATT-style IPW. Propensity model ``is_chess960 ~ own_rating``, fit
separately per format on the full corpus (``game_features.parquet``, no
source_type restriction). Chess960 rows keep weight 1; standard rows are
weighted by the odds of being Chess960 given ``own_rating``. The weighted
gradient fit (ipw_gradient) reports HC1 robust (sandwich) SEs, since IPW
weighting induces heteroskedasticity WLS's default SE ignores.

Run:  .venv-pipeline/bin/python -m pipeline.analysis.matching
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.config import PROCESSED_DIR, RESULTS_DIR

IMBALANCE_THRESHOLD = 0.1


def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    """Standardized mean difference (a − b), pooled SD."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    n_a, n_b = len(a), len(b)
    pooled_sd = np.sqrt(((n_a - 1) * a.var(ddof=1) + (n_b - 1) * b.var(ddof=1)) / (n_a + n_b - 2))
    return float((a.mean() - b.mean()) / pooled_sd)


def covariate_balance(game_features: pd.DataFrame, formats: tuple[str, ...] = ("classical", "rapid")) -> pd.DataFrame:
    """Cohen's d on own_rating, Chess960 vs standard, per format."""
    rows = []
    for fmt in formats:
        sub = game_features[game_features["format"] == fmt]
        fs = pd.to_numeric(sub.loc[sub.corpus == "freestyle", "own_rating"], errors="coerce").dropna()
        std = pd.to_numeric(sub.loc[sub.corpus == "standard", "own_rating"], errors="coerce").dropna()
        d = cohens_d(fs.to_numpy(), std.to_numpy())
        rows.append({
            "format": fmt, "cohens_d": d, "n_chess960": len(fs), "n_standard": len(std),
            "exceeds_0.1_threshold": abs(d) > IMBALANCE_THRESHOLD,
        })
    return pd.DataFrame(rows)


def _propensity_weights(sub: pd.DataFrame) -> pd.Series:
    """Fit is_chess960 ~ own_rating (logistic), return per-row IPW weight:
    Chess960 rows -> 1.0; standard rows -> odds(chess960 | own_rating)."""
    import statsmodels.api as sm

    sub = sub.copy()
    sub["is_chess960"] = (sub["corpus"] == "freestyle").astype(float)
    X = sm.add_constant(sub[["own_rating"]].astype(float))
    fit = sm.Logit(sub["is_chess960"].to_numpy(), X).fit(disp=0)
    p_chess960 = fit.predict(X)
    odds = p_chess960 / (1 - p_chess960)
    weight = np.where(sub["is_chess960"] == 1.0, 1.0, odds)
    return pd.Series(weight, index=sub.index)


def ipw_h1a_shift(formats: tuple[str, ...] = ("classical", "rapid")) -> pd.DataFrame:
    """Re-run H1a's per-band standard-corpus mean opening_acpl with IPW
    weights vs. the original unweighted mean. Reports max abs shift."""
    rows = []
    for fmt in formats:
        fs = pd.read_parquet(PROCESSED_DIR / f"banded_h1_freestyle_{fmt}.parquet")
        std = pd.read_parquet(PROCESSED_DIR / f"banded_h1_standard_{fmt}.parquet")
        combined = pd.concat([fs, std], ignore_index=True)
        weights = _propensity_weights(combined)

        for band, sub_std in std.groupby("band", observed=True):
            vals = pd.to_numeric(sub_std["opening_acpl"], errors="coerce")
            w = weights.loc[sub_std.index]
            ok = vals.notna()
            if ok.sum() < 5:
                continue
            unweighted = float(vals[ok].mean())
            weighted = float(np.average(vals[ok], weights=w[ok]))
            rows.append({
                "format": fmt, "band": band, "n": int(ok.sum()),
                "unweighted_mean": unweighted, "weighted_mean": weighted,
                "shift": weighted - unweighted,
            })
    out = pd.DataFrame(rows)
    return out


def ipw_gradient(formats: tuple[str, ...] = ("classical", "rapid")) -> pd.DataFrame:
    """Re-run the rating-accuracy-gradient's pooled-OLS interaction with IPW
    weights on standard rows (Chess960 weight 1), vs. the original unweighted
    fit — a check on whether the hand-selected standard corpus's rating
    imbalance against Chess960 (covariate_balance's Cohen's d) is driving
    the gradient interaction, not a claim about broader comparability.
    The weighted fit's SE is player-clustered (one-way, bare
    player_name — same convention the baseline gradient test uses),
    not just heteroskedasticity-robust, since IPW weighting induces
    heteroskedasticity on top of the within-player correlation the
    baseline fit already clusters for."""
    import statsmodels.api as sm

    from pipeline.analysis.hypothesis_tests import test_rating_accuracy_gradient

    gf = pd.read_parquet(PROCESSED_DIR / "game_features.parquet")
    rows = []
    for fmt in formats:
        sub = gf[gf["format"] == fmt]
        fs_all = sub[sub.corpus == "freestyle"]
        std_all = sub[sub.corpus == "standard"]

        orig = test_rating_accuracy_gradient(fs_all, std_all, fmt)
        orig_coef = float(orig["interaction_coefficient"].iloc[0])
        orig_p = float(orig["interaction_p_value"].iloc[0])

        prep = sub[["own_rating", "opening_acpl", "corpus", "player_name"]].copy()
        prep["own_rating"] = pd.to_numeric(prep["own_rating"], errors="coerce")
        prep["opening_acpl"] = pd.to_numeric(prep["opening_acpl"], errors="coerce")
        prep = prep.dropna(subset=["own_rating", "opening_acpl"])
        weights = _propensity_weights(prep.assign(format=fmt) if "format" not in prep else prep,)
        pooled = prep.assign(corpus_standard=(prep.corpus == "standard").astype(float))
        pooled["own_rating_x_standard"] = pooled["own_rating"] * pooled["corpus_standard"]
        X = sm.add_constant(pooled[["own_rating", "corpus_standard", "own_rating_x_standard"]].astype(float))
        w = weights.reindex(pooled.index).to_numpy()
        fit = sm.WLS(pooled["opening_acpl"].astype(float).to_numpy(), X, weights=w).fit(
            cov_type="cluster", cov_kwds={"groups": pooled["player_name"].to_numpy()}
        )
        ipw_coef = float(fit.params["own_rating_x_standard"])
        ipw_se = float(fit.bse["own_rating_x_standard"])
        ipw_p = float(fit.pvalues["own_rating_x_standard"])

        rows.append({
            "format": fmt,
            "original_coefficient": orig_coef, "original_p_value": orig_p,
            "ipw_coefficient": ipw_coef, "ipw_clustered_se": ipw_se, "ipw_p_value": ipw_p,
            "pct_change": (ipw_coef - orig_coef) / orig_coef * 100,
        })
    return pd.DataFrame(rows)


def main() -> dict[str, pd.DataFrame]:
    gf = pd.read_parquet(PROCESSED_DIR / "game_features.parquet")
    balance = covariate_balance(gf)
    h1a_shift = ipw_h1a_shift()
    gradient = ipw_gradient()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in [("covariate_balance", balance), ("ipw_h1a_shift", h1a_shift), ("ipw_gradient", gradient)]:
        path = RESULTS_DIR / f"matching_{name}.csv"
        df.to_csv(path, index=False)
        print(f"[matching] wrote {path.name} ({len(df)} rows)")
        print(df.to_string(index=False))
        print()

    print(f"H1a IPW: max abs shift = {h1a_shift['shift'].abs().max():.4f} cp")
    return {"covariate_balance": balance, "ipw_h1a_shift": h1a_shift, "ipw_gradient": gradient}


if __name__ == "__main__":
    main()
