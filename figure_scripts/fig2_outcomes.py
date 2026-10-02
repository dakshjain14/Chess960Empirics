"""fig2_outcomes.py — abstract Figure 2: game outcomes (underdog win / draw
/ favorite win) by rating-gap bin, Chess960 vs. standard chess.

Reads ``c5_outcomes.csv`` directly and calls
``pipeline.figures.figures.outcome_stacked_bars`` — no new computation.
Writes ``fig2_outcomes.png``.

Run:  PYTHONPATH=. .venv-pipeline/bin/python figure_scripts/fig2_outcomes.py

(Lives outside pipeline/ deliberately — see figure_scripts/README.md.)
"""

from __future__ import annotations

import pandas as pd

from pipeline.config import RESULTS_DIR
from pipeline.figures.figures import outcome_stacked_bars


def main() -> None:
    outcomes = pd.read_csv(RESULTS_DIR / "c5_outcomes.csv")
    out = RESULTS_DIR / "figures" / "fig2_outcomes.png"
    outcome_stacked_bars(outcomes, out)


if __name__ == "__main__":
    main()
