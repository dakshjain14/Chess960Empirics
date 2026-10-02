# Figure scripts

Scripts that draw the two figures in the abstract. Each reads tracked files in `data/processed/` and `data/results/` and writes its PNG to `data/results/figures/`, overwriting the existing file. The CSVs behind each figure are the numbers to check; the scripts only draw them.

| Script | Figure | Data | Output |
|---|---|---|---|
| `fig1_gradient.py` | Figure 1: opening accuracy (ACPL) vs. rating, one fitted line per corpus, classical and rapid panels | `rating_accuracy_gradient_results.csv`, `game_features.parquet` | `fig1_gradient.png` |
| `fig2_outcomes.py` | Figure 2: game outcomes (underdog win / draw / favorite win) by rating-gap bin, Chess960 vs. standard | `c5_outcomes.csv` | `fig2_outcomes.png` |

```bash
PYTHONPATH=. .venv-pipeline/bin/python figure_scripts/fig1_gradient.py
PYTHONPATH=. .venv-pipeline/bin/python figure_scripts/fig2_outcomes.py
```
