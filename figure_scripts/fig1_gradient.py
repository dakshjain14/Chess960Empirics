"""fig1_gradient.py — abstract Figure 1: rating-accuracy-gradient.

Thin driver for ``figures.rating_accuracy_gradient_plot``. Reads
``game_features.parquet`` and ``rating_accuracy_gradient_results.csv``
directly; no new computation.

Run:  PYTHONPATH=. .venv-pipeline/bin/python figure_scripts/fig1_gradient.py

(Lives outside pipeline/ deliberately — see figure_scripts/README.md.)
"""

from __future__ import annotations

import pandas as pd

from pipeline.config import PROCESSED_DIR, RESULTS_DIR
from pipeline.figures.figures import rating_accuracy_gradient_plot


def main() -> None:
    game_features = pd.read_parquet(PROCESSED_DIR / "game_features.parquet")
    gradient_results = pd.read_csv(RESULTS_DIR / "rating_accuracy_gradient_results.csv", comment="#")
    rating_accuracy_gradient_plot(
        game_features, gradient_results,
        RESULTS_DIR / "figures" / "fig1_gradient.png",
    )


if __name__ == "__main__":
    main()
