import numpy as np
import pandas as pd
import plotly.graph_objects as go

from config import (
    LIMIT_COLOR,
    LIMIT_LINE_WIDTH,
    LINE_COLOR,
    MARKER_SIZE,
    TITLE_FONT_SIZE,
    X_RANGE_PADDING_RATIO,
)


def _fmt(v) -> str:
    if v is None or pd.isna(v):
        return "?"
    return f"{v:g}"


def build_subject_figure(
    xs: np.ndarray,
    ys: np.ndarray,
    lo: float | None,
    hi: float | None,
    name: str,
    unit: str,
) -> go.Figure:
    shapes = []
    if lo is not None and not pd.isna(lo):
        shapes.append(
            dict(
                type="line",
                x0=float(lo), x1=float(lo),
                y0=0, y1=100,
                line=dict(dash="dash", color=LIMIT_COLOR, width=LIMIT_LINE_WIDTH),
            )
        )
    if hi is not None and not pd.isna(hi):
        shapes.append(
            dict(
                type="line",
                x0=float(hi), x1=float(hi),
                y0=0, y1=100,
                line=dict(dash="dash", color=LIMIT_COLOR, width=LIMIT_LINE_WIDTH),
            )
        )

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
        xrange = [dmin - pad, dmax + pad]
    else:
        xrange = None

    fig = go.Figure(
        data=[
            go.Scatter(
                x=xs.tolist() if isinstance(xs, np.ndarray) else xs,
                y=ys.tolist() if isinstance(ys, np.ndarray) else ys,
                mode="markers",
                marker=dict(color=LINE_COLOR, size=MARKER_SIZE),
                hovertemplate="score: %{x}<br>cum%: %{y:.2f}<extra></extra>",
                showlegend=False,
            )
        ],
        layout=dict(
            title=dict(
                text=f"{name}<br>({_fmt(lo)} ~ {_fmt(hi)} {unit})",
                font=dict(size=TITLE_FONT_SIZE),
                x=0.5,
                xanchor="center",
            ),
            xaxis=dict(range=xrange, title="score"),
            yaxis=dict(range=[0, 100], fixedrange=True, title="cum %"),
            shapes=shapes,
            margin=dict(l=50, r=20, t=50, b=40),
            paper_bgcolor="white",
            plot_bgcolor="white",
        ),
    )
    return fig
