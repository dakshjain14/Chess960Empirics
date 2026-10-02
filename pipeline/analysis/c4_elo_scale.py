"""c4_elo_scale.py — C4 on the Elo expected-score scale (METHODOLOGY.md's C4
section). Primary model: fractional logit (binomial family, logit link) of
White's score (1 / 1/2 / 0) on signed rating gap, with a corpus term and a
gap x corpus interaction, fit once per run over the pooled two-corpus
stratum — the same pooled-interaction structure the white_win and
decisive_only sensitivity codings below use, just on a continuous [0,1]
response instead of a binary one. Standard
errors are two-way cluster-robust by White's player name AND Black's player
name (Cameron-Gelbach-Miller: cov = cov_white + cov_black - cov_white_x_black,
via statsmodels' ``cov_cluster_2groups``), so correlation from either player
appearing in multiple games is captured, not just White's.

Three codings are fit for every run, all with the same cluster-robust SEs:
  fractional_score  — the fractional-score model. score = 1/0.5/0, GLM(Binomial), logit link.
  white_win         — sensitivity. 1 if White won, 0 if draw or Black won.
  decisive_only     — sensitivity. Same as white_win, but draws dropped first.

Two runs: classical (freestyle vs standard), rapid (freestyle vs standard)
— the full corpus in each format, no playing-setting split.

Writes c4_codings.csv (coefficient/CI/p/n for both runs x 3 codings, plus a
plain-language "more predictable" note) and c4_elo_scale.csv (per-corpus
fitted slope; White's own expected score and the colour-neutral expected
score — (p(+gap) + 1 - p(-gap)) / 2, averaging over which side the
stronger player has — at gap=100/200; White's expected score alone at
gap=0; alongside Elo's own reference score at each gap).

Run:  PYTHONPATH=. .venv-pipeline/bin/python pipeline/analysis/c4_elo_scale.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.stats.sandwich_covariance as swc
from scipy import stats as spstats

from pipeline.config import PROCESSED_DIR, RESULTS_DIR

_WHITE, _BLACK, _DRAW = "1-0", "0-1", "1/2-1/2"


def _load(corpus: str, fmt: str) -> pd.DataFrame:
    return pd.read_parquet(PROCESSED_DIR / f"{corpus}_{fmt}_scalars.parquet")


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    """Decisive-or-draw games with numeric, non-equal Elo on both sides;
    adds signed_gap, score (1/0.5/0), white_win, decisive flag."""
    work = df[df["result"].isin([_WHITE, _BLACK, _DRAW])].copy()
    we = pd.to_numeric(work["white_elo"], errors="coerce")
    be = pd.to_numeric(work["black_elo"], errors="coerce")
    work = work[we.notna() & be.notna() & (we != be)].copy()
    we, be = we[work.index], be[work.index]
    work["signed_gap"] = we - be
    work["score"] = np.select(
        [work["result"] == _WHITE, work["result"] == _DRAW, work["result"] == _BLACK],
        [1.0, 0.5, 0.0],
    )
    work["white_win"] = (work["result"] == _WHITE).astype(float)
    work["decisive"] = work["result"] != _DRAW
    return work[["white_player", "black_player", "signed_gap", "score", "white_win", "decisive"]]


def _pooled(fs: pd.DataFrame, std: pd.DataFrame) -> pd.DataFrame:
    pooled = pd.concat(
        [fs.assign(corpus_standard=0.0), std.assign(corpus_standard=1.0)], ignore_index=True
    )
    pooled["signed_gap_x_standard"] = pooled["signed_gap"] * pooled["corpus_standard"]
    pooled["cluster_white"] = pooled["white_player"]
    pooled["cluster_black"] = pooled["black_player"]
    return pooled


class _TwoWayFit:
    """Minimal results-like wrapper: GLM point estimates (MLE) with a
    two-way (White player x Black player) cluster-robust covariance
    substituted in, Wald/normal inference on top of it."""

    def __init__(self, params: pd.Series, bse: pd.Series, names: list[str]):
        self.params = params
        self.bse = bse
        z = params / bse
        self.pvalues = pd.Series(2 * (1 - spstats.norm.cdf(np.abs(z))), index=names)
        lo = params - 1.959963984540054 * bse
        hi = params + 1.959963984540054 * bse
        self._ci = pd.DataFrame({0: lo, 1: hi}, index=names)

    def conf_int(self) -> pd.DataFrame:
        return self._ci


def _fit(pooled: pd.DataFrame, y_col: str) -> _TwoWayFit:
    X = sm.add_constant(pooled[["signed_gap", "corpus_standard", "signed_gap_x_standard"]].astype(float))
    y = pooled[y_col].to_numpy(float)
    model = sm.GLM(y, X, family=sm.families.Binomial())
    res = model.fit()  # MLE point estimates; covariance replaced below
    g1 = pooled["cluster_white"].astype("category").cat.codes.to_numpy()
    g2 = pooled["cluster_black"].astype("category").cat.codes.to_numpy()
    cov2way, _, _ = swc.cov_cluster_2groups(res, g1, g2)
    names = list(X.columns)
    params = pd.Series(res.params.to_numpy(), index=names)
    bse = pd.Series(np.sqrt(np.diag(cov2way)), index=names)
    fitted = _TwoWayFit(params, bse, names)
    fitted.predict = lambda df: res.predict(df[names])
    return fitted


def _more_predictable_note(coef: float, p: float, run_label: str) -> str:
    if p >= 0.05:
        return "no significant difference in predictability between formats"
    # interaction coded standard-minus-chess960: positive -> standard's gap
    # predicts outcome more strongly -> chess960 is LESS predictable there.
    less_predictable = "Chess960" if coef > 0 else "standard chess"
    return f"{less_predictable} is significantly less predictable by rating gap ({run_label})"


RUNS: list[tuple[str, str]] = [
    ("classical", "classical"),
    ("rapid", "rapid"),
]

CODINGS: list[tuple[str, str]] = [
    ("fractional_score", "score"),
    ("white_win", "white_win"),
    ("decisive_only", "white_win"),  # filtered to decisive() rows before fitting
]


def main() -> dict[str, pd.DataFrame]:
    code_rows = []
    scale_rows = []

    for run_label, fmt in RUNS:
        fs_raw = _load("freestyle", fmt)
        std_raw = _load("standard", fmt)

        fs = _prep(fs_raw)
        std = _prep(std_raw)

        for coding_name, y_col in CODINGS:
            fs_c, std_c = fs, std
            if coding_name == "decisive_only":
                fs_c = fs[fs["decisive"]]
                std_c = std[std["decisive"]]
            pooled = _pooled(fs_c, std_c)
            res = _fit(pooled, y_col)
            coef = float(res.params["signed_gap_x_standard"])
            ci = res.conf_int().loc["signed_gap_x_standard"]
            p = float(res.pvalues["signed_gap_x_standard"])
            code_rows.append({
                "run": run_label, "format": fmt, "coding": coding_name,
                "n_chess960": int((pooled["corpus_standard"] == 0).sum()),
                "n_standard": int((pooled["corpus_standard"] == 1).sum()),
                "interaction_coefficient": coef,
                "ci_lower": float(ci[0]), "ci_upper": float(ci[1]),
                "p_value": p,
                "note": _more_predictable_note(coef, p, run_label),
            })

            if coding_name == "fractional_score":
                chess960_slope = float(res.params["signed_gap"])
                standard_slope = chess960_slope + coef

                def _white_pred(signed_gap: float, is_standard: float) -> float:
                    return float(res.predict(pd.DataFrame(
                        {"const": [1.0], "signed_gap": [signed_gap], "corpus_standard": [is_standard],
                         "signed_gap_x_standard": [signed_gap * is_standard]}))[0])

                # White's expected score at gap=0 (first-move advantage alone,
                # no rating gap) — colour-neutral is trivially 0.5 here, so
                # only the White-side value is informative.
                scale_rows.append({
                    "run": run_label, "format": fmt, "gap": 0,
                    "chess960_slope_per_point": chess960_slope,
                    "standard_slope_per_point": standard_slope,
                    "chess960_white_expected_score": _white_pred(0, 0.0),
                    "standard_white_expected_score": _white_pred(0, 1.0),
                    "chess960_colour_neutral_expected_score": float("nan"),
                    "standard_colour_neutral_expected_score": float("nan"),
                    "elo_expected_score": 0.5,
                })

                for gap in (100, 200):
                    elo_pred = 1.0 / (1.0 + 10 ** (-gap / 400.0))
                    rows_by_corpus = {}
                    for name, is_standard in (("chess960", 0.0), ("standard", 1.0)):
                        p_plus = _white_pred(gap, is_standard)
                        p_minus = _white_pred(-gap, is_standard)
                        # colour-neutral expected score for the stronger
                        # player, averaged over which side (White/Black) the
                        # stronger player has: (p(+gap) + (1 - p(-gap))) / 2
                        colour_neutral = (p_plus + (1.0 - p_minus)) / 2.0
                        rows_by_corpus[name] = (p_plus, colour_neutral)
                    scale_rows.append({
                        "run": run_label, "format": fmt, "gap": gap,
                        "chess960_slope_per_point": chess960_slope,
                        "standard_slope_per_point": standard_slope,
                        "chess960_white_expected_score": rows_by_corpus["chess960"][0],
                        "standard_white_expected_score": rows_by_corpus["standard"][0],
                        "chess960_colour_neutral_expected_score": rows_by_corpus["chess960"][1],
                        "standard_colour_neutral_expected_score": rows_by_corpus["standard"][1],
                        "elo_expected_score": elo_pred,
                    })

    codings_df = pd.DataFrame(code_rows)
    scale_df = pd.DataFrame(scale_rows)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    codings_path = RESULTS_DIR / "c4_codings.csv"
    scale_path = RESULTS_DIR / "c4_elo_scale.csv"
    codings_df.to_csv(codings_path, index=False)
    scale_df.to_csv(scale_path, index=False)

    print(codings_df.round(6).to_string(index=False))
    print()
    print(scale_df.round(4).to_string(index=False))
    print(f"\n[c4_elo_scale] wrote {codings_path.name} ({len(codings_df)} rows), "
          f"{scale_path.name} ({len(scale_df)} rows)")
    return {"codings": codings_df, "scale": scale_df}


if __name__ == "__main__":
    main()
