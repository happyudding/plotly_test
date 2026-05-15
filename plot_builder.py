import math

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import (
    COLS_PER_ROW,
    HI_LIMIT_COLOR,
    HORIZONTAL_SPACING,
    LIMIT_LINE_WIDTH,
    LINE_COLOR,
    LO_LIMIT_COLOR,
    ROW_GAP_PX,
    SUBPLOT_HEIGHT_PX,
    SUBPLOT_TITLE_FONT_SIZE,
    X_RANGE_PADDING_RATIO,
)
from data_loader import ExcelData
from preprocess import cumulative_distribution, to_numeric_clean


def _layout_metrics(rows: int) -> tuple[int, float]:
    total_height = SUBPLOT_HEIGHT_PX * rows + ROW_GAP_PX * max(rows - 1, 0)
    if rows <= 1:
        return total_height, 0.0
    vertical_spacing = ROW_GAP_PX / total_height
    return total_height, min(vertical_spacing, 0.9 / (rows - 1))


def _safe_horizontal_spacing(cols: int) -> float:
    if cols <= 1:
        return 0.0
    return min(HORIZONTAL_SPACING, 0.9 / (cols - 1))


def build_figure(data: ExcelData) -> go.Figure:
    n_subjects = len(data.subjects)
    rows = max(1, math.ceil(n_subjects / COLS_PER_ROW))
    total_height, vertical_spacing = _layout_metrics(rows)

    def _fmt(v: float) -> str:
        return "?" if v is None or pd.isna(v) else f"{v:g}"

    titles = []
    for i, name in enumerate(data.subjects):
        unit = data.units[i] if i < len(data.units) else ""
        lo = data.lo_limits[i] if i < len(data.lo_limits) else None
        hi = data.hi_limits[i] if i < len(data.hi_limits) else None
        range_part = f"({_fmt(lo)} ~ {_fmt(hi)} {unit})".strip()
        titles.append(f"{name}<br>{range_part}")
    titles += [""] * (rows * COLS_PER_ROW - n_subjects)

    fig = make_subplots(
        rows=rows,
        cols=COLS_PER_ROW,
        subplot_titles=titles,
        horizontal_spacing=_safe_horizontal_spacing(COLS_PER_ROW),
        vertical_spacing=vertical_spacing,
    )

    for idx in range(n_subjects):
        r = idx // COLS_PER_ROW + 1
        c = idx % COLS_PER_ROW + 1

        values = to_numeric_clean(data.scores.iloc[:, idx])
        xs, ys = cumulative_distribution(values)

        if xs.size > 0:
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="markers",
                    marker=dict(color=LINE_COLOR, size=5),
                    name=data.subjects[idx],
                    showlegend=False,
                    hovertemplate="score: %{x}<br>cum%: %{y:.2f}<extra></extra>",
                ),
                row=r,
                col=c,
            )

        lo = data.lo_limits[idx] if idx < len(data.lo_limits) else None
        hi = data.hi_limits[idx] if idx < len(data.hi_limits) else None

        if lo is not None and not pd.isna(lo):
            fig.add_vline(
                x=float(lo),
                line=dict(dash="dash", color=LO_LIMIT_COLOR, width=LIMIT_LINE_WIDTH),
                row=r,
                col=c,
            )
        if hi is not None and not pd.isna(hi):
            fig.add_vline(
                x=float(hi),
                line=dict(dash="dash", color=HI_LIMIT_COLOR, width=LIMIT_LINE_WIDTH),
                row=r,
                col=c,
            )

        fig.update_yaxes(range=[0, 100], fixedrange=True, row=r, col=c)

        domain_vals = []
        if xs.size > 0:
            domain_vals.extend([float(xs.min()), float(xs.max())])
        if lo is not None and not pd.isna(lo):
            domain_vals.append(float(lo))
        if hi is not None and not pd.isna(hi):
            domain_vals.append(float(hi))
        if domain_vals:
            dmin, dmax = min(domain_vals), max(domain_vals)
            span = dmax - dmin if dmax > dmin else max(abs(dmax), 1.0)
            pad = span * X_RANGE_PADDING_RATIO
            fig.update_xaxes(range=[dmin - pad, dmax + pad], row=r, col=c)

    for ann in fig["layout"]["annotations"]:
        ann["font"] = dict(size=SUBPLOT_TITLE_FONT_SIZE)

    fig.update_layout(
        height=total_height,
        title_text=f"Cumulative Distribution by Subject (n={n_subjects})",
        margin=dict(l=40, r=40, t=80, b=40),
        showlegend=False,
    )

    return fig
