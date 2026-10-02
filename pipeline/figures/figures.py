"""Plotting functions for the two paper figures: rating_accuracy_gradient_plot
(Figure 1: C1-adjacent gradient scatter + fit lines) and outcome_stacked_bars
(Figure 2: C4 game outcomes, 100% stacked bars). All matplotlib, 300 DPI,
Okabe-Ito colourblind-safe hex, write a PNG and return the Figure (no
plt.show).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless — before pyplot

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from pipeline.config import CORPUS_COLORS, FIG_DPI, OKABE_ITO

_FALLBACK_SERIES = (OKABE_ITO["vermillion"], OKABE_ITO["blue"], OKABE_ITO["bluish_green"],
                    OKABE_ITO["orange"], OKABE_ITO["reddish_purple"], OKABE_ITO["sky_blue"])


def _corpus_color(corpus: str, i: int) -> str:
    """Fixed colour for a known corpus, else a cycled Okabe-Ito fallback."""
    return CORPUS_COLORS.get(str(corpus).lower(), _FALLBACK_SERIES[i % len(_FALLBACK_SERIES)])


_CORPUS_LABELS = {"freestyle": "Chess960", "standard": "Standard"}


def _corpus_label(corpus: str) -> str:
    """Paper-facing corpus name — "freestyle" is internal, Figure 2 and the
    paper text both say "Chess960"."""
    return _CORPUS_LABELS.get(str(corpus).lower(), str(corpus))


def _save(fig: plt.Figure, output_path: str | Path, dpi: int) -> None:
    """Save fig as a tightly-cropped PNG, creating parent dirs as needed."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    print(f"[figures] wrote {out}  ({dpi} dpi)")


# --------------------------------------------------------------------------- #
# rating_accuracy_gradient_plot                                                #
# --------------------------------------------------------------------------- #


def rating_accuracy_gradient_plot(
    game_features: pd.DataFrame,
    gradient_results: pd.DataFrame,
    output_path: str | Path,
    *,
    rating_col: str = "own_rating",
    acpl_col: str = "opening_acpl",
    corpus_col: str = "corpus",
    format_col: str = "format",
    formats: tuple[str, ...] = ("classical", "rapid"),
    dpi: int = FIG_DPI,
) -> plt.Figure:
    """opening_acpl vs. own_rating, one fitted OLS line per corpus, one panel per
    format — the primary visual for the rating-accuracy-gradient finding.
    gradient_results only supplies the official interaction p-value to annotate each
    panel; the plotted lines are refit directly from game_features (same OLS the
    official test used, just without the intercept term the results CSV doesn't store)."""
    work = game_features.copy()
    work[rating_col] = pd.to_numeric(work[rating_col], errors="coerce")
    work[acpl_col] = pd.to_numeric(work[acpl_col], errors="coerce")
    work = work.dropna(subset=[rating_col, acpl_col])

    # y-axis is clipped to the 99.5th percentile for readability — a handful
    # of blunder-heavy openings (up to CPL_CAP) would otherwise compress the
    # entire meaningful 0-80cp range, where the actual slope difference
    # lives, into a sliver at the bottom of the plot. Every point still
    # contributes to the fitted line; only the visible axis range is capped.
    y_cap = float(np.ceil(work[acpl_col].quantile(0.995) / 10.0) * 10.0)

    corpora = list(dict.fromkeys(work[corpus_col]))
    fig, axes = plt.subplots(1, len(formats), figsize=(6.5 * len(formats), 5.5), sharey=True)
    if len(formats) == 1:
        axes = [axes]

    for ax, fmt in zip(axes, formats):
        fdf = work[work[format_col] == fmt]
        for ci, corp in enumerate(corpora):
            s = fdf[fdf[corpus_col] == corp]
            if s.empty:
                continue
            col = _corpus_color(corp, ci)
            alpha = float(np.clip(1500.0 / max(len(s), 1), 0.03, 0.5))
            ax.scatter(s[rating_col], s[acpl_col], s=7, alpha=alpha, color=col, edgecolors="none")
            if len(s) >= 2:
                slope, intercept = np.polyfit(s[rating_col], s[acpl_col], 1)
                xs = np.linspace(s[rating_col].min(), s[rating_col].max(), 50)
                ax.plot(xs, intercept + slope * xs, color=col, linewidth=2.5,
                        label=f"{_corpus_label(corp)} ({slope * 100:+.2f} / 100 pts)")

        ax.set_ylim(0, y_cap)

        p_row = gradient_results[gradient_results[format_col] == fmt]
        if len(p_row):
            p_val = float(p_row["interaction_p_value"].iloc[0])
            p_str = f"p = {p_val:.2e}" if p_val < 0.001 else f"p = {p_val:.4f}"
            ax.text(0.03, 0.97, f"slope-difference\ninteraction: {p_str}",
                    transform=ax.transAxes, ha="left", va="top", fontsize=10,
                    bbox=dict(boxstyle="round", facecolor="white", edgecolor="#888888", alpha=0.9))

        ax.set_title(fmt.capitalize(), fontsize=13, fontweight="bold")
        ax.set_xlabel("player rating  (Elo)", fontsize=10)
        ax.legend(frameon=False, fontsize=9, loc="upper right")
        ax.grid(alpha=0.25, linewidth=0.6)
        ax.set_axisbelow(True)

    axes[0].set_ylabel("opening ACPL  (centipawns, moves 1-15)", fontsize=10)
    fig.suptitle("Opening accuracy by rating: the absolute gap between stronger and weaker "
                 "players is larger in Chess960",
                 fontsize=13, y=1.02)
    fig.text(0.5, -0.02, f"y-axis capped at {y_cap:.0f}cp (99.5th percentile) for readability — "
             "all points, including outliers above the cap, are included in the fitted lines",
             ha="center", fontsize=8, style="italic", color="#555555")
    _save(fig, output_path, dpi)
    return fig


