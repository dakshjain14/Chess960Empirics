"""loto_c4_expected_score.py — leave-one-tournament-out robustness for C4's
fractional-score model (METHODOLOGY.md's C4 section). Reuses
c4_elo_scale.py's fractional-logit pooled-interaction fit (two-way
White/Black-player cluster-robust SEs), refit once per excluded
source_event, for classical and rapid.

The White-win LOTO check in robustness.py is kept alongside this one, but
only as a labelled sensitivity (it uses the white_win coding, not this
fractional-score model).

Writes loto_c4_expected_score.csv: baseline + [min, max] coefficient and
p-value across all exclusions, which exclusion produced each extreme, and
whether significance (CI excludes zero at alpha=0.05) ever flips.

Run:  PYTHONPATH=. .venv-pipeline/bin/python pipeline/analysis/loto_c4_expected_score.py
"""
from __future__ import annotations

import pandas as pd

from pipeline.analysis.c4_elo_scale import RUNS, _fit, _load, _pooled, _prep
from pipeline.config import RESULTS_DIR


def main() -> pd.DataFrame:
    rows = []
    for run_label, fmt in RUNS:
        fs = _prep(_load("freestyle", fmt))
        std = _prep(_load("standard", fmt))
        pooled_full = _pooled(fs, std)

        fs_raw = _load("freestyle", fmt)
        std_raw = _load("standard", fmt)
        events = sorted(set(fs_raw["source_event"].dropna().unique()) | set(std_raw["source_event"].dropna().unique()))

        base_res = _fit(pooled_full, "score")
        base_coef = float(base_res.params["signed_gap_x_standard"])
        base_p = float(base_res.pvalues["signed_gap_x_standard"])

        coefs, pvals, sig_flip = {}, {}, False
        for ev in events:
            fs_ex = fs_raw[fs_raw["source_event"] != ev]
            std_ex = std_raw[std_raw["source_event"] != ev]
            if len(fs_ex) == len(fs_raw) and len(std_ex) == len(std_raw):
                continue  # event not present in either corpus for this format
            pooled_ex = _pooled(_prep(fs_ex), _prep(std_ex))
            res = _fit(pooled_ex, "score")
            coef = float(res.params["signed_gap_x_standard"])
            p = float(res.pvalues["signed_gap_x_standard"])
            coefs[ev], pvals[ev] = coef, p
            ci = res.conf_int().loc["signed_gap_x_standard"]
            excludes_zero = bool(ci[0] > 0 or ci[1] < 0)
            base_excludes_zero = base_p < 0.05
            if excludes_zero != base_excludes_zero:
                sig_flip = True

        min_ev = min(coefs, key=coefs.get)
        max_ev = max(coefs, key=coefs.get)
        min_p_ev = min(pvals, key=pvals.get)
        max_p_ev = max(pvals, key=pvals.get)
        rows.append({
            "run": run_label, "format": fmt,
            "baseline_coef": base_coef, "baseline_p": base_p,
            "min_coef": coefs[min_ev], "min_coef_excluding": min_ev,
            "max_coef": coefs[max_ev], "max_coef_excluding": max_ev,
            "min_p": pvals[min_p_ev], "min_p_excluding": min_p_ev,
            "max_p": pvals[max_p_ev], "max_p_excluding": max_p_ev,
            "n_exclusions": len(coefs),
            "significance_ever_flips": sig_flip,
        })
        print(f"[loto_c4_expected_score] {run_label}: baseline coef={base_coef:.6f} p={base_p:.4f}, "
              f"{len(coefs)} exclusions, coef range [{coefs[min_ev]:.6f}, {coefs[max_ev]:.6f}], "
              f"p range [{pvals[min_p_ev]:.4f}, {pvals[max_p_ev]:.4f}], "
              f"significance ever flips: {sig_flip}")

    out = pd.DataFrame(rows)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "loto_c4_expected_score.csv"
    out.to_csv(path, index=False)
    print(f"\n[loto_c4_expected_score] wrote {path.name} ({len(out)} rows)")
    return out


if __name__ == "__main__":
    main()
