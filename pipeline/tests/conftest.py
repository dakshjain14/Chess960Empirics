"""Shared test fixtures/helpers for pipeline/tests/."""
from __future__ import annotations

import numpy as np
import pandas as pd

_WHITE, _BLACK, _DRAW = "1-0", "0-1", "1/2-1/2"


def synthetic_games(n: int = 4000, seed: int = 12345) -> pd.DataFrame:
    """Generate n fake games with realistic Elo/result shape, for
    band_gap_builder tests (test_banding.py)."""
    rng = np.random.default_rng(seed)
    n_players = max(30, n // 20)
    pool = np.clip(rng.normal(2400, 180, n_players), 2000, 2900).round().astype(int)
    rows = []
    for i in range(n):
        wi, bi = rng.integers(0, n_players, 2)
        while bi == wi:
            bi = rng.integers(0, n_players)
        we, be = int(pool[wi]), int(pool[bi])
        exp_w = 1 / (1 + 10 ** (-(we - be) / 400))
        r = rng.random()
        result = _DRAW if r < 0.3 * np.exp(-abs(we - be) / 400) else (_WHITE if rng.random() < exp_w else _BLACK)
        rows.append({
            "game_id": f"SYN{i:06d}", "source_event": f"E{i % 5}", "source_type": "otb",
            "corpus": "freestyle", "format": "classical",
            "white_player": f"P{wi}", "black_player": f"P{bi}",
            "white_elo": we, "black_elo": be, "result": result,
        })
    return pd.DataFrame(rows)


def synthetic_two_corpora(n: int = 5000, seed: int = 12345) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build two synthetic corpora with an injected effect (chess960 given a
    flatter Elo/outcome signal), for hypothesis_tests.py's C4 interaction
    test (test_c3_c4_c5_coverage.py) — the "chess960 is less predictable"
    effect that test checks for."""
    rng = np.random.default_rng(seed)
    n_players = max(40, n // 20)
    pool = np.clip(rng.normal(2450, 170, n_players), 2000, 2900).round().astype(int)

    def make(corpus: str, chaos: bool) -> pd.DataFrame:
        rows = []
        for i in range(n):
            wi, bi = rng.integers(0, n_players, 2)
            while bi == wi:
                bi = rng.integers(0, n_players)
            we, be = int(pool[wi]), int(pool[bi])
            exp = 1 / (1 + 10 ** (-(we - be) / 400))
            if chaos:
                exp = 0.5 + (exp - 0.5) * 0.5
            dp = 0.30 * np.exp(-abs(we - be) / 400)
            r = rng.random()
            res = _DRAW if r < dp else (_WHITE if rng.random() < exp else _BLACK)
            rows.append({
                "game_id": f"{corpus}{i:06d}", "source_event": f"E{i % 6}", "source_type": "otb",
                "corpus": corpus, "format": "classical",
                "white_player": f"P{wi}", "black_player": f"P{bi}",
                "white_elo": we, "black_elo": be, "result": res,
            })
        return pd.DataFrame(rows)

    return make("chess960", chaos=True), make("standard", chaos=False)
