"""Central constants for the Chess960-vs-standard analysis pipeline.

No hardcoded file paths anywhere except this file. Every module imports
what it needs from here; nothing else in the codebase hardcodes a
threshold, depth, iteration count, or path.
"""

from __future__ import annotations

from pathlib import Path

# Filesystem layout
REPO_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_GAMES_DIR: Path = REPO_ROOT / "data" / "games"
FREESTYLE_MANIFEST_PATH: Path = DATA_GAMES_DIR / "Freestyle" / "freestyle_manifest.xlsx"
STANDARD_MANIFEST_PATH: Path = DATA_GAMES_DIR / "Standard" / "Standard_Manifest.xlsx"
PROCESSED_DIR: Path = REPO_ROOT / "data" / "processed"
RESULTS_DIR: Path = REPO_ROOT / "data" / "results"
DATA_RATING_LISTS_DIR: Path = REPO_ROOT / "data" / "Rating_lists"
UPDATED_RATINGS_DIR: Path = PROCESSED_DIR / "Updated_Ratings"
UPDATED_TIME_DIR: Path = PROCESSED_DIR / "Updated_Time"
UPDATED_ENGINE_EVAL_DIR: Path = PROCESSED_DIR / "Updated_engine_eval"

OPENING_WINDOW_MOVES: int = 15
CPL_CAP: int = 500
MATE_SCORE_CP: int = 100_000

# Filters
MIN_ELO: int = 2000

# Banding
MIN_CELL_COUNT: int = 20
BAND_STARTING_WIDTH: int = 100
GAP_STARTING_WIDTH: int = 50

# Hypothesis tests
BOOTSTRAP_ITERATIONS: int = 5000
WILSON_Z: float = 1.959963984540054
DEFAULT_SEED: int = 12345

# Figures
FIG_DPI: int = 300

OKABE_ITO: dict[str, str] = {
    "black": "#000000",
    "orange": "#E69F00",
    "sky_blue": "#56B4E9",
    "bluish_green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "vermillion": "#D55E00",
    "reddish_purple": "#CC79A7",
}

CORPUS_COLORS: dict[str, str] = {
    "freestyle": OKABE_ITO["vermillion"],
    "standard": OKABE_ITO["blue"],
}

# Canonical vocabulary
CORPORA: tuple[str, ...] = ("freestyle", "standard")
FORMATS: tuple[str, ...] = ("classical", "rapid")
SOURCE_TYPES: tuple[str, ...] = ("otb", "playin_online")
