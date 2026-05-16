import numpy as np
import pandas as pd
import plotly.graph_objects as go

from config import (
    LIMIT_COLOR,
    LIMIT_LINE_WIDTH,
    MARKER_SIZE,
    TITLE_FONT_SIZE,
    X_RANGE_PADDING_RATIO,
)


def _fmt(v) -> str:
    if v is None or pd.isna(v):
        return "?"
    return f"{v:g}"


def build_subject_figure(
    traces: list[dict],
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
    for t in traces:
        xs = t["xs"]
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
        layout=dict(
            title=dict(
                text=f"{name}<br>({_fmt(lo)} ~ {_fmt(hi)} {unit})",
                font=dict(size=TITLE_FONT_SIZE),
                x=0.5,
                xanchor="center",
            ),
            xaxis=dict(
                range=xrange,
                title="score",
                ticks="outside",
                tickcolor="#666",
                ticklen=6,
                showgrid=True,
                gridcolor="#eee",
                zeroline=False,
                minor=dict(
                    ticks="outside",
                    ticklen=3,
                    tickcolor="#bbb",
                    showgrid=False,
                ),
            ),
            yaxis=dict(
                range=[0, 100],
                fixedrange=True,
                title="cum %",
                tickmode="array",
                tickvals=[0, 20, 40, 60, 80, 100],
                ticktext=["0%", "20%", "40%", "60%", "80%", "100%"],
                ticks="outside",
                tickcolor="#666",
                ticklen=6,
                showgrid=True,
                gridcolor="#eee",
                zeroline=False,
                minor=dict(
                    tickmode="linear",
                    tick0=0,
                    dtick=5,
                    ticks="outside",
                    ticklen=3,
                    tickcolor="#bbb",
                    showgrid=False,
                ),
            ),
            shapes=shapes,
            margin=dict(l=55, r=20, t=55, b=40),
            paper_bgcolor="white",
            plot_bgcolor="white",
            showlegend=True,
            legend=dict(
                orientation="v",
                yanchor="top",
                y=0.98,
                xanchor="left",
                x=0.02,
                bgcolor="rgba(255,255,255,0.85)",
                bordercolor="rgba(0,0,0,0.1)",
                borderwidth=1,
                font=dict(size=10),
            ),
        ),
    )

    for t in traces:
        xs = t["xs"]
        ys = t["ys"]
        school = t["school"]
        color = t["color"]
        fig.add_trace(
            go.Scatter(
                x=xs.tolist() if isinstance(xs, np.ndarray) else xs,
                y=ys.tolist() if isinstance(ys, np.ndarray) else ys,
                mode="markers",
                name=school,
                marker=dict(color=color, size=MARKER_SIZE),
                hovertemplate=(
                    f"<b>{school}</b><br>"
                    "score: %{x}<br>cum%: %{y:.2f}<extra></extra>"
                ),
                showlegend=True,
                cliponaxis=False,
            )
        )

    return fig
