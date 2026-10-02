"""engine_annotate_standalone.py — engine evaluation stage annotation, standalone.

Self-contained (no repo imports, runs anywhere): pip install chess + a
local Stockfish binary (--stockfish-path, STOCKFISH_PATH env var, or
`stockfish` on PATH).

For every PGN under --input-root, runs Stockfish (depth --depth) over each
game's opening window (2*--opening-moves plies), strips any pre-existing
[%eval] and writes ours in its place (white-POV, "0.24"/"#-3"), mirrored to
--output-root; [%clk] and other comment content is preserved.

Parallel at the file level: --workers processes, each with one persistent
single-threaded Stockfish instance, dispatched via
imap_unordered(chunksize=1) so uneven file sizes don't idle a worker.
Resumable at the file level only — a file whose output already has the
same game count as its input is skipped; an interrupted file is simply
redone from scratch next run (output is written only once a whole file's
games are analysed, so a crash never leaves a partial PGN behind).

Usage:
    python engine_annotate_standalone.py --input-root Updated_Time --output-root Updated_engine_eval
"""
from __future__ import annotations

import argparse
import atexit
import glob
import multiprocessing as mp
import os
import re
import shutil
import time
from pathlib import Path

import chess
import chess.engine
import chess.pgn

STOCKFISH_DEPTH = 20
OPENING_WINDOW_MOVES = 15
ENGINE_HASH_MB = 256
N_WORKERS = 8  # matches the production run's 8-core server (see ENGINE.md)

_STOCKFISH_CANDIDATES = (
    "/usr/local/bin/stockfish",
    "/usr/games/stockfish",
    "/usr/bin/stockfish",
    "/opt/homebrew/bin/stockfish",
    "/home/linuxbrew/.linuxbrew/bin/stockfish",
)


def resolve_stockfish_path(override: str | None = None) -> str:
    """--stockfish-path override -> STOCKFISH_PATH env var -> `which stockfish`
    -> conventional install locations -> spec default (may not exist)."""
    if override and os.access(override, os.X_OK):
        return override
    env = os.environ.get("STOCKFISH_PATH")
    if env and os.access(env, os.X_OK):
        return env
    found = shutil.which("stockfish")
    if found:
        return found
    for cand in _STOCKFISH_CANDIDATES:
        if os.access(cand, os.X_OK):
            return cand
    return "/usr/local/bin/stockfish"


_CHESS960_VARIANTS = {"chess960", "fischerandom", "fischerrandom", "960"}

_EVAL_RE = re.compile(r"\[%eval[^\]]*\]\s*")


def _starting_board(game: chess.pgn.Game) -> chess.Board:
    """Starting board for game, with Chess960 handled (Variant header, or a
    FEN header carrying file-letter castling rights)."""
    board = game.board()
    if game.headers.get("Variant", "").strip().lower() in _CHESS960_VARIANTS:
        board.chess960 = True
    fen = game.headers.get("FEN", "").strip()
    if fen and not board.chess960:
        parts = fen.split()
        castling = parts[2] if len(parts) > 2 else "-"
        if any(c in "ABCDEFGHabcdefgh" for c in castling):
            board.chess960 = True
    return board


def _open_engine(engine_path: str) -> chess.engine.SimpleEngine:
    """Threads=1, Hash=ENGINE_HASH_MB, MultiPV=1, full strength — one
    single-threaded engine per worker avoids SMP search nondeterminism.
    60s handshake timeout: Stockfish startup (exec + NNUE load) has been
    observed to take 6-8s+ even idle, close to python-chess's 10s default."""
    eng = chess.engine.SimpleEngine.popen_uci(engine_path, timeout=60.0)
    opts = {"Threads": 1, "Hash": ENGINE_HASH_MB, "MultiPV": 1, "UCI_LimitStrength": False}
    try:
        eng.configure({k: v for k, v in opts.items() if k in eng.options})
    except chess.engine.EngineError:  # pragma: no cover - non-Stockfish engines
        pass
    return eng


