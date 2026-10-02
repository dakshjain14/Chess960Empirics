"""Tests for run_pipeline orchestration. Stockfish runs separately via engine_annotate_standalone.py; this file never touches it."""

from __future__ import annotations

import pandas as pd
import pytest

from pipeline import run_pipeline
from pipeline.config import CORPORA, FORMATS, PROCESSED_DIR


def test_cli_requires_corpus_format_for_feature_stages(capsys):
    rc = run_pipeline.main(["--stage", "extract_scalars"])
    assert rc == 2
    assert "required" in capsys.readouterr().err


def test_cli_requires_corpus_format_even_with_only_one_given(capsys):
    rc = run_pipeline.main(["--stage", "extract_scalars", "--corpus", "freestyle"])
    assert rc == 2
    assert "required" in capsys.readouterr().err


# --- cross-path consistency: the H1 path (game_features.parquet) and the
# scalars path (C3/C4's {corpus}_{format}_scalars.parquet, four files) are
# two independently-built pipelines over the same underlying corpus, and
# should cover exactly the same games. A mismatch in either direction means
# the two paths disagree about which raw games exist in the corpus -- the
# class of bug this test catches (see A1).


_SCALARS_PATHS = [PROCESSED_DIR / f"{corpus}_{fmt}_scalars.parquet" for corpus in CORPORA for fmt in FORMATS]
_GAME_FEATURES_PATH = PROCESSED_DIR / "game_features.parquet"


@pytest.mark.skipif(
    not (_GAME_FEATURES_PATH.exists() and all(p.exists() for p in _SCALARS_PATHS)),
    reason="game_features.parquet / scalars parquets not present until the pipeline has been run",
)
def test_scalars_game_ids_equal_game_features_game_ids():
    gf_ids = set(pd.read_parquet(_GAME_FEATURES_PATH, columns=["game_id"])["game_id"])
    scalars_ids: set[str] = set()
    for path in _SCALARS_PATHS:
        scalars_ids |= set(pd.read_parquet(path, columns=["game_id"])["game_id"])

    missing_from_scalars = gf_ids - scalars_ids
    missing_from_gf = scalars_ids - gf_ids
    assert not missing_from_scalars and not missing_from_gf, (
        f"game_features.parquet and the four scalars files disagree on which games exist: "
        f"{len(missing_from_scalars)} game_id(s) in game_features.parquet but not in any scalars "
        f"file (e.g. {sorted(missing_from_scalars)[:5]}); "
        f"{len(missing_from_gf)} game_id(s) in a scalars file but not in game_features.parquet "
        f"(e.g. {sorted(missing_from_gf)[:5]})"
    )


# --- same consistency check, but per corpus/format rather than pooled: a
# pooled match (above) can hide an equal-sized mismatch in both directions
# within a single corpus/format, e.g. games misfiled from one format into
# another would cancel out in the aggregate counts.


@pytest.mark.skipif(
    not (_GAME_FEATURES_PATH.exists() and all(p.exists() for p in _SCALARS_PATHS)),
    reason="game_features.parquet / scalars parquets not present until the pipeline has been run",
)
@pytest.mark.parametrize("corpus", CORPORA)
@pytest.mark.parametrize("fmt", FORMATS)
def test_scalars_game_ids_equal_game_features_game_ids_per_corpus_format(corpus, fmt):
    gf = pd.read_parquet(_GAME_FEATURES_PATH, columns=["game_id", "corpus", "format"])
    gf_ids = set(gf.loc[(gf["corpus"] == corpus) & (gf["format"] == fmt), "game_id"])

    scalars_path = PROCESSED_DIR / f"{corpus}_{fmt}_scalars.parquet"
    scalars_ids = set(pd.read_parquet(scalars_path, columns=["game_id"])["game_id"])

    missing_from_scalars = gf_ids - scalars_ids
    missing_from_gf = scalars_ids - gf_ids
    assert not missing_from_scalars and not missing_from_gf, (
        f"{corpus}/{fmt}: game_features.parquet and {scalars_path.name} disagree on which games "
        f"exist: {len(missing_from_scalars)} game_id(s) in game_features.parquet but not in "
        f"{scalars_path.name} (e.g. {sorted(missing_from_scalars)[:5]}); "
        f"{len(missing_from_gf)} game_id(s) in {scalars_path.name} but not in game_features.parquet "
        f"(e.g. {sorted(missing_from_gf)[:5]})"
    )