# --------------------------------------------------------------------------- #
# outcome_stacked_bars                                                         #
# --------------------------------------------------------------------------- #

_OUTCOME_COLORS: dict[str, str] = {
    "underdog_win": OKABE_ITO["orange"],
    "draw": "#BBBBBB",
    "favourite_win": OKABE_ITO["blue"],
}


def outcome_stacked_bars(
    outcomes: pd.DataFrame,
    output_path: str | Path,
    *,
    bin_labels: tuple[str, ...] = ("0-100", "101-250", "251+"),
    formats: tuple[str, ...] = ("classical", "rapid"),
    format_col: str = "format",
    gap_bin_col: str = "gap_bin",
    dpi: int = FIG_DPI,
) -> plt.Figure:
    """Game outcomes by rating-gap bin: 100% stacked bars, underdog win /
    draw / favorite win (bottom to top), one Chess960 bar and one standard
    bar per gap bin, one panel per format — the visual for Claim 4's
    descriptive outcome-shares supplement.
    Segment colour encodes outcome (consistent across every bar, draw in
    neutral grey); which bar is which corpus is shown by its own x-tick
    label, not colour. outcomes is c5_outcomes.csv's table (one row per
    (format, gap_bin), with chess960_*/standard_* outcome-share columns)."""
    fig, axes = plt.subplots(1, len(formats), figsize=(6.5 * len(formats), 5.6), sharey=True)
    if len(formats) == 1:
        axes = [axes]

    bar_width = 0.8
    pair_gap = 0.3
    group_gap = 1.0
    segments = (
        ("underdog_win", "underdog win"),
        ("draw", "draw"),
        ("favourite_win", "favorite win"),
    )

    for ax, fmt in zip(axes, formats):
        df = outcomes[outcomes[format_col] == fmt]
        xticks, xticklabels = [], []
        group_labels_x, group_labels_text = [], []
        x = 0.0
        legend_handles = {}

        for gb in bin_labels:
            row = df[df[gap_bin_col] == gb].iloc[0]
            bar_centers = []
            for corpus_label, prefix in (("Chess960", "chess960"), ("Standard", "standard")):
                bottom = 0.0
                for seg_key, seg_label in segments:
                    val = float(row[f"{prefix}_{seg_key}_pct"])
                    bar = ax.bar(x, val, bar_width, bottom=bottom,
                                 color=_OUTCOME_COLORS[seg_key], edgecolor="white", linewidth=0.6)
                    if val >= 5.0:
                        ax.text(x, bottom + val / 2, f"{val:.0f}%", ha="center", va="center",
                                 fontsize=8, color="white" if seg_key != "draw" else "#222222")
                    legend_handles.setdefault(seg_label, bar[0])
                    bottom += val
                xticks.append(x)
                xticklabels.append(corpus_label)
                bar_centers.append(x)
                x += bar_width + pair_gap
            group_labels_x.append(sum(bar_centers) / 2)
            group_labels_text.append(f"{gb}\nElo gap")
            x += group_gap

        ax.set_xticks(xticks)
        ax.set_xticklabels(xticklabels, fontsize=8, rotation=0)
        for gx, gt in zip(group_labels_x, group_labels_text):
            ax.annotate(gt, xy=(gx, -0.11), xycoords=("data", "axes fraction"),
                        ha="center", va="top", fontsize=9, fontweight="bold")
        ax.set_ylim(0, 100)
        ax.set_title(fmt.capitalize(), fontsize=13, fontweight="bold", pad=12)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    axes[0].set_ylabel("Share of games (%)")
    handles = list(legend_handles.values())
    labels = list(legend_handles.keys())
    fig.legend(handles, labels, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 1.04))
    fig.suptitle("Game outcomes by rating gap: underdog win, draw and favorite win, "
                 "Chess960 vs. standard chess", fontsize=13, y=1.1)
    fig.tight_layout()
    _save(fig, output_path, dpi)
    return fig