def _eval_str(pov_score: chess.engine.PovScore) -> str:
    """Lichess-style [%eval] string from White's POV: "0.24" or "#-3"."""
    white = pov_score.white()
    if white.is_mate():
        return f"#{white.mate()}"
    return f"{white.score() / 100:.2f}"


def analyze_opening(
    game: chess.pgn.Game,
    engine: chess.engine.SimpleEngine,
    depth: int = STOCKFISH_DEPTH,
    max_moves: int = OPENING_WINDOW_MOVES,
) -> list[str] | None:
    """Run engine over game's first max_moves full moves; return the
    per-ply white-POV eval strings (one per analysed ply), or None on any
    parse/engine failure (illegal move sequence, engine error)."""
    try:
        board = _starting_board(game)
        limit = chess.engine.Limit(depth=depth)
        max_plies = 2 * max_moves
        per_move_eval: list[str] = []

        for move in game.mainline_moves():
            if len(per_move_eval) >= max_plies:
                break
            if move not in board.legal_moves:
                return None
            board.push(move)
            score_after = engine.analyse(board, limit)["score"]
            per_move_eval.append(_eval_str(score_after))

        return per_move_eval if per_move_eval else None
    except (chess.engine.EngineError, chess.engine.EngineTerminatedError, ValueError, OSError):
        return None


def _strip_eval(comment: str | None) -> str:
    return _EVAL_RE.sub("", comment or "").strip()


def _with_eval(comment: str | None, eval_str: str) -> str:
    rest = _strip_eval(comment)
    tag = f"[%eval {eval_str}]"
    return f"{tag} {rest}" if rest else tag


