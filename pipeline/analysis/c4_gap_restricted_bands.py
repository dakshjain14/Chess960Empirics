"""Per-band C4 check, a supplementary predictability model, not wired into
any pipeline stage — refits
the fractional-score model (c4_elo_scale.py's _fit —
two-way White/Black-player cluster-robust SEs), refit within each classical
band, restricted to |gap|<=250 so the two corpora's different rating-gap
compositions within a nominal band don't conflate with the corpus x gap
interaction being tested — "gap-restricted" describes what the |gap|<=250
cap does: restrict the comparison to a common gap range, not match
individual games by gap.

Also reports, per band, the minimum detectable effect (MDE) at alpha=0.05,
power=0.80 — (1.96 + 0.84) * SE — so a CI including zero can be read
against how large an effect that band's n could even detect.

Run:  PYTHONPATH=. .venv-pipeline/bin/python pipeline/analysis/c4_gap_restricted_bands.py
"""
from __future__ import annotations

import pandas as pd

from pipeline import run_pipeline as rp
from pipeline.analysis import hypothesis_tests as ht
from pipeline.analysis.c4_elo_scale import _fit, _pooled, _prep
from pipeline.banding import band_gap_builder as bg
from pipeline.config import RESULTS_DIR

_WHITE, _BLACK, _DRAW = ht._WHITE, ht._BLACK, ht._DRAW
BANDS = ["2400 to 2499", "2500 to 2599", "2600 to 2699", "2700 to 2799"]
GAP_CAP = 250.0
_Z_ALPHA, _Z_POWER = 1.959963984540054, 0.8416212335729143


def get_c34(corpus, fmt):
    df = pd.read_parquet(rp._paths(corpus, fmt, None)["scalars"])
    return bg.build_bands_c4c5(df).data


def main():
    fs_raw = get_c34("freestyle", "classical")
    std_raw = get_c34("standard", "classical")

    print(f"=== Per-band C4 check, gap<={GAP_CAP:.0f} only, classical, fractional-logit expected-score model ===\n")
    print("Rule: if the interaction 95% CI includes zero, predictability claim NOT supported at that band.\n")

    rows = []
    for band in BANDS:
        fs_b = fs_raw[(fs_raw.band.astype(str) == band)].copy()
        std_b = std_raw[(std_raw.band.astype(str) == band)].copy()
        fs_prepped = _prep(fs_b)
        std_prepped = _prep(std_b)
        fs_prepped = fs_prepped[fs_prepped["signed_gap"].abs() <= GAP_CAP]
        std_prepped = std_prepped[std_prepped["signed_gap"].abs() <= GAP_CAP]
        n_fs, n_std = len(fs_prepped), len(std_prepped)

        print(f"--- band {band}: n_freestyle={n_fs}, n_standard={n_std} ---")
        if n_fs < 20 or n_std < 20:
            print("  insufficient_n (<20 in one corpus) — not fit\n")
            rows.append({"band": band, "n_freestyle": n_fs, "n_standard": n_std,
                         "interaction_coefficient": None, "ci_lower": None, "ci_upper": None,
                         "p_value": None, "excludes_zero": None, "min_detectable_effect": None,
                         "status": "insufficient_n"})
            continue

        pooled = _pooled(fs_prepped, std_prepped)
        fit = _fit(pooled, "score")
        coef = float(fit.params["signed_gap_x_standard"])
        ci_lo, ci_hi = fit.conf_int().loc["signed_gap_x_standard"]
        p = float(fit.pvalues["signed_gap_x_standard"])
        se = float(fit.bse["signed_gap_x_standard"])
        mde = (_Z_ALPHA + _Z_POWER) * se
        excludes_zero = (ci_lo > 0) or (ci_hi < 0)
        print(f"  interaction coefficient = {coef:.6f}")
        print(f"  95% CI = [{ci_lo:.6f}, {ci_hi:.6f}]")
        print(f"  p-value = {p:.4f}")
        print(f"  minimum detectable effect (alpha=.05, power=.80) = {mde:.6f}")
        print(f"  CI excludes zero: {excludes_zero}")
        print(f"  -> classical predictability claim {'SUPPORTED' if excludes_zero else 'NOT SUPPORTED'} at this band")
        print()
        rows.append({"band": band, "n_freestyle": n_fs, "n_standard": n_std,
                     "interaction_coefficient": coef, "ci_lower": float(ci_lo), "ci_upper": float(ci_hi),
                     "p_value": p, "excludes_zero": excludes_zero, "min_detectable_effect": mde,
                     "status": "ok"})

    out = pd.DataFrame(rows)
    path = RESULTS_DIR / "c4_interaction_by_band_classical.csv"
    out.to_csv(path, index=False)
    print(f"[c4_gap_restricted_bands] wrote {path.name} ({len(out)} rows)")
    return out


if __name__ == "__main__":
    main()