def annotate_games(
    games: list[chess.pgn.Game],
    evals_by_index: dict[int, list[str]],
    out_path: str | Path,
    opening_moves: int = OPENING_WINDOW_MOVES,
) -> int:
    """Write out_path with our [%eval] on the first 2*opening_moves plies of
    each game (pre-existing [%eval] stripped everywhere); a game absent
    from evals_by_index gets a "no engine analysis" marker."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    max_plies = 2 * opening_moves
    n = 0

    with open(out_path, "w", encoding="utf-8") as fh:
        exporter = chess.pgn.FileExporter(fh)
        for i, game in enumerate(games):
            evals = evals_by_index.get(i)
            limit = 0 if evals is None else min(len(evals), max_plies)

            node = game
            ply = 0
            while node.variations:
                node = node.variations[0]
                if ply < limit:
                    node.comment = _with_eval(node.comment, str(evals[ply]))
                else:
                    node.comment = _strip_eval(node.comment)
                ply += 1

            if evals is None and game.variations:
                first = game.variations[0]
                first.comment = (f"{first.comment} " if first.comment else "") + \
                    "{ pipeline: no engine analysis }"

            game.accept(exporter)
            n += 1

    return n


_WORKER: dict = {}


def _init_worker(engine_path: str, depth: int, max_moves: int) -> None:
    """Pool initializer: open one persistent Stockfish instance per worker
    process, reused for every game in every file that worker handles."""
    eng = _open_engine(engine_path)
    _WORKER.update(engine=eng, depth=depth, max_moves=max_moves)
    atexit.register(lambda: _safe_quit(eng))


def _safe_quit(eng: chess.engine.SimpleEngine) -> None:
    try:
        eng.quit()
    except Exception:  # pragma: no cover
        pass


_EVENT_TAG_RE = re.compile(r"^\[Event ", re.MULTILINE)


def _count_games(path: str) -> int:
    with open(path, encoding="utf-8-sig") as f:
        return len(_EVENT_TAG_RE.findall(f.read()))


def build_pending_files(input_root: str, output_root: str) -> tuple[list[tuple[str, str]], int]:
    """Return (pending, n_already_done): pending is [(src, dst), ...] for
    every *.pgn under input_root not yet fully annotated at output_root."""
    pending = []
    n_already_done = 0
    pgn_files = sorted(glob.glob(os.path.join(input_root, "**", "*.pgn"), recursive=True))
    for src in pgn_files:
        rel = os.path.relpath(src, input_root)
        dst = os.path.join(output_root, rel)
        if os.path.exists(dst) and _count_games(dst) == _count_games(src):
            n_already_done += 1
            continue
        pending.append((src, dst))
    return pending, n_already_done


def _process_file(args: tuple[str, str]) -> dict:
    src, dst = args
    t0 = time.time()

    games = []
    with open(src, encoding="utf-8-sig") as fh:
        while True:
            game = chess.pgn.read_game(fh)
            if game is None:
                break
            games.append(game)

    evals_by_index = {}
    n_errors = 0
    for i, game in enumerate(games):
        evals = analyze_opening(game, _WORKER["engine"], depth=_WORKER["depth"], max_moves=_WORKER["max_moves"])
        if evals is None:
            n_errors += 1
            continue
        evals_by_index[i] = evals

    annotate_games(games, evals_by_index, dst, opening_moves=_WORKER["max_moves"])

    return {
        "basename": os.path.basename(src),
        "dst": dst,
        "n_games": len(games),
        "n_errors": n_errors,
        "elapsed": time.time() - t0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input-root", required=True, help="Root directory of input PGNs (searched recursively)")
    ap.add_argument("--output-root", required=True, help="Root directory for annotated output (mirrors input tree)")
    ap.add_argument("--workers", type=int, default=N_WORKERS)
    ap.add_argument("--depth", type=int, default=STOCKFISH_DEPTH)
    ap.add_argument("--opening-moves", type=int, default=OPENING_WINDOW_MOVES)
    ap.add_argument("--stockfish-path", default=None)
    args = ap.parse_args()

    engine_path = resolve_stockfish_path(args.stockfish_path)
    if not os.access(engine_path, os.X_OK):
        print(f"no runnable Stockfish binary found (tried {engine_path!r}) — "
              f"set STOCKFISH_PATH or pass --stockfish-path")
        raise SystemExit(1)

    # record the engine's own UCI id (e.g. "Stockfish 17.1") in the run's
    # output rather than relying on external knowledge of what's installed
    probe = _open_engine(engine_path)
    engine_id = probe.id.get("name", "<no id name reported>")
    _safe_quit(probe)
    print(f"engine: {engine_id}")

    pending, n_already_done = build_pending_files(args.input_root, args.output_root)
    print(f"{n_already_done} files already done, {len(pending)} pending "
          f"({args.workers} workers, depth={args.depth}, opening_moves={args.opening_moves}, "
          f"chunksize=1, engine={engine_path})")
    if not pending:
        print("nothing to do")
        return

    ctx = mp.get_context("spawn")
    t_start = time.time()
    n_done = 0
    n_games_total = 0
    n_errors_total = 0
    with ctx.Pool(
        args.workers,
        initializer=_init_worker,
        initargs=(engine_path, args.depth, args.opening_moves),
    ) as pool:
        for result in pool.imap_unordered(_process_file, pending, chunksize=1):
            n_done += 1
            n_games_total += result["n_games"]
            n_errors_total += result["n_errors"]
            err_note = f", {result['n_errors']} stockfish errors" if result["n_errors"] else ""
            elapsed = time.time() - t_start
            print(f"[{n_done}/{len(pending)}] {result['basename']}: "
                  f"{result['n_games']} games{err_note} "
                  f"in {result['elapsed']:.0f}s -> {result['dst']} "
                  f"(total elapsed {elapsed/60:.1f}m)")

    print(f"\ndone: {n_done} files, {n_games_total} games, "
          f"{n_errors_total} stockfish errors, {(time.time()-t_start)/60:.1f}m total")


if __name__ == "__main__":
    main()
